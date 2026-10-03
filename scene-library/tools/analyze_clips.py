#!/usr/bin/env python3
"""Measure downloaded clips: shots, pace, aspect ratio, light, colour and motion, plus contact sheets.

Run after tools/download_clips.py, on the machine that holds the clips:

    pip install numpy scenedetect opencv-python-headless   # and ffmpeg
    python3 tools/analyze_clips.py                   # every downloaded clip not yet measured
    python3 tools/analyze_clips.py --force           # measure everything again
    python3 tools/analyze_clips.py --repick          # first replace 'estimated' windows with the
                                                     # busiest 30 s of each upload, re-download, then measure

For each clip it writes:
    clips/<scene_type>/<id>.sheet.jpg     4x3 contact sheet of 12 frames
    clips/<scene_type>/<id>.frames/NN.jpg the 12 frames (used by tools/embed.py)
    "measured" in clips/<scene_type>/<id>.json, and data/analysis.json for all clips:
      shots, avg_shot_seconds, cuts_per_minute, cut_times     editing pace
      width, height, fps, aspect_ratio, aspect_name           frame (letterboxing removed)
      brightness, contrast, saturation, warmth, lighting_key,
      colour, temperature, palette                            look
      motion, motion_level, motion_curve                      how much moves on screen
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from query import load_scenes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ANALYSIS = ROOT / "data" / "analysis.json"
RESOLVED = ROOT / "data" / "resolved.json"
FFMPEG_CUT_THRESHOLD = 0.2  # fallback when PySceneDetect is missing: ffmpeg scene score for a cut
SAMPLE_FPS = 4          # frames per second sampled for light, colour and motion
ASPECTS = {"4:3": 1.33, "1.37:1": 1.37, "1.66:1": 1.66, "16:9": 1.78, "1.85:1": 1.85, "2:1": 2.0,
           "2.20:1": 2.2, "2.39:1": 2.39, "2.76:1": 2.76}


def run(cmd, binary=False):
    return subprocess.run(cmd, capture_output=True, text=not binary, check=False)


def probe(path):
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
               "stream=width,height,r_frame_rate,sample_aspect_ratio:format=duration", "-of", "json", str(path)])
    info = json.loads(out.stdout or "{}")
    stream = (info.get("streams") or [{}])[0]
    num, _, den = stream.get("r_frame_rate", "0/1").partition("/")
    sar = stream.get("sample_aspect_ratio", "1:1")
    sar = (int(sar.split(":")[0]) / int(sar.split(":")[1])) if re.match(r"^\d+:\d+$", sar) and sar != "0:1" else 1.0
    return {
        "width": stream.get("width", 0), "height": stream.get("height", 0),
        "fps": round(int(num) / int(den or 1), 3) if num.isdigit() else 0,
        "duration": float(info.get("format", {}).get("duration", 0) or 0), "sar": sar,
    }


def active_area(path, info):
    """The picture inside any letterbox or pillarbox bars (largest area over the whole clip)."""
    out = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vf", "fps=2,cropdetect=limit=24:round=2:reset=0",
               "-an", "-f", "null", "-"])
    crops = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", out.stderr)
    w, h = info["width"], info["height"]
    if crops:
        cw, ch, cx, cy = map(int, crops[-1])
        if cw >= w * 0.5 and ch >= h * 0.4:  # ignore detections fooled by near-black scenes
            return cw, ch, cx, cy
    return w, h, 0, 0


def detect_cuts(path, crop, threshold=FFMPEG_CUT_THRESHOLD, scale=320):
    """Cut times in seconds. PySceneDetect's content detector when installed (it copes with dark
    footage); otherwise ffmpeg's scene-change score."""
    try:
        from scenedetect import ContentDetector, detect
        scenes = detect(str(path), ContentDetector(threshold=27, min_scene_len=8))
        return [round(start.seconds if hasattr(start, "seconds") else start.get_seconds(), 2)
                for start, _ in scenes[1:]]
    except ImportError:
        pass
    cw, ch, cx, cy = crop
    vf = f"crop={cw}:{ch}:{cx}:{cy},scale={scale}:-2,select='gt(scene,{threshold})',showinfo"
    out = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vf", vf, "-an", "-f", "null", "-"])
    cuts = []
    for t in re.findall(r"pts_time:([\d.]+)", out.stderr):
        t = float(t)
        if not cuts or t - cuts[-1] > 0.3:  # merge flashes and double-detections
            cuts.append(round(t, 2))
    return cuts


def sample_frames(path, crop, fps=SAMPLE_FPS, width=96):
    cw, ch, cx, cy = crop
    height = max(2, int(round(width * ch / cw / 2)) * 2)
    out = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vf",
               f"fps={fps},crop={cw}:{ch}:{cx}:{cy},scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
              binary=True)
    data = np.frombuffer(out.stdout, dtype=np.uint8)
    frames = data[: len(data) // (width * height * 3) * (width * height * 3)]
    return frames.reshape(-1, height, width, 3).astype(np.float32) / 255.0


def palette(pixels, k=6, iterations=12, sample=8000, seed=7):
    rng = np.random.default_rng(seed)
    px = pixels.reshape(-1, 3)
    px = px[rng.choice(len(px), size=min(sample, len(px)), replace=False)]
    luma = px @ np.array([0.2126, 0.7152, 0.0722])
    centres = px[np.argsort(luma)[np.linspace(0, len(px) - 1, k).astype(int)]]  # spread across the tonal range
    for _ in range(iterations):
        labels = np.argmin(((px[:, None, :] - centres[None]) ** 2).sum(-1), axis=1)
        for j in range(k):
            if (labels == j).any():
                centres[j] = px[labels == j].mean(0)
    shares = np.bincount(labels, minlength=k) / len(labels)
    order = np.argsort(-shares)
    return [{"hex": "#%02x%02x%02x" % tuple(int(round(c * 255)) for c in centres[j]), "share": round(float(shares[j]), 3)}
            for j in order if shares[j] > 0.01]


def look_and_motion(frames):
    y = frames @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    mx, mn = frames.max(-1), frames.min(-1)
    saturation = float(((mx - mn) / (mx + 1e-6)).mean())
    warmth = float(frames[..., 0].mean() - frames[..., 2].mean())
    brightness, contrast = float(y.mean()), float(y.std())
    diffs = np.abs(np.diff(y, axis=0)).mean(axis=(1, 2)) if len(y) > 1 else np.zeros(1)
    per_second = [float(diffs[i:i + SAMPLE_FPS].mean()) for i in range(0, len(diffs), SAMPLE_FPS)]
    motion = float(diffs.mean())
    return {
        "brightness": round(brightness, 3), "contrast": round(contrast, 3), "saturation": round(saturation, 3),
        "warmth": round(warmth, 3),
        "lighting_key": "low_key" if brightness < 0.25 else "high_key" if brightness > 0.55 else "mid_key",
        "colour": "monochrome" if saturation < 0.06 else "muted" if saturation < 0.25 else "natural" if saturation < 0.45 else "vivid",
        "temperature": "warm" if warmth > 0.04 else "cool" if warmth < -0.04 else "neutral",
        "palette": palette(frames),
        "motion": round(motion, 4),
        "motion_level": "calm" if motion < 0.02 else "moderate" if motion < 0.05 else "intense" if motion < 0.09 else "frenetic",
        "motion_curve": "".join(str(min(9, int(v / 0.015))) for v in per_second),
    }


def contact_sheet(path, crop, duration, out_dir, sheet, count=12):
    cw, ch, cx, cy = crop
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    rate = count / max(duration, 1)
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vf",
         f"fps={rate:.5f},crop={cw}:{ch}:{cx}:{cy},scale=480:-2", "-frames:v", str(count), "-q:v", "3",
         str(out_dir / "%02d.jpg")])
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(out_dir / "%02d.jpg"), "-vf",
         "tile=4x3:padding=4:margin=4:color=black", "-frames:v", "1", "-q:v", "3", str(sheet)])
    return len(list(out_dir.glob("*.jpg")))


def aspect_name(ratio):
    return min(ASPECTS, key=lambda name: abs(ASPECTS[name] - ratio))


def measure(path, folder, scene_id):
    info = probe(path)
    crop = active_area(path, info)
    ratio = crop[0] * info["sar"] / crop[1]
    cuts = detect_cuts(path, crop)
    duration = info["duration"] or 30
    frames = sample_frames(path, crop)
    shots = len(cuts) + 1
    result = {
        "seconds": round(duration, 2), "width": info["width"], "height": info["height"], "fps": info["fps"],
        "aspect_ratio": round(ratio, 2), "aspect_name": aspect_name(ratio),
        "letterboxed": crop[1] < info["height"] * 0.95 or crop[0] < info["width"] * 0.95,
        "shots": shots, "avg_shot_seconds": round(duration / shots, 2),
        "cuts_per_minute": round(len(cuts) / duration * 60, 1), "cut_times": cuts,
        "pace": "long_take" if shots == 1 else "slow" if duration / shots > 6 else "moderate" if duration / shots > 3
                else "fast" if duration / shots > 1.5 else "rapid",
    }
    result.update(look_and_motion(frames) if len(frames) else {})
    result["frames"] = contact_sheet(path, crop, duration, folder / f"{scene_id}.frames", folder / f"{scene_id}.sheet.jpg")
    return result


# ---------- Re-picking estimated windows ----------

def busiest_window(path, clip=30):
    """Start second of the 30 s with the most motion and cutting in a full upload."""
    info = probe(path)
    crop = active_area(path, info)
    frames = sample_frames(path, crop, fps=2, width=64)
    y = frames @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    seconds = len(y) // 2
    if seconds <= clip + 4:
        return None
    motion = np.abs(np.diff(y, axis=0)).mean(axis=(1, 2))
    motion = np.array([motion[i * 2:i * 2 + 2].mean() for i in range(seconds - 1)])
    cut_density = np.zeros(seconds)
    for t in detect_cuts(path, crop, scale=160):
        if int(t) < seconds:
            cut_density[int(t)] += 1
    z = lambda a: (a - a.mean()) / (a.std() + 1e-9)
    score = z(np.convolve(motion, np.ones(clip), "valid")) + 0.6 * z(np.convolve(cut_density[:len(motion)], np.ones(clip), "valid"))
    edge = max(2, int(seconds * 0.04))  # skip intros and end cards
    score[:edge] = score[-edge:] = -np.inf
    return max(0, int(np.argmax(score)) - 1)


def repick(scenes, clips_dir, args):
    sys.path.insert(0, str(Path(__file__).parent))
    from download_clips import ytdlp_base
    resolved = json.loads(RESOLVED.read_text())
    targets = [s for s in scenes if s["clip"]["window"] == "estimated" and s["id"] in resolved]
    print(f"re-picking {len(targets)} estimated windows (downloads each full upload at 360p, then deletes it)")
    changed = []
    with tempfile.TemporaryDirectory() as tmp:
        for n, s in enumerate(targets, 1):
            vid = s["clip"]["youtube_id"]
            src = Path(tmp) / f"{vid}.mp4"
            cmd = ytdlp_base(args) + ["-f", "bv*[height<=360]/b[height<=360]/worst", "-o", str(src),
                                      f"https://www.youtube.com/watch?v={vid}"]
            if run(cmd).returncode != 0 or not src.exists():
                print(f"[{n}/{len(targets)}] ✗ {s['id']}: download failed")
                continue
            start = busiest_window(src)
            src.unlink(missing_ok=True)
            entry = resolved[s["id"]]
            if start is None or entry.get("video") != vid:
                print(f"[{n}/{len(targets)}] · {s['id']}: kept")
                continue
            entry.update(start=start, end=min(entry["duration"], start + 30), pick="motion-peak")
            changed.append(s["id"])
            print(f"[{n}/{len(targets)}] ✓ {s['id']}: window now {start}-{start + 30}s")
    RESOLVED.write_text(json.dumps(resolved, indent=1, ensure_ascii=False, sort_keys=True))
    if changed:
        subprocess.run([sys.executable, str(ROOT / "tools" / "build.py")], check=False)
        dl = [sys.executable, str(ROOT / "tools" / "download_clips.py"), "--force", "--out", str(clips_dir), "--ids", *changed]
        if args.cookies_from_browser:
            dl += ["--cookies-from-browser", args.cookies_from_browser]
        subprocess.run(dl, check=False)
    return changed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clips", type=Path, default=ROOT / "clips", help="clips folder (default clips/)")
    ap.add_argument("--force", action="store_true", help="measure clips that were already measured")
    ap.add_argument("--repick", action="store_true", help="improve estimated windows first (needs yt-dlp)")
    ap.add_argument("--cookies-from-browser", metavar="BROWSER")
    ap.add_argument("--cookies", type=Path)
    ap.add_argument("--ids", nargs="+", help="only these scene ids")
    ap.add_argument("--workers", type=int, default=4, help="clips measured in parallel (default 4)")
    args = ap.parse_args()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        sys.exit("needs ffmpeg and ffprobe on PATH")

    scenes = [s for s in load_scenes() if not args.ids or s["id"] in args.ids]
    repicked = set(repick(scenes, args.clips, args)) if args.repick else set()
    analysis = json.loads(ANALYSIS.read_text()) if ANALYSIS.exists() else {}
    todo = []
    for s in scenes:
        clip = args.clips / s["scene_type"] / f"{s['id']}.mp4"
        if clip.exists() and (args.force or s["id"] not in analysis or s["id"] in repicked):
            todo.append((s, clip))
    print(f"measuring {len(todo)} clips with {args.workers} workers")

    def work(item):
        s, clip = item
        try:
            return s, clip, measure(clip, clip.parent, s["id"]), None
        except Exception as e:  # a corrupt file should not stop the run
            return s, clip, None, e

    with ThreadPoolExecutor(args.workers) as pool:
        for n, (s, clip, m, err) in enumerate(pool.map(work, todo), 1):
            if err:
                print(f"[{n}/{len(todo)}] ✗ {s['id']}: {err}")
                continue
            analysis[s["id"]] = m
            sidecar = clip.with_suffix(".json")
            if sidecar.exists():
                record = json.loads(sidecar.read_text())
                record["measured"] = m
                sidecar.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
            print(f"[{n}/{len(todo)}] {s['id']}: {m['shots']} shots, {m['avg_shot_seconds']}s avg, "
                  f"{m['aspect_name']}, {m.get('lighting_key')}, motion {m.get('motion_level')}", flush=True)
            if n % 10 == 0:
                ANALYSIS.write_text(json.dumps(analysis, indent=1, ensure_ascii=False, sort_keys=True))
    ANALYSIS.write_text(json.dumps(analysis, indent=1, ensure_ascii=False, sort_keys=True))
    from download_clips import write_indexes
    if args.clips.exists():
        write_indexes(args.clips)
    print(f"{len(analysis)} clips measured in total; results in {ANALYSIS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
