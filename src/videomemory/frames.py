"""On-demand single-frame extraction via ffmpeg. Cached on disk under data_dir/frames/."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from videomemory.config import frame_dir, video_dir
from videomemory.ingest import _is_url  # type: ignore


def _frame_path(video_id: str, t: float) -> Path:
    return frame_dir(video_id) / f"{int(t * 1000):010d}.jpg"


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
    """Stream the video via yt-dlp piped into ffmpeg without writing the full file.

    Used when we don't have the local video — only the audio wav cached.
    """
    if not (shutil.which("yt-dlp") and shutil.which("ffmpeg")):
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    # Pipe yt-dlp video to ffmpeg via stdin
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


async def extract_frame_at(video_id: str, source: str, t_seconds: float) -> Path | None:
    """Get a single keyframe for (video_id, t). Cache-aware."""
    out = _frame_path(video_id, t_seconds)
    if out.exists():
        return out

    vdir = video_dir(video_id)

    # 1. Local original (saved alongside source.wav for local-file ingests)
    candidates = [p for p in vdir.glob("source.*") if p.suffix.lower() not in (".wav", ".json", ".txt")]
    for c in candidates:
        if await _ffmpeg_extract(c, t_seconds, out):
            return out

    # 1b. For local-file ingests we stored the original path in original_path.txt
    op = vdir / "original_path.txt"
    if op.exists():
        orig = Path(op.read_text().strip())
        if orig.exists() and await _ffmpeg_extract(orig, t_seconds, out):
            return out

    # 2. For URLs, stream-extract via yt-dlp piped into ffmpeg
    if _is_url(source):
        if await _ytdlp_image_dump(source, t_seconds, out):
            return out

    return None


__all__ = ["extract_frame_at"]
