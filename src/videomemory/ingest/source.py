"""Resolve a video source (local path or URL) into a local file."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from urllib.parse import urlparse

from videomemory.ingest.hash import video_id_for_source
from videomemory.ingest.metadata import ffprobe, parse_metadata
from videomemory.storage.artifacts import ArtifactPaths
from videomemory.types import VideoMetadata


class IngestError(RuntimeError):
    pass


def _is_url(src: str) -> bool:
    try:
        u = urlparse(src)
        return u.scheme in ("http", "https", "rtsp", "rtmp")
    except Exception:
        return False


async def _download_with_ytdlp(url: str, dest_template: Path) -> tuple[Path, str | None]:
    """Download a URL via yt-dlp. Returns (local_path, title)."""
    if shutil.which("yt-dlp") is None:
        # Fallback: try the python module via uv-installed `yt_dlp` binary
        raise IngestError("yt-dlp not installed")
    args = [
        "yt-dlp",
        "-f",
        "mp4/best[ext=mp4]/best",
        "--no-playlist",
        "--no-mtime",
        "--restrict-filenames",
        "-o",
        str(dest_template),
        "--print",
        "after_move:%(title)s|%(filepath)s",
        url,
    ]
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise IngestError(f"yt-dlp failed: {stderr.decode(errors='replace')[:400]}")
    out = stdout.decode().strip().splitlines()
    title: str | None = None
    filepath: Path | None = None
    for line in out:
        if "|" in line:
            title, filepath_str = line.split("|", 1)
            filepath = Path(filepath_str)
    if filepath is None or not filepath.exists():
        # Fallback to glob (yt-dlp print may not have fired in older versions)
        parent = dest_template.parent
        candidates = sorted(parent.glob("source.*"))
        if not candidates:
            raise IngestError("yt-dlp completed but no file found")
        filepath = candidates[0]
    return filepath, title


async def resolve_source(
    source: str, data_dir: Path
) -> tuple[VideoMetadata, ArtifactPaths]:
    """Return (metadata, artifact_paths) after ensuring the source is local."""

    if _is_url(source):
        # URL: use url-derived ID so the download can be placed deterministically.
        pre_video_id = video_id_for_source(source)
        paths = ArtifactPaths(data_dir=data_dir, video_id=pre_video_id)
        paths.ensure()
        existing = paths.find_source()
        if existing is None:
            dest_template = paths.root / "source.%(ext)s"
            local_path, title = await _download_with_ytdlp(source, dest_template)
        else:
            local_path = existing
            title = None
    else:
        # Local file: compute content-derived ID up front (no pre-id dir).
        local_path = Path(source).expanduser().resolve()
        if not local_path.exists():
            raise IngestError(f"file not found: {local_path}")
        title = local_path.stem
        video_id = video_id_for_source(source, file_path=local_path)
        paths = ArtifactPaths(data_dir=data_dir, video_id=video_id)
        paths.ensure()
        dest = paths.source_path(local_path.suffix.lstrip(".") or "mp4")
        if not dest.exists() and dest.resolve() != local_path.resolve():
            try:
                dest.symlink_to(local_path)
            except OSError:
                shutil.copy2(local_path, dest)
        # Use the resolved local file path so downstream stages read the original
        # (symlink works for everything we do; avoid copying large videos).

    # Probe
    probe = await ffprobe(local_path)
    md = parse_metadata(probe)

    meta = VideoMetadata(
        video_id=paths.video_id,
        source=source,
        title=title,
        file_path=str(local_path),
        **md,
    )
    paths.metadata_json.write_text(meta.model_dump_json(indent=2))
    return meta, paths
