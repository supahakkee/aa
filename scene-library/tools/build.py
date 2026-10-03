#!/usr/bin/env python3
"""Merge catalog/*.json (scenes and their tags) with data/resolved.json (their clips).

    python3 tools/build.py                        # data/scenes.json, scenes.jsonl, scenes.js
    python3 tools/build.py --standalone out.html  # one self-contained page (thumbnails embedded)

Every scene must pass tools/validate.py first. The standalone page inlines the data and embeds
thumbnails as WebP data URIs (needs ffmpeg); its clips open on YouTube instead of playing inline,
for places where YouTube embeds are not allowed.
"""
import argparse
import base64
import json
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from resolve import RESOLVED, ROOT, load_catalog  # noqa: E402
from validate import TAXONOMY, check  # noqa: E402

import requests  # noqa: E402

DATA = ROOT / "data"
WINDOW = {"most-replayed": "most_replayed", "estimated": "estimated", "pinned": "hand_picked"}


def record(scene, clip):
    """The agent-facing record: identity, description, every facet, credits, then the clip."""
    out = {
        "id": scene["id"],
        "film": scene["film"],
        "year": scene["year"],
        "scene": scene["scene"],
        "what_happens": scene["what_happens"],
        "what_to_study": scene["why"],
    }
    out.update({facet: scene[facet] for facet in TAXONOMY})
    out.update({
        "period": scene["period"],
        "keywords": scene["keywords"],
        "director": scene.get("director", ""),
        "production_country": scene.get("country", ""),
        "crew": scene.get("craft", []),
        "awards": scene.get("accolades", []),
        "clip": {
            "file": f"clips/{scene['scene_type']}/{scene['id']}.mp4",
            "youtube_id": clip["video"],
            "youtube_url": f"https://www.youtube.com/watch?v={clip['video']}&t={clip['start']}s",
            "start": clip["start"],
            "end": clip["end"],
            "seconds": clip["end"] - clip["start"],
            "window": WINDOW[clip["pick"]],
            "source_title": clip["title"],
            "source_channel": clip["channel"],
            "source_views": clip.get("views", 0),
            "source_duration": clip["duration"],
            "replay_heat": clip.get("heat", ""),
            "alternates": [{"youtube_id": a["id"], "start": a.get("start", 0), "title": a["title"],
                            "channel": a["channel"]} for a in clip.get("alts", [])],
        },
    })
    return out


def merged():
    resolved = json.loads(RESOLVED.read_text()) if RESOLVED.exists() else {}
    scenes, missing, invalid = [], [], []
    for scene in load_catalog():
        problems = check(scene)
        if problems:
            invalid.append((scene["id"], problems))
            continue
        clip = resolved.get(scene["id"], {})
        if clip.get("status") != "ok":
            missing.append(scene["id"])
            continue
        scenes.append(record(scene, clip))
    return scenes, missing, invalid


def thumb_data_uri(video_id, cache_dir):
    out = cache_dir / f"{video_id}.webp"
    if not out.exists():
        r = requests.get(f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg", timeout=30)
        r.raise_for_status()
        src = cache_dir / f"{video_id}.jpg"
        src.write_bytes(r.content)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-vf", "scale=288:-2",
                        "-quality", "52", str(out)], check=True)
    return "data:image/webp;base64," + base64.b64encode(out.read_bytes()).decode()


def js(value):
    """JSON that cannot close a surrounding <script> element."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def standalone(payload, path):
    page = (ROOT / "index.html").read_text()
    body = page.split("<!-- @artifact-start -->", 1)[1].split("<!-- @artifact-end -->", 1)[0]
    body = re.sub(r"<!-- @head-end -->\s*</head>\s*<body>", "", body)
    body = re.sub(r'<script src="clips/manifest.js"[^>]*></script>\s*', "", body)
    cache = Path(tempfile.gettempdir()) / "scene-library-thumbs"
    cache.mkdir(exist_ok=True)
    videos = sorted({s["clip"]["youtube_id"] for s in payload["scenes"]})
    with ThreadPoolExecutor(8) as pool:
        thumbs = dict(zip(videos, pool.map(lambda v: thumb_data_uri(v, cache), videos)))
    data = (f"<script>window.SL_MODE='link';window.SCENE_DATA={js(payload)};"
            f"window.SCENE_THUMBS={js(thumbs)};</script>")
    body = body.replace('<script src="data/scenes.js"></script><!-- @data -->', data)
    Path(path).write_text(body.strip() + "\n")
    print(f"wrote {path} ({Path(path).stat().st_size / 1e6:.1f} MB, {len(payload['scenes'])} scenes)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--standalone", metavar="OUT.html")
    args = ap.parse_args()

    scenes, missing, invalid = merged()
    for sid, problems in invalid:
        print(f"invalid tags, skipped: {sid}: {'; '.join(problems)}")
    for sid in missing:
        print(f"no clip, skipped: {sid}")
    DATA.mkdir(exist_ok=True)
    facets = json.loads((ROOT / "taxonomy.json").read_text())["facets"]
    (DATA / "scenes.json").write_text(json.dumps(
        {"version": 2, "taxonomy": "taxonomy.json", "count": len(scenes), "scenes": scenes},
        indent=1, ensure_ascii=False) + "\n")
    with open(DATA / "scenes.jsonl", "w") as f:
        for s in scenes:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    payload = {"taxonomy": facets, "scenes": scenes}
    (DATA / "scenes.js").write_text(
        "// Generated by tools/build.py from catalog/*.json, taxonomy.json and data/resolved.json.\n"
        f"window.SCENE_DATA = {js(payload)};\n")
    print(f"{len(scenes)} scenes written, {len(missing)} without a clip, {len(invalid)} with invalid tags")
    if args.standalone:
        standalone(payload, args.standalone)
    sys.exit(1 if invalid else 0)


if __name__ == "__main__":
    main()
