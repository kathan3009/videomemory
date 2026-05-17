"""Ingest pipeline: URL/path → audio → faster-whisper → 30s windows → bge embeddings → SQLite.

Idempotent: same source = same video_id = no re-work.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from videomemory.config import (
    max_video_seconds,
    video_dir,
    whisper_model,
    window_seconds,
)
from videomemory.embed import embed_texts
from videomemory.library import (
    get_video,
    has_windows,
    insert_windows,
    upsert_video,
)
from videomemory.types import Video, Window

log = logging.getLogger(__name__)


# ---------- video ID resolution ----------

_YT_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _youtube_id(url: str) -> str | None:
    try:
        u = urlparse(url)
    except Exception:
        return None
    host = (u.hostname or "").lower()
    if host == "youtu.be":
        cand = u.path.lstrip("/")
        return cand if _YT_RE.match(cand) else None
    if "youtube.com" in host:
        q = parse_qs(u.query)
        if "v" in q and _YT_RE.match(q["v"][0]):
            return q["v"][0]
        for pre in ("/embed/", "/shorts/", "/v/"):
            if u.path.startswith(pre):
                c = u.path[len(pre):].split("/")[0]
                if _YT_RE.match(c):
                    return c
    return None


def _is_url(s: str) -> bool:
    try:
        return urlparse(s).scheme in ("http", "https", "rtsp", "rtmp")
    except Exception:
        return False


def video_id_for(source: str, file_path: Path | None = None) -> str:
    yt = _youtube_id(source)
    if yt:
        return f"yt_{yt}"
    if file_path and file_path.exists():
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return f"f_{h.hexdigest()[:16]}"
    return f"u_{hashlib.sha256(source.encode()).hexdigest()[:16]}"


def deep_link(source: str, t_seconds: float) -> str:
    yt = _youtube_id(source)
    if yt:
        return f"https://youtu.be/{yt}?t={int(t_seconds)}"
    return f"{source}#t={int(t_seconds)}"


def fmt_time(t: float) -> str:
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ---------- download / probe ----------


@dataclass
class Source:
    video_id: str
    source: str
    local_audio: Path
    title: str | None
    duration: float


async def _ffprobe_duration(path: Path) -> float:
    if not shutil.which("ffprobe"):
        return 0.0
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    try:
        return float(out.decode().strip() or 0)
    except ValueError:
        return 0.0


async def _download_audio(url: str, dest_dir: Path) -> tuple[Path, str | None, float]:
    """Download audio-only with yt-dlp + report duration + title.

    For non-YouTube URLs we fall back to downloading the full video.
    """
    if not shutil.which("yt-dlp"):
        raise RuntimeError("yt-dlp not installed (run: videomemory setup)")
    dest_dir.mkdir(parents=True, exist_ok=True)
    info_path = dest_dir / "info.json"
    args = [
        "yt-dlp",
        "-f", "bestaudio/best",
        "-x", "--audio-format", "wav",
        "--no-playlist", "--no-mtime",
        "--write-info-json",
        "--restrict-filenames",
        "-o", str(dest_dir / "source.%(ext)s"),
        url,
    ]
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {err.decode(errors='replace')[:500]}")
    wav = next(iter(dest_dir.glob("source.wav")), None)
    if wav is None:
        # yt-dlp might leave a non-wav file; convert with ffmpeg
        cand = next(iter(dest_dir.glob("source.*")), None)
        if cand is None:
            raise RuntimeError("yt-dlp downloaded nothing")
        wav = dest_dir / "source.wav"
        await _ffmpeg_to_wav(cand, wav)
    title = None
    duration = 0.0
    for j in dest_dir.glob("source.info.json"):
        try:
            data = json.loads(j.read_text())
            title = data.get("title")
            duration = float(data.get("duration") or 0)
        except Exception:
            pass
    if duration <= 0:
        duration = await _ffprobe_duration(wav)
    return wav, title, duration


async def _ffmpeg_to_wav(src: Path, dst: Path, sample_rate: int = 16000) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not installed")
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src), "-vn", "-ac", "1", "-ar", str(sample_rate),
        "-f", "wav", str(dst),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {err.decode(errors='replace')[:500]}")


async def resolve_source(source: str) -> Source:
    """Return everything we need to transcribe `source`."""
    if _is_url(source):
        vid = video_id_for(source)
        vdir = video_dir(vid)
        wav = vdir / "source.wav"
        if wav.exists():
            duration = await _ffprobe_duration(wav)
            return Source(vid, source, wav, _read_title(vdir), duration)
        wav, title, duration = await _download_audio(source, vdir)
        if title:
            (vdir / "title.txt").write_text(title)
        return Source(vid, source, wav, title, duration)
    # local file
    p = Path(source).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(source)
    vid = video_id_for(source, file_path=p)
    vdir = video_dir(vid)
    wav = vdir / "source.wav"
    if not wav.exists():
        await _ffmpeg_to_wav(p, wav)
    duration = await _ffprobe_duration(wav)
    title = p.stem
    (vdir / "title.txt").write_text(title)
    (vdir / "original_path.txt").write_text(str(p))
    return Source(vid, source, wav, title, duration)


def _read_title(vdir: Path) -> str | None:
    t = vdir / "title.txt"
    return t.read_text().strip() if t.exists() else None


# ---------- transcribe ----------


@lru_cache(maxsize=2)
def _whisper(model_size: str):
    from faster_whisper import WhisperModel

    return WhisperModel(model_size, device="cpu", compute_type="int8")


def _transcribe_to_segments(wav: Path, model_size: str) -> list[tuple[float, float, str]]:
    model = _whisper(model_size)
    segments, _ = model.transcribe(
        str(wav),
        vad_filter=True,
        beam_size=1,
        condition_on_previous_text=False,
    )
    return [(float(s.start or 0), float(s.end or 0), (s.text or "").strip()) for s in segments if (s.text or "").strip()]


def _bucket_into_windows(
    segments: list[tuple[float, float, str]],
    video_id: str,
    window_size: float,
) -> list[Window]:
    if not segments:
        return []
    end_total = segments[-1][1]
    n = max(1, int(end_total // window_size) + 1)
    buckets: list[list[str]] = [[] for _ in range(n)]
    bounds: list[tuple[float, float]] = [
        (i * window_size, min((i + 1) * window_size, end_total)) for i in range(n)
    ]
    for s, e, text in segments:
        mid = (s + e) / 2
        idx = min(int(mid // window_size), n - 1)
        buckets[idx].append(text)
    windows: list[Window] = []
    for i, parts in enumerate(buckets):
        if not parts:
            continue
        joined = " ".join(parts).strip()
        if not joined:
            continue
        windows.append(
            Window(
                window_id=f"{video_id}__{i:05d}",
                video_id=video_id,
                idx=i,
                start=bounds[i][0],
                end=bounds[i][1],
                text=joined,
            )
        )
    return windows


# ---------- top-level ----------


async def ingest(source: str, *, force: bool = False) -> Video:
    """Idempotent: returns the existing Video if already cached, else runs the pipeline."""
    cap = max_video_seconds()

    if not force:
        # If we already know about this source, short-circuit
        pre_id = video_id_for(source) if _is_url(source) else None
        if pre_id:
            existing = get_video(pre_id)
            if existing and has_windows(pre_id):
                return existing

    src = await resolve_source(source)
    if cap > 0 and src.duration > cap:
        raise ValueError(
            f"video too long: {src.duration:.0f}s > limit {cap}s "
            "(set VIDEOMEMORY_MAX_VIDEO_SECONDS to change)"
        )

    v = Video(
        video_id=src.video_id,
        source=src.source,
        title=src.title,
        duration=src.duration,
        added_at=datetime.utcnow(),
        file_path=str(src.local_audio),
    )
    upsert_video(v)
    if not force and has_windows(src.video_id):
        return v

    # Transcribe + bucket + embed
    log.info("transcribing %s (%.1fs)", src.video_id, src.duration)
    segments = await asyncio.to_thread(_transcribe_to_segments, src.local_audio, whisper_model())
    windows = _bucket_into_windows(segments, src.video_id, window_seconds())
    if windows:
        vecs = await asyncio.to_thread(embed_texts, [w.text for w in windows])
        insert_windows(windows, vecs)
    log.info("ingested %s windows=%d", src.video_id, len(windows))
    return v


async def ingest_many(sources: list[str], *, concurrency: int = 2) -> list[Video | Exception]:
    """Ingest many URLs concurrently with a bounded semaphore."""
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(s: str):
        async with sem:
            try:
                return await ingest(s)
            except Exception as exc:
                log.warning("ingest failed for %s: %s", s, exc)
                return exc

    return await asyncio.gather(*(one(s) for s in sources))


def transcribe_full(video_id: str) -> str:
    """Concatenated transcript for a cached video. Cheap — just walks SQLite."""
    from videomemory.library import get_windows

    return "\n".join(f"[{fmt_time(w.start)}] {w.text}" for w in get_windows(video_id))


__all__ = [
    "ingest",
    "ingest_many",
    "resolve_source",
    "video_id_for",
    "deep_link",
    "fmt_time",
    "transcribe_full",
]
