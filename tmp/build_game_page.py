"""Build a static, shareable YouTube timeline from a tracking review overlay.

Example:
    python build_game_page.py /path/to/overlay.json --video-duration 3867 \
        --output game_20260908_test_v2
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageOps


def observed_runs(frames: list[list[dict]], ids: set[str], fps: float,
                  source_start: float, video_duration: float) -> dict[str, list[dict]]:
    sightings: dict[str, list[int]] = defaultdict(list)
    for frame_index, boxes in enumerate(frames):
        for box in boxes:
            if box["id"] in ids:
                sightings[box["id"]].append(frame_index)

    result = {}
    for identity, indices in sightings.items():
        spans = []
        first = last = indices[0]
        for index in indices[1:]:
            if index <= last + 2:
                last = index
                continue
            spans.append((first, last))
            first = last = index
        spans.append((first, last))
        result[identity] = [
            {
                "left": round(100 * (source_start + first / fps) / video_duration, 6),
                "width": round(100 * (last - first + 1) / fps / video_duration, 6),
            }
            for first, last in spans
        ]
    return result


def portrait_for(person: dict, review_dir: Path) -> Path:
    choices = [photo for photo in person["photos"]
               if photo.get("correct") is not False]
    if not choices:
        choices = person["photos"]
    candidates = []
    for photo in choices:
        path = (review_dir / photo["src"]).resolve()
        if not path.is_file():
            continue
        with Image.open(path) as image:
            width, height = image.size
        candidates.append((width * height, path))
    if not candidates:
        raise FileNotFoundError(f"No appearance crop for {person['label']}")
    return max(candidates)[1]


def build(overlay_path: Path, output: Path, video_duration: float) -> None:
    overlay = json.loads(overlay_path.read_text())
    selected = [person for person in overlay["people"]
                if person["category"] == "player"]
    selected.sort(key=lambda person: int(person["label"][1:]))
    if not selected:
        raise ValueError("The review has no confirmed players")
    fps = float(overlay["fps"])
    source_start = float(overlay["clip_start_seconds"])
    source_end = source_start + float(overlay["duration"])
    if video_duration < source_end:
        raise ValueError("The full video duration is shorter than the tracked interval")
    runs = observed_runs(overlay["frames"], {person["id"] for person in selected},
                         fps, source_start, video_duration)
    output.mkdir(parents=True, exist_ok=True)
    images = output / "players"
    images.mkdir(exist_ok=True)
    people = []
    for person in selected:
        if person["id"] not in runs:
            raise ValueError(f"{person['label']} has no observations")
        name = f"player_{int(person['label'][1:]):02d}.jpg"
        source = portrait_for(person, overlay_path.parent)
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.thumbnail((180, 240), Image.Resampling.LANCZOS)
            image.save(images / name, "JPEG", quality=88, optimize=True)
        first = source_start + min(
            index for index, boxes in enumerate(overlay["frames"])
            if any(box["id"] == person["id"] for box in boxes)) / fps
        people.append({"id": person["id"], "name": person["label"],
                       "image": f"players/{name}", "first": round(first, 3),
                       "runs": runs[person["id"]]})

    data = {"videoId": "T4_94fyPL2c", "start": 0, "duration": video_duration,
            "trackedStart": source_start, "trackedEnd": source_end, "people": people}
    template = (Path(__file__).parent / "index.html").read_text()
    template = template.replace("<title>Game player timeline</title>",
                                "<title>CTS SEP08 · Barney & Friends vs Dream Team</title>")
    template = template.replace(
        '<header><div><div class="eyebrow">Match review</div><h1>Player timeline</h1></div><div class="window">Five-minute game window</div></header>',
        '<header><div><div class="eyebrow">CTS · September 8</div><h1>Barney &amp; Friends vs Dream Team</h1></div><div class="window">Full video · tracking from 9:39 to 34:22</div></header>')
    template = template.replace("<h2>Tracked appearances</h2>", "")
    template = re.sub(r"const DATA=.*?;\nconst palette=",
                      "const DATA=" + json.dumps(data, separators=(",", ":")) + ";\nconst palette=",
                      template, count=1, flags=re.S)
    template = template.replace(
        "const fmt=t=>`${Math.floor(t/60)}:${String(Math.floor(t%60)).padStart(2,'0')}`;",
        "const fmt=t=>{const h=Math.floor(t/3600),m=Math.floor(t%3600/60),s=String(Math.floor(t%60)).padStart(2,'0');return h?`${h}:${String(m).padStart(2,'0')}:${s}`:`${m}:${s}`};")
    (output / "index.html").write_text(template)
    (output / "page.json").write_text(json.dumps({
        "title": "CTS SEP08 · Barney & Friends vs Dream Team",
        "video_id": data["videoId"], "video_duration_seconds": video_duration,
        "tracked_interval_seconds": [source_start, source_end],
        "confirmed_identities": len(people),
    }, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("overlay", type=Path)
    parser.add_argument("--video-duration", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.overlay.expanduser().resolve(), args.output.expanduser().resolve(),
          args.video_duration)
