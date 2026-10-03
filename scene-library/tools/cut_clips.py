#!/usr/bin/env python3
"""Save the 30-second windows as local MP4 files for offline study, mood reels and pre-vis edits.

Downloads only each scene's window (not the whole video) with yt-dlp and ffmpeg, into
clips/<category>/<scene-id>.mp4. clips/ is git-ignored. For personal reference only: the footage
belongs to its rights holders, so don't publish or redistribute the files.

    pip install yt-dlp                                  # once; ffmpeg must also be installed
    python3 tools/cut_clips.py --category gunfights     # one bin
    python3 tools/cut_clips.py --list pull-list.txt     # text copied from "Copy pull list"
    python3 tools/cut_clips.py --ids heat-1995-bank-shootout --pad 5
    python3 tools/cut_clips.py --all --height 720
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    pick = ap.add_mutually_exclusive_group(required=True)
    pick.add_argument("--all", action="store_true", help="every scene in the library")
    pick.add_argument("--category", nargs="+", help="category keys, e.g. gunfights space-battle")
    pick.add_argument("--ids", nargs="+", help="scene ids")
    pick.add_argument("--list", type=Path, help="file containing scene ids (e.g. a copied pull list)")
    ap.add_argument("--pad", type=int, default=0, help="extra seconds before and after the window")
    ap.add_argument("--height", type=int, default=1080, help="maximum video height (default 1080)")
    ap.add_argument("--out", type=Path, default=ROOT / "clips")
    args = ap.parse_args()

    if not shutil.which("yt-dlp") or not shutil.which("ffmpeg"):
        sys.exit("needs yt-dlp and ffmpeg on PATH (pip install yt-dlp; ffmpeg from your package manager)")

    scenes = json.loads((ROOT / "data" / "scenes.json").read_text())["scenes"]
    if args.category:
        scenes = [s for s in scenes if s["category"] in args.category]
    elif args.list:
        # Accept a copied pull list ("... [scene-id]") or one scene id per line.
        text = args.list.read_text()
        wanted = set(re.findall(r"\[([a-z0-9-]+)\]", text)) | {line.strip() for line in text.splitlines()}
        scenes = [s for s in scenes if s["id"] in wanted]
    elif args.ids:
        scenes = [s for s in scenes if s["id"] in set(args.ids)]
    if not scenes:
        sys.exit("no matching scenes")

    done = failed = 0
    for s in scenes:
        target = args.out / s["category"] / f"{s['id']}.mp4"
        if target.exists():
            done += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        start = max(0, s["start"] - args.pad)
        end = s["end"] + args.pad
        print(f"[{done + failed + 1}/{len(scenes)}] {s['film']} ({s['year']}) — {s['scene']}  {start}s–{end}s")
        cmd = ["yt-dlp", "--quiet", "--no-warnings", "--no-playlist",
               "-f", f"bv*[height<={args.height}][ext=mp4]+ba[ext=m4a]/b[height<={args.height}]/b",
               "--merge-output-format", "mp4", "--download-sections", f"*{start}-{end}",
               "--force-keyframes-at-cuts", "-o", str(target),
               f"https://www.youtube.com/watch?v={s['video']}"]
        if subprocess.run(cmd).returncode == 0 and target.exists():
            done += 1
        else:
            failed += 1
            print(f"  failed: {s['id']}")
    print(f"{done} clips in {args.out}, {failed} failed")


if __name__ == "__main__":
    main()
