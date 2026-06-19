"""Screen capture — macOS `screencapture` first, Linux `import` fallback.

Tiny adapter so the daemon can request "capture to <path>" without caring about
the platform. Returns the captured file path on success, None on failure.
"""

from __future__ import annotations

import asyncio
import platform
import shutil
from pathlib import Path


async def capture_screen(out_path: Path) -> Path | None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    system = platform.system()
    if system == "Darwin":
        return await _macos_screencapture(out_path)
    if system == "Linux":
        return await _linux_capture(out_path)
    # Windows path is a v1.1 feature.
    return None


async def _macos_screencapture(out_path: Path) -> Path | None:
    """`screencapture -x -t jpg -o -r <path>` — no shutter sound, jpg, no cursor."""
    if not shutil.which("screencapture"):
        return None
    proc = await asyncio.create_subprocess_exec(
        "screencapture", "-x", "-t", "jpg", "-o", "-r", str(out_path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    return out_path if out_path.exists() and out_path.stat().st_size > 0 else None


async def _linux_capture(out_path: Path) -> Path | None:
    """Try ffmpeg x11grab first, fall back to ImageMagick `import`."""
    if shutil.which("ffmpeg"):
        display = ":0.0"
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "x11grab", "-i", display, "-frames:v", "1",
            str(out_path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if out_path.exists() and out_path.stat().st_size > 0:
            return out_path
    if shutil.which("import"):  # ImageMagick
        proc = await asyncio.create_subprocess_exec(
            "import", "-window", "root", str(out_path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return out_path if out_path.exists() else None
    return None
