"""Zero-shot scene tags via open-clip, plus image embeddings."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from videomemory.config import select_device

log = logging.getLogger(__name__)

DEFAULT_TAG_VOCAB: tuple[str, ...] = (
    "a person",
    "a group of people",
    "a speaker presenting",
    "a developer at a computer",
    "a whiteboard with writing",
    "a laptop screen",
    "a slide with text",
    "an architecture diagram",
    "an office room",
    "a meeting room",
    "outdoors",
    "a chart or graph",
    "code on a screen",
    "a dashboard UI",
    "a phone screen",
    "a city street",
    "a kitchen",
    "a vehicle",
    "an animal",
    "food",
)


@lru_cache(maxsize=1)
def _load_clip(model_name: str = "ViT-B-32", pretrained: str = "openai", device: str | None = None):
    import open_clip
    import torch

    dev = device or select_device("auto")
    model, _, preprocess = open_clip.create_model_and_transforms(model_name, pretrained=pretrained)
    tok = open_clip.get_tokenizer(model_name)
    model = model.to(dev).eval()
    log.info("loaded CLIP %s/%s on %s", model_name, pretrained, dev)
    return model, preprocess, tok, dev, torch


@lru_cache(maxsize=1)
def _text_features(vocab: tuple[str, ...], model_name: str, pretrained: str):
    model, _, tok, dev, torch = _load_clip(model_name, pretrained)
    with torch.no_grad():
        text = tok(list(vocab)).to(dev)
        feats = model.encode_text(text)
        feats /= feats.norm(dim=-1, keepdim=True)
    return feats


def score_tags(
    frame_paths: list[Path],
    vocab: tuple[str, ...] = DEFAULT_TAG_VOCAB,
    top_k: int = 5,
    model_name: str = "ViT-B-32",
    pretrained: str = "openai",
) -> list[list[tuple[str, float]]]:
    """For each frame, return top-K (tag, score) pairs."""
    if not frame_paths:
        return []
    model, preprocess, _, dev, torch = _load_clip(model_name, pretrained)
    text_feats = _text_features(vocab, model_name, pretrained)
    out: list[list[tuple[str, float]]] = []
    for fp in frame_paths:
        img = Image.open(fp).convert("RGB")
        x = preprocess(img).unsqueeze(0).to(dev)
        with torch.no_grad():
            feat = model.encode_image(x)
            feat /= feat.norm(dim=-1, keepdim=True)
            sims = (100.0 * feat @ text_feats.T).softmax(dim=-1)[0]
        scores = sims.detach().cpu().numpy()
        idx = np.argsort(-scores)[:top_k]
        out.append([(vocab[i], float(scores[i])) for i in idx])
    return out


def embed_images(
    frame_paths: list[Path],
    model_name: str = "ViT-B-32",
    pretrained: str = "openai",
) -> list[list[float]]:
    if not frame_paths:
        return []
    model, preprocess, _, dev, torch = _load_clip(model_name, pretrained)
    embs: list[list[float]] = []
    for fp in frame_paths:
        img = Image.open(fp).convert("RGB")
        x = preprocess(img).unsqueeze(0).to(dev)
        with torch.no_grad():
            feat = model.encode_image(x)
            feat = feat / feat.norm(dim=-1, keepdim=True)
        embs.append(feat[0].detach().cpu().numpy().tolist())
    return embs


def score_query_against_frames(
    query: str,
    frame_embeddings: list[list[float]],
    model_name: str = "ViT-B-32",
    pretrained: str = "openai",
) -> list[float]:
    """Score a text query against a precomputed list of frame embeddings."""
    if not frame_embeddings:
        return []
    model, _, tok, dev, torch = _load_clip(model_name, pretrained)
    with torch.no_grad():
        t = tok([query]).to(dev)
        tf = model.encode_text(t)
        tf = tf / tf.norm(dim=-1, keepdim=True)
        tf_np = tf[0].detach().cpu().numpy()
    fe = np.array(frame_embeddings, dtype=np.float32)
    fe /= np.linalg.norm(fe, axis=1, keepdims=True) + 1e-9
    return (fe @ tf_np).tolist()
