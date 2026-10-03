#!/usr/bin/env python3
"""Build the CLIP index behind "find similar" and plain-language search (data/embeddings.npz).

    pip install fastembed numpy requests
    python3 tools/embed.py            # frames from analysed clips where available, else YouTube thumbnails

Each scene gets an image vector, the average of its frames (the 12 frames tools/analyze_clips.py
saves, or the YouTube thumbnail plus three automatic frames when the clip is not downloaded), and
a text vector for its description and tags, both in CLIP's shared space. Re-run it after
analysing clips: scenes then switch from thumbnails to their own frames.
"""
import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).parent))
from query import load_scenes  # noqa: E402
from semantic import IMAGE_MODEL, TEXT_MODEL  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "embeddings.npz"
CACHE = Path.home() / ".cache" / "set-piece-vault" / "thumbs"
THUMBS = ["mqdefault", "mq1", "mq2", "mq3"]  # uploader's thumbnail + frames at 25/50/75% of the upload


def thumbnails(video_id):
    paths = []
    for name in THUMBS:
        path = CACHE / f"{video_id}-{name}.jpg"
        if not path.exists():
            try:
                r = requests.get(f"https://i.ytimg.com/vi/{video_id}/{name}.jpg", timeout=20)
                if r.status_code != 200 or len(r.content) < 1500:  # missing or placeholder image
                    continue
                path.write_bytes(r.content)
            except requests.RequestException:
                continue
        paths.append(path)
    return paths


def describe(s):
    """Text for the CLIP text encoder, strongest visual words first (it reads about 60 words)."""
    tags = [s["period"], s["time_of_day"].replace("_", " "), *s["atmosphere"], *s["environment"][:2], *s["mood"][:2]]
    return f"{s['what_happens']} {', '.join(t.replace('_', ' ') for t in tags)}."


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clips", type=Path, default=ROOT / "clips")
    args = ap.parse_args()
    from fastembed import ImageEmbedding, TextEmbedding

    scenes = load_scenes()
    CACHE.mkdir(parents=True, exist_ok=True)

    def images_for(s):
        frames = sorted((args.clips / s["scene_type"] / f"{s['id']}.frames").glob("*.jpg"))
        return (frames, "frames") if frames else (thumbnails(s["clip"]["youtube_id"]), "thumbnails")

    with ThreadPoolExecutor(8) as pool:
        sources = list(pool.map(images_for, scenes))
    print(f"{sum(src == 'frames' for _, src in sources)} scenes from clip frames, "
          f"{sum(src == 'thumbnails' for _, src in sources)} from YouTube thumbnails", flush=True)

    image_model, text_model = ImageEmbedding(IMAGE_MODEL), TextEmbedding(TEXT_MODEL)
    flat = [str(p) for paths, _ in sources for p in paths]
    vectors = np.array(list(image_model.embed(flat, batch_size=32)), dtype=np.float32)
    image = np.zeros((len(scenes), vectors.shape[1]), dtype=np.float32)
    i = 0
    for n, (paths, _) in enumerate(sources):
        if paths:
            image[n] = vectors[i:i + len(paths)].mean(0)
            i += len(paths)
    text = np.array(list(text_model.embed([describe(s) for s in scenes], batch_size=64)), dtype=np.float32)
    normalise = lambda m: m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)

    np.savez_compressed(
        OUT, ids=np.array([s["id"] for s in scenes]), image=normalise(image).astype(np.float16),
        text=normalise(text).astype(np.float16), source=np.array([src for _, src in sources]),
        model=np.array([IMAGE_MODEL, TEXT_MODEL]))
    missing = sum(1 for paths, _ in sources if not paths)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(scenes)} scenes"
          + (f" ({missing} without any image: text only)" if missing else ""))


if __name__ == "__main__":
    main()
