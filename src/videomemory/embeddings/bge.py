"""Text embeddings via sentence-transformers (bge-small by default)."""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

from videomemory.config import select_device

log = logging.getLogger(__name__)

EMBED_DIM_BY_MODEL: dict[str, int] = {
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "BAAI/bge-large-en-v1.5": 1024,
}


@lru_cache(maxsize=2)
def _load(model_name: str = "BAAI/bge-small-en-v1.5", device: str | None = None):
    from sentence_transformers import SentenceTransformer

    dev = device or select_device("auto")
    model = SentenceTransformer(model_name, device=dev)
    log.info("loaded embedding model %s on %s", model_name, dev)
    return model


def embed_texts(texts: list[str], model_name: str = "BAAI/bge-small-en-v1.5") -> list[list[float]]:
    if not texts:
        return []
    model = _load(model_name)
    arr = model.encode(texts, normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True)
    return [v.tolist() for v in arr]


def embed_text(text: str, model_name: str = "BAAI/bge-small-en-v1.5") -> list[float]:
    return embed_texts([text], model_name=model_name)[0]


def cosine(a: list[float] | np.ndarray, b: list[float] | np.ndarray) -> float:
    av = np.asarray(a, dtype=np.float32)
    bv = np.asarray(b, dtype=np.float32)
    na = np.linalg.norm(av) + 1e-9
    nb = np.linalg.norm(bv) + 1e-9
    return float((av @ bv) / (na * nb))


def dim_for(model_name: str) -> int:
    if model_name in EMBED_DIM_BY_MODEL:
        return EMBED_DIM_BY_MODEL[model_name]
    # Best-effort: trigger a dummy encoding
    return len(embed_text("probe", model_name=model_name))
