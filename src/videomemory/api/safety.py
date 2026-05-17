"""Minimal safety guards for the public HTTP API.

Currently a single max-duration cap to prevent abuse (random visitors ingesting
multi-hour livestreams). Configurable via VIDEOMEMORY_MAX_VIDEO_SECONDS.

If you also want auth, set VIDEOMEMORY_INGEST_TOKEN and `ingest_url`/`upload`
endpoints will require `Authorization: Bearer <token>`.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from fastapi import Header, HTTPException


def max_duration_seconds() -> int:
    return int(os.environ.get("VIDEOMEMORY_MAX_VIDEO_SECONDS", "1800"))  # default 30 min


def required_ingest_token() -> str | None:
    val = os.environ.get("VIDEOMEMORY_INGEST_TOKEN")
    return val.strip() if val else None


async def require_ingest_token(authorization: str | None = Header(default=None)) -> None:
    token = required_ingest_token()
    if not token:
        return  # auth disabled
    expected = f"Bearer {token}"
    if not authorization or authorization.strip() != expected:
        raise HTTPException(status_code=401, detail="invalid or missing ingest token")


async def assert_local_duration_ok(path: Path) -> None:
    cap = max_duration_seconds()
    if cap <= 0:
        return
    if shutil.which("ffprobe") is None:
        return
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    try:
        secs = float(out.decode().strip() or "0")
    except ValueError:
        return
    if secs > cap:
        raise HTTPException(
            status_code=413,
            detail=f"video too long: {secs:.0f}s > limit {cap}s "
                   f"(set VIDEOMEMORY_MAX_VIDEO_SECONDS to change)",
        )


async def assert_url_duration_ok(url: str) -> None:
    """Probe a URL with yt-dlp to fetch declared duration before we download."""
    cap = max_duration_seconds()
    if cap <= 0:
        return
    if shutil.which("yt-dlp") is None:
        return
    proc = await asyncio.create_subprocess_exec(
        "yt-dlp", "--no-warnings", "--print", "%(duration)s",
        "--skip-download", "--no-playlist", url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    try:
        secs = float(out.decode().strip().splitlines()[0] or "0")
    except (ValueError, IndexError):
        return
    if secs > cap:
        raise HTTPException(
            status_code=413,
            detail=f"video too long: {secs:.0f}s > limit {cap}s",
        )
