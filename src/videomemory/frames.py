"""Frame extraction.

Single-frame: `extract_frame_at(video_id, source, t)` — used by `skip()` to
deliver the visual moment of a transcript hit.

Multi-frame: `get_frames(url, count|every|at)` — the agent's tool for **purely
visual videos** (comedy shorts, sports highlights, silent demos). Returns N
frame URIs the agent fetches and reads with its own native vision.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from videomemory.config import frame_dir, video_dir
from videomemory.ingest import _is_url, deep_link, fmt_time, ingest  # type: ignore
from videomemory.types import Frame

MAX_FRAMES = 16


def _frame_path(video_id: str, t: float) -> Path:
    return frame_dir(video_id) / f"{int(t * 1000):010d}.jpg"


def _frame_uri(video_id: str, t: float) -> str:
    return f"videomemory://frames/{video_id}/{int(t * 1000):010d}.jpg"


async def _ffmpeg_extract(input_path: Path, t: float, out: Path) -> bool:
    if not shutil.which("ffmpeg"):
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(max(t, 0)),
        "-i", str(input_path),
        "-frames:v", "1",
        "-q:v", "3",
        str(out),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    return out.exists() and out.stat().st_size > 0


async def _ytdlp_image_dump(url: str, t: float, out: Path) -> bool:
    """Stream the video via yt-dlp into ffmpeg, extract one frame. Slow per-call."""
    if not (shutil.which("yt-dlp") and shutil.which("ffmpeg")):
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    ytdlp = await asyncio.create_subprocess_exec(
        "yt-dlp", "-f", "best[height<=720]/best", "-q",
        "--no-playlist", "-o", "-", url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    ff = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(max(t, 0)), "-i", "pipe:0",
        "-frames:v", "1", "-q:v", "3",
        str(out),
        stdin=ytdlp.stdout, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await ff.wait()
    try:
        ytdlp.terminate()
    except ProcessLookupError:
        pass
    await ytdlp.wait()
    return out.exists() and out.stat().st_size > 0


async def _download_video_once(url: str, dest_dir: Path) -> Path | None:
    """Download a small-ish video file so we can seek through it locally for N frames.

    Cached at <video_dir>/source.video.mp4 — reused across all get_frames() calls.
    """
    if not shutil.which("yt-dlp"):
        return None
    dest = dest_dir / "source.video.mp4"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    proc = await asyncio.create_subprocess_exec(
        "yt-dlp",
        "-f", "best[height<=480][ext=mp4]/best[height<=720][ext=mp4]/best[ext=mp4]/best",
        "--no-playlist", "--no-mtime",
        "-o", str(dest),
        url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        return None
    return dest if dest.exists() and dest.stat().st_size > 0 else None


async def _local_video_path(video_id: str, source: str) -> Path | None:
    """Find or fetch a local video file we can seek through."""
    vdir = video_dir(video_id)
    # 1. Already-downloaded source.video.mp4 (multi-frame cache)
    p = vdir / "source.video.mp4"
    if p.exists() and p.stat().st_size > 0:
        return p
    # 2. Local-file ingest stored the original path
    op = vdir / "original_path.txt"
    if op.exists():
        orig = Path(op.read_text().strip())
        if orig.exists():
            return orig
    # 3. Any non-audio source.* (image/video) sitting alongside the wav
    for cand in vdir.glob("source.*"):
        if cand.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov", ".avi"):
            return cand
    # 4. URL: download once
    if _is_url(source):
        return await _download_video_once(source, vdir)
    return None


async def extract_frame_at(video_id: str, source: str, t_seconds: float) -> Path | None:
    """Get a single keyframe for (video_id, t). Cache-aware."""
    out = _frame_path(video_id, t_seconds)
    if out.exists():
        return out

    local = await _local_video_path(video_id, source)
    if local and await _ffmpeg_extract(local, t_seconds, out):
        return out

    if _is_url(source) and await _ytdlp_image_dump(source, t_seconds, out):
        return out

    return None


async def extract_frames(video_id: str, source: str, times: list[float]) -> list[tuple[float, Path | None]]:
    """Batch: extract multiple frames using a single local video copy (download once, seek many)."""
    local = await _local_video_path(video_id, source)
    results: list[tuple[float, Path | None]] = []
    for t in times:
        out = _frame_path(video_id, t)
        if out.exists():
            results.append((t, out)); continue
        if local and await _ffmpeg_extract(local, t, out):
            results.append((t, out)); continue
        if _is_url(source) and await _ytdlp_image_dump(source, t, out):
            results.append((t, out)); continue
        results.append((t, None))
    return results


def _sample_times(duration: float, count: int) -> list[float]:
    """N evenly-spaced timestamps across the video, skipping the very edges."""
    if count <= 0 or duration <= 0:
        return []
    if count == 1:
        return [duration / 2]
    edge = max(0.5, duration * 0.02)
    span = max(duration - 2 * edge, 0.0)
    step = span / (count - 1) if count > 1 else 0
    return [round(edge + i * step, 2) for i in range(count)]


async def get_frames(
    url: str,
    *,
    count: int | None = None,
    every: float | None = None,
    at: list[float] | None = None,
    max_frames: int = MAX_FRAMES,
) -> list[Frame]:
    """Sample N keyframes from a video and return URIs the agent can fetch.

    Pick one:
        count   = N evenly-spaced frames across the whole video
        every   = a frame every X seconds
        at      = explicit list of timestamps (seconds)
        (none)  = defaults to count=8

    Cap is `max_frames` (16) to keep agent context tight.
    """
    v = await ingest(url)
    if v.duration <= 0:
        return []

    if at is not None:
        times = [t for t in at if 0 <= t <= v.duration]
    elif every is not None and every > 0:
        n = min(max_frames, max(1, int(v.duration / every) + 1))
        times = [i * every for i in range(n) if i * every < v.duration]
    elif count is not None and count > 0:
        times = _sample_times(v.duration, min(count, max_frames))
    else:
        times = _sample_times(v.duration, min(8, max_frames))

    times = times[:max_frames]
    extracted = await extract_frames(v.video_id, v.source, times)

    out: list[Frame] = []
    for t, path in extracted:
        if path is None:
            continue
        out.append(
            Frame(
                video_id=v.video_id,
                timestamp_seconds=t,
                timestamp_human=fmt_time(t),
                deep_link=deep_link(v.source, t),
                frame_uri=_frame_uri(v.video_id, t),
            )
        )
    return out


__all__ = ["extract_frame_at", "extract_frames", "get_frames", "_frame_uri"]
