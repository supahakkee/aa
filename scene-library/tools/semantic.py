"""Semantic search over scenes using CLIP embeddings made by tools/embed.py.

Each scene has an image vector (the mean of its frames, or its YouTube thumbnail) and a text vector
(its description and tags), both in CLIP's shared space, so a plain-language query can match what a
scene looks like as well as how it is described. Scores from the two are standardised before
being mixed, because image-text and text-text similarities live on different scales.
"""
from pathlib import Path

TEXT_MODEL = "Qdrant/clip-ViT-B-32-text"
IMAGE_MODEL = "Qdrant/clip-ViT-B-32-vision"


def _z(x):
    return (x - x.mean()) / (x.std() + 1e-9)


class Semantic:
    _cache = {}

    def __init__(self, path):
        import numpy as np
        data = np.load(path, allow_pickle=False)
        self.np = np
        self.ids = [str(i) for i in data["ids"]]
        self.index = {sid: n for n, sid in enumerate(self.ids)}
        self.image = data["image"].astype("float32")
        self.text = data["text"].astype("float32")
        self._encoder = None

    @classmethod
    def load(cls, root):
        """The index for this library, or None when embeddings or numpy are missing."""
        path = Path(root) / "data" / "embeddings.npz"
        if not path.exists():
            return None
        try:
            key = (str(path), path.stat().st_mtime)
            if key not in cls._cache:
                cls._cache = {key: cls(path)}
            return cls._cache[key]
        except ImportError:
            return None

    def _encode(self, query):
        if self._encoder is None:
            from fastembed import TextEmbedding
            self._encoder = TextEmbedding(TEXT_MODEL)
        v = self.np.array(list(self._encoder.embed([query]))[0], dtype="float32")
        return v / (self.np.linalg.norm(v) + 1e-9)

    def _rank(self, scores, limit, exclude=None):
        order = self.np.argsort(-scores)
        out = []
        for n in order:
            if self.ids[n] != exclude:
                out.append((self.ids[n], float(scores[n])))
            if len(out) == limit:
                break
        return out

    def search_text(self, query, limit=10, image_weight=0.45):
        """Scenes matching a plain-language description of how they look or what happens."""
        q = self._encode(query)
        scores = image_weight * _z(self.image @ q) + (1 - image_weight) * _z(self.text @ q)
        return self._rank(scores, limit)

    def similar_to(self, scene_id, limit=10, image_weight=0.5):
        """Scenes that look and read most like the given one."""
        n = self.index[scene_id]
        scores = image_weight * _z(self.image @ self.image[n]) + (1 - image_weight) * _z(self.text @ self.text[n])
        return self._rank(scores, limit, exclude=scene_id)
