"""Tiny config. Single data dir, env-overridable."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    p = Path(os.environ.get("VIDEOMEMORY_DATA_DIR", str(Path.home() / ".videomemory")))
    p.mkdir(parents=True, exist_ok=True)
    (p / "videos").mkdir(parents=True, exist_ok=True)
    (p / "frames").mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / "library.sqlite"


def video_dir(video_id: str) -> Path:
    p = data_dir() / "videos" / video_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def frame_dir(video_id: str) -> Path:
    p = data_dir() / "frames" / video_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def max_video_seconds() -> int:
    return int(os.environ.get("VIDEOMEMORY_MAX_VIDEO_SECONDS", "3600"))  # 1h default


def whisper_model() -> str:
    return os.environ.get("VIDEOMEMORY_WHISPER_MODEL", "small")


def embed_model() -> str:
    return os.environ.get("VIDEOMEMORY_EMBED_MODEL", "BAAI/bge-small-en-v1.5")


def window_seconds() -> int:
    return int(os.environ.get("VIDEOMEMORY_WINDOW_SECONDS", "30"))


# ---- Visual funnel knobs (generic video understanding) ----

def visual_candidate_fps() -> float:
    """Frames-per-second sampled as candidates before dedup (1 fps is the standard)."""
    return float(os.environ.get("VIDEOMEMORY_VISUAL_FPS", "1.0"))


def visual_candidate_px() -> int:
    """Long-edge px for candidate frames used only for embedding/dedup (kept tiny)."""
    return int(os.environ.get("VIDEOMEMORY_VISUAL_CAND_PX", "336"))


def visual_dhash_threshold() -> int:
    """Hamming distance below which two frames are pixel-near-duplicates."""
    return int(os.environ.get("VIDEOMEMORY_VISUAL_DHASH", "6"))


def visual_semantic_dedup() -> float:
    """CLIP cosine above which two frames are semantic near-duplicates."""
    return float(os.environ.get("VIDEOMEMORY_VISUAL_SEMDEDUP", "0.92"))
