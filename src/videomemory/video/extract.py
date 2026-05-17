"""Frame extraction via ffmpeg + OpenCV-based keyframe selection."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import cv2
import imagehash
import numpy as np
from PIL import Image


async def extract_audio_wav(video_path: Path, dest_wav: Path, sample_rate: int = 16000) -> Path:
    """Extract mono 16kHz wav (whisper-ready) via ffmpeg."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not installed")
    dest_wav.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "wav",
        str(dest_wav),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extract failed: {err.decode(errors='replace')[:300]}")
    return dest_wav


def _frame_entropy(gray: np.ndarray) -> float:
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).ravel()
    hist = hist / (hist.sum() + 1e-9)
    nz = hist[hist > 0]
    return float(-(nz * np.log2(nz)).sum())


def select_keyframes_for_scene(
    video_path: Path,
    start: float,
    end: float,
    out_dir: Path,
    max_keyframes: int = 3,
    dedup_hamming: int = 6,
) -> list[tuple[Path, float]]:
    """Sample candidates from [start, end], keep top-N by entropy, dedup by phash.

    Returns list of (frame_path, timestamp_sec).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    duration = max(end - start, 0.1)
    # Sample ~max(8, ceil(duration)*2) candidates evenly through the scene
    n_candidates = max(8, int(duration * 2))
    times = np.linspace(start + 0.05, end - 0.05, n_candidates).tolist()
    candidates: list[tuple[float, np.ndarray, float]] = []  # (ts, bgr, entropy)
    for ts in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ent = _frame_entropy(gray)
        candidates.append((ts, frame, ent))
    cap.release()

    if not candidates:
        return []

    # Sort by entropy desc, take top N*3 then dedup
    candidates.sort(key=lambda x: x[2], reverse=True)
    picked: list[tuple[float, np.ndarray]] = []
    hashes: list[imagehash.ImageHash] = []
    for ts, frame, _ in candidates[: max_keyframes * 4]:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        ph = imagehash.phash(Image.fromarray(rgb))
        if any((ph - existing) <= dedup_hamming for existing in hashes):
            continue
        hashes.append(ph)
        picked.append((ts, frame))
        if len(picked) >= max_keyframes:
            break

    # Re-sort chronologically for stable output
    picked.sort(key=lambda x: x[0])
    out: list[tuple[Path, float]] = []
    for i, (ts, frame) in enumerate(picked):
        fname = out_dir / f"{int(ts * 1000):08d}_{i}.jpg"
        cv2.imwrite(str(fname), frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
        out.append((fname, ts))
    _ = fps  # silence unused
    return out
