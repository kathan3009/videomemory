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
