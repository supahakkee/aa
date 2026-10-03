#!/usr/bin/env python3
"""Download every scene's 30-second window as an MP4, organised for agents.

Run this on your own computer (YouTube refuses downloads from cloud servers):

    pip install -U yt-dlp                 # plus ffmpeg, e.g. brew install ffmpeg / apt install ffmpeg
    python3 tools/download_clips.py                        # all scenes
    python3 tools/download_clips.py scene_type=fight.blades region=japan
    python3 tools/download_clips.py genre=western --height 720 --pad 2
    python3 tools/download_clips.py --ids heat-1995-downtown-la-bank-robbery-shootout
    python3 tools/download_clips.py --cookies-from-browser chrome   # if YouTube asks you to sign in

Filters use the same facet=value syntax as tools/query.py (values in taxonomy.json; comma = OR).

Writes, for each scene:
    clips/<scene_type>/<id>.mp4      the clip (H.264/AAC MP4, max --height, default 1080p)
    clips/<scene_type>/<id>.json     the scene's full record plus "local_file" and download details
and for the whole set:
    clips/index.jsonl                one line per downloaded clip (the record + local_file)
    clips/manifest.js                lets index.html play the local files
    clips/report.json                what failed and why

Re-running skips clips that are already there, so an interrupted run resumes. If the main upload
fails, the alternates found by the resolver are tried. The files are for personal study and
reference: the footage belongs to its rights holders, so don't publish or redistribute it.
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from query import load_scenes, parse_filters, select  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def ytdlp_base(args):
    cmd = ["yt-dlp", "--quiet", "--no-warnings", "--no-playlist", "--no-progress",
           "--retries", "5", "--fragment-retries", "5"]
    # yt-dlp needs a JavaScript runtime for YouTube; it looks for deno, so point it at node if that's what exists.
    if not shutil.which("deno") and shutil.which("node"):
        cmd += ["--js-runtimes", "node"]
    if args.cookies_from_browser:
        cmd += ["--cookies-from-browser", args.cookies_from_browser]
    if args.cookies:
        cmd += ["--cookies", str(args.cookies)]
    return cmd


def probe_seconds(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
        return round(float(out.stdout.strip()), 1)
    except (ValueError, OSError):
        return None


def download(scene, args):
    clip = scene["clip"]
    target = args.out / scene["scene_type"] / f"{scene['id']}.mp4"
    sidecar = target.with_suffix(".json")
    if target.exists() and sidecar.exists() and not args.force:
        return {"id": scene["id"], "status": "skipped", "file": str(target)}
    target.parent.mkdir(parents=True, exist_ok=True)

    sources = [(clip["youtube_id"], clip["start"], clip["end"], "primary")]
    sources += [(a["youtube_id"], a["start"], a["start"] + 30, "alternate") for a in clip.get("alternates", [])]
    errors = []
    for video_id, start, end, kind in sources:
        start, end = max(0, start - args.pad), end + args.pad
        tmp = target.with_name(f".{target.stem}.part.mp4")
        cmd = ytdlp_base(args) + [
            "-f", f"bv*[height<={args.height}][vcodec^=avc1]+ba[ext=m4a]/bv*[height<={args.height}]+ba/b[height<={args.height}]/b",
            "--merge-output-format", "mp4", "--remux-video", "mp4",
            "--download-sections", f"*{start}-{end}", "--force-keyframes-at-cuts",
            "-o", str(tmp), f"https://www.youtube.com/watch?v={video_id}",
        ]
        for attempt in range(2):
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 and tmp.exists():
                break
            time.sleep(3 * (attempt + 1))
        if result.returncode != 0 or not tmp.exists():
            message = (result.stderr.strip().splitlines() or ["unknown error"])[-1]
            errors.append(f"{kind} {video_id}: {message}")
            tmp.unlink(missing_ok=True)
            if "Sign in to confirm" in message and not (args.cookies or args.cookies_from_browser):
                errors.append("YouTube wants a signed-in session: re-run with --cookies-from-browser chrome (or firefox, safari, edge)")
                break
            continue
        tmp.replace(target)
        seconds = probe_seconds(target)
        record = dict(scene)
        record["local_file"] = str(target.relative_to(args.out.parent)) if args.out.parent in target.parents else str(target)
        record["download"] = {
            "youtube_id": video_id, "source": kind, "start": start, "end": end, "seconds": seconds,
            "max_height": args.height, "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        sidecar.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        return {"id": scene["id"], "status": "ok", "file": str(target), "source": kind, "seconds": seconds}
    return {"id": scene["id"], "status": "failed", "errors": errors}


def write_indexes(out):
    records = []
    for sidecar in sorted(out.glob("*/*.json")):
        record = json.loads(sidecar.read_text())
        if (out / record["scene_type"] / f"{record['id']}.mp4").exists():
            records.append(record)
    with open(out / "index.jsonl", "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    local = {r["id"]: f"{out.name}/{r['scene_type']}/{r['id']}.mp4" for r in records}
    (out / "manifest.js").write_text(
        "// Written by tools/download_clips.py: clips available on this machine.\n"
        f"window.LOCAL_CLIPS = {json.dumps(local, indent=1)};\n")
    return len(records)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("filters", nargs="*", help="facet=value filters, e.g. scene_type=chase.vehicle era=contemporary")
    ap.add_argument("--ids", nargs="+", help="only these scene ids")
    ap.add_argument("--text", help="only scenes whose text mentions this")
    ap.add_argument("--height", type=int, default=1080, help="maximum video height (default 1080)")
    ap.add_argument("--pad", type=int, default=0, help="extra seconds before and after the window")
    ap.add_argument("--workers", type=int, default=3, help="parallel downloads (default 3)")
    ap.add_argument("--out", type=Path, default=ROOT / "clips", help="output folder (default clips/)")
    ap.add_argument("--force", action="store_true", help="download again even if the clip exists")
    ap.add_argument("--cookies-from-browser", metavar="BROWSER", help="use your browser's YouTube session")
    ap.add_argument("--cookies", type=Path, help="cookies.txt file for YouTube")
    ap.add_argument("--dry-run", action="store_true", help="list what would be downloaded")
    args = ap.parse_args()

    scenes = select(load_scenes(), parse_filters(args.filters), text=args.text, ids=args.ids)
    if not scenes:
        sys.exit("no scenes match")
    if args.dry_run:
        for s in scenes:
            print(f"{s['scene_type']}/{s['id']}.mp4  {s['clip']['youtube_url']}")
        print(f"{len(scenes)} clips")
        return
    missing = [tool for tool in ("yt-dlp", "ffmpeg", "ffprobe") if not shutil.which(tool)]
    if missing:
        sys.exit(f"missing {', '.join(missing)}: pip install -U yt-dlp, and install ffmpeg "
                 "(brew install ffmpeg / sudo apt install ffmpeg / winget install ffmpeg)")

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"downloading {len(scenes)} clips to {args.out} (max {args.height}p, {args.workers} at a time)")
    results, done = [], 0
    with ThreadPoolExecutor(args.workers) as pool:
        for r in pool.map(lambda s: download(s, args), scenes):
            done += 1
            results.append(r)
            mark = {"ok": "✓", "skipped": "·", "failed": "✗"}[r["status"]]
            detail = r.get("source", "") if r["status"] == "ok" else "; ".join(r.get("errors", []))[:160]
            print(f"[{done}/{len(scenes)}] {mark} {r['id']} {detail}", flush=True)

    total = write_indexes(args.out)
    failed = [r for r in results if r["status"] == "failed"]
    (args.out / "report.json").write_text(json.dumps({"results": results}, indent=1, ensure_ascii=False) + "\n")
    print(f"{total} clips in {args.out}; {len(failed)} failed this run (details in report.json)")
    if failed:
        print("re-run the same command to retry the failures; see README for --cookies-from-browser")


if __name__ == "__main__":
    main()
