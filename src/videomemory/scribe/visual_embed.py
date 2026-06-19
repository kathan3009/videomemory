"""CLIP image + text embedder for scribe visual search.

Uses sentence-transformers' ``clip-ViT-B-32`` which exposes a *single* model that
encodes both images and text into the same 512-d space, so we can search
"photo of a cat" against actual screenshots even when there's no OCR text.

Designed to be lazy: the model is only loaded the first time it's needed —
either at digest time (image encode) or at search time (text encode of the
query). When ``sentence-transformers`` / ``torch`` aren't installed, the
functions degrade to no-ops so the rest of scribe keeps working.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

CLIP_MODEL_NAME = "clip-ViT-B-32"
CLIP_DIM = 512


@lru_cache(maxsize=1)
def _model():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    device = "cpu"
    try:
        import torch

        if torch.backends.mps.is_available():
            device = "mps"
        elif torch.cuda.is_available():
            device = "cuda"
    except Exception:
        pass
    return SentenceTransformer(CLIP_MODEL_NAME, device=device)


def available() -> bool:
    return _model() is not None


def embed_images(paths: list[Path]) -> list[list[float] | None]:
    """CLIP-embed each image. Returns None for any path that fails."""
    m = _model()
    if m is None or not paths:
        return [None] * len(paths)
    try:
        from PIL import Image
    except ImportError:
        return [None] * len(paths)

    imgs: list = []
    valid_idx: list[int] = []
    for i, p in enumerate(paths):
        try:
            imgs.append(Image.open(p).convert("RGB"))
            valid_idx.append(i)
        except Exception:
            continue
    if not imgs:
        return [None] * len(paths)
    arr = m.encode(imgs, normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True)
    out: list[list[float] | None] = [None] * len(paths)
    for j, i in enumerate(valid_idx):
        out[i] = arr[j].astype(np.float32).tolist()
    return out


def embed_query(text: str) -> list[float] | None:
    """CLIP-embed a free-text query in the same space as image embeddings."""
    m = _model()
    if m is None or not text:
        return None
    arr = m.encode([text], normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True)
    return arr[0].astype(np.float32).tolist()


__all__ = ["available", "embed_images", "embed_query", "CLIP_DIM", "CLIP_MODEL_NAME"]
