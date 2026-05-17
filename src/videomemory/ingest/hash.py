"""Stable video IDs and content hashes used as cache keys."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def short_hash(text: str, length: int = 12) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:length]


_YT_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def youtube_id(url: str) -> str | None:
    """Extract the 11-char YouTube video ID from any known URL form."""
    try:
        u = urlparse(url)
    except Exception:
        return None
    host = (u.hostname or "").lower()
    if host in ("youtu.be",):
        candidate = u.path.lstrip("/")
        return candidate if _YT_RE.match(candidate) else None
    if "youtube.com" in host:
        q = parse_qs(u.query)
        if "v" in q and _YT_RE.match(q["v"][0]):
            return q["v"][0]
        # /embed/<id> /shorts/<id>
        for prefix in ("/embed/", "/shorts/", "/v/"):
            if u.path.startswith(prefix):
                cand = u.path[len(prefix) :].split("/")[0]
                if _YT_RE.match(cand):
                    return cand
    return None


def video_id_for_source(source: str, file_path: Path | None = None) -> str:
    """Deterministic ID for a video.

    - YouTube URL → `yt_<11charid>`
    - Local file → `f_<short_sha256>`  (computed from content if file_path provided)
    - Other URL → `u_<short_sha256(url)>`
    """
    yt = youtube_id(source)
    if yt:
        return f"yt_{yt}"
    if source.startswith(("http://", "https://", "rtsp://", "rtmp://")):
        return f"u_{short_hash(source)}"
    if file_path is not None and file_path.exists():
        return f"f_{sha256_file(file_path)[:16]}"
    return f"f_{short_hash(source)}"
