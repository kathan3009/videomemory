"""Text embedding wrapper — bge-small by default."""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from videomemory.config import embed_model


@lru_cache(maxsize=2)
def _model(name: str):
    from sentence_transformers import SentenceTransformer

    # Auto-pick device: MPS on Apple Silicon, CPU otherwise.
    device = "cpu"
    try:
        import torch

        if torch.backends.mps.is_available():
            device = "mps"
        elif torch.cuda.is_available():
            device = "cuda"
    except Exception:
        pass
    return SentenceTransformer(name, device=device)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    m = _model(embed_model())
    arr = m.encode(texts, normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True)
    return [v.astype(np.float32).tolist() for v in arr]


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]
