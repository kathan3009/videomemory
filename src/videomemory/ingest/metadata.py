"""Extract video metadata via ffprobe."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path


class FFprobeError(RuntimeError):
    pass


async def ffprobe(path: Path) -> dict:
    """Run ffprobe -show_format -show_streams on a file."""
    if shutil.which("ffprobe") is None:
        raise FFprobeError("ffprobe not installed (install ffmpeg)")
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise FFprobeError(stderr.decode(errors="replace").strip() or "ffprobe failed")
    return json.loads(stdout.decode())


def _to_float(s: str | int | float | None) -> float:
    if s is None or s == "":
        return 0.0
    try:
        # ffprobe sometimes returns rational like "30000/1001"
        if isinstance(s, str) and "/" in s:
            a, b = s.split("/", 1)
            return float(a) / float(b) if float(b) else 0.0
        return float(s)
    except (ValueError, ZeroDivisionError):
        return 0.0


def parse_metadata(probe: dict) -> dict:
    fmt = probe.get("format", {})
    streams = probe.get("streams", []) or []
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    duration = _to_float(fmt.get("duration")) or _to_float(v.get("duration"))
    fps = _to_float(v.get("avg_frame_rate") or v.get("r_frame_rate"))
    return {
        "duration": duration,
        "fps": fps,
        "width": int(v.get("width") or 0),
        "height": int(v.get("height") or 0),
        "codec": v.get("codec_name"),
        "audio_codec": a.get("codec_name"),
        "file_size": int(fmt.get("size") or 0),
    }
