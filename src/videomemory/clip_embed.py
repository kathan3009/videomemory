"""Joint image+text embedder for the visual-understanding funnel.

Prefers **MobileCLIP-S2** (via ``open_clip``): 512-d, ~2.3x faster than SigLIP-B
on Apple Silicon and +11pts ImageNet zero-shot over plain CLIP ViT-B/32, at the
same 512 dimensionality — so it's a drop-in for the vector store.

Falls back to sentence-transformers' ``clip-ViT-B-32`` (also 512-d) when
``open_clip`` isn't installed, so the rest of the system keeps working. The two
models are NOT interchangeable at query time — vectors are only comparable within
one model — so each stored frame records ``model_id()`` and retrieval filters to
matching vectors (see ``visual_index``).

Lazy: the model loads on first image-encode (index time) or text-encode (query
time), then stays warm via ``lru_cache``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

_MOBILECLIP_REF = "hf-hub:apple/MobileCLIP-S2-OpenCLIP"
_FALLBACK_NAME = "clip-ViT-B-32"
CLIP_DIM = 512


def _device() -> str:
    try:
        import torch

        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


@lru_cache(maxsize=1)
def _backend():
    """Return (kind, payload). kind ∈ {"open_clip", "st", None}."""
    dev = _device()
    # 1. Preferred: MobileCLIP-S2 via open_clip.
    try:
        import open_clip
        import torch

        model, preprocess = open_clip.create_model_from_pretrained(_MOBILECLIP_REF)
        tokenizer = open_clip.get_tokenizer(_MOBILECLIP_REF)
        model = model.to(dev).eval()
        return ("open_clip", {"model": model, "preprocess": preprocess, "tokenizer": tokenizer, "device": dev, "torch": torch})
    except Exception:
        pass
    # 2. Fallback: sentence-transformers CLIP ViT-B/32.
    try:
        from sentence_transformers import SentenceTransformer

        return ("st", {"model": SentenceTransformer(_FALLBACK_NAME, device=dev)})
    except Exception:
        return (None, {})


def model_id() -> str | None:
    kind, _ = _backend()
    if kind == "open_clip":
        return "mobileclip-s2"
    if kind == "st":
        return "clip-vit-b-32"
    return None


def available() -> bool:
    return model_id() is not None


def embed_images(paths: list[Path]) -> list[list[float] | None]:
    """CLIP-embed each image into the joint space. None for any path that fails."""
    kind, p = _backend()
    if kind is None or not paths:
        return [None] * len(paths)
    try:
        from PIL import Image
    except ImportError:
        return [None] * len(paths)

    imgs: list = []
    valid_idx: list[int] = []
    for i, path in enumerate(paths):
        try:
            imgs.append(Image.open(path).convert("RGB"))
            valid_idx.append(i)
        except Exception:
            continue
    if not imgs:
        return [None] * len(paths)

    out: list[list[float] | None] = [None] * len(paths)
    if kind == "open_clip":
        torch = p["torch"]
        batch = torch.stack([p["preprocess"](im) for im in imgs]).to(p["device"])
        with torch.no_grad():
            feats = p["model"].encode_image(batch)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        arr = feats.cpu().numpy().astype(np.float32)
    else:  # sentence-transformers
        arr = p["model"].encode(imgs, normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True).astype(np.float32)

    for j, i in enumerate(valid_idx):
        out[i] = arr[j].tolist()
    return out


def embed_query(text: str) -> list[float] | None:
    """Embed a free-text query in the same space as the image embeddings."""
    kind, p = _backend()
    if kind is None or not text:
        return None
    if kind == "open_clip":
        torch = p["torch"]
        toks = p["tokenizer"]([text]).to(p["device"])
        with torch.no_grad():
            feats = p["model"].encode_text(toks)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().numpy().astype(np.float32)[0].tolist()
    arr = p["model"].encode([text], normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True)
    return arr[0].astype(np.float32).tolist()


__all__ = ["available", "model_id", "embed_images", "embed_query", "CLIP_DIM"]
