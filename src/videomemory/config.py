"""Runtime configuration for local and tenant-isolated hosted operation."""

from __future__ import annotations

import os
from pathlib import Path

from videomemory.tenant import current_tenant, tenant_data_dir


def hosted_mode() -> bool:
    return os.environ.get("VIDEOMEMORY_HOSTED", "0").lower() in {"1", "true", "yes"}


def data_root() -> Path:
    p = Path(os.environ.get("VIDEOMEMORY_DATA_ROOT", "/data/videomemory"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_dir() -> Path:
    tenant = current_tenant()
    if hosted_mode() or tenant is not None:
        p = tenant_data_dir(data_root(), tenant)
    else:
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


def max_download_bytes() -> int:
    return int(os.environ.get("VIDEOMEMORY_MAX_DOWNLOAD_BYTES", str(2 * 1024 * 1024 * 1024)))


def max_upload_bytes() -> int:
    """Maximum accepted browser upload size (100 MiB beta default)."""
    return int(os.environ.get("VIDEOMEMORY_MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))


def max_tenant_bytes() -> int:
    """Hard ceiling for one tenant's complete on-disk workspace."""
    return int(os.environ.get("VIDEOMEMORY_MAX_TENANT_BYTES", str(350 * 1024 * 1024)))


def max_global_bytes() -> int:
    """Emergency ceiling for all persistent tenant data on a single-node beta."""
    return int(os.environ.get("VIDEOMEMORY_MAX_GLOBAL_BYTES", str(450 * 1024 * 1024)))


def max_active_jobs() -> int:
    return int(os.environ.get("VIDEOMEMORY_MAX_ACTIVE_JOBS", "4"))


def media_process_timeout_seconds() -> int:
    return int(os.environ.get("VIDEOMEMORY_MEDIA_PROCESS_TIMEOUT_SECONDS", "300"))


def download_timeout_seconds() -> int:
    return int(os.environ.get("VIDEOMEMORY_DOWNLOAD_TIMEOUT_SECONDS", "900"))


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


# ---- Shot detection knobs ----

def scene_threshold() -> float:
    """ffmpeg `scene` score (0..1) above which a frame starts a new shot."""
    return float(os.environ.get("VIDEOMEMORY_SCENE_THRESHOLD", "0.4"))


def min_shot_seconds() -> float:
    """Shots shorter than this are merged into the neighbour (kills flicker cuts)."""
    return float(os.environ.get("VIDEOMEMORY_MIN_SHOT_SECONDS", "0.6"))


# ---- Cut-point knobs (montage assembly) ----

def cut_motion_fps() -> float:
    """Sampling rate of the per-frame motion curve (YDIF)."""
    return float(os.environ.get("VIDEOMEMORY_CUT_MOTION_FPS", "10.0"))
