"""Google Takeout watch-history → batch ingest into the library.

Accepts either:
 - the JSON export: `YouTube and YouTube Music/history/watch-history.json`
 - the HTML export at the same path (older Takeouts)

Strategy: extract YouTube URLs, dedupe, ingest each via `ingest_many()` with
bounded concurrency. Resumable: already-cached videos are skipped trivially.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

_URL_RE = re.compile(r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})")


def parse_history_file(path: Path) -> list[str]:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(p)
    text = p.read_text(errors="replace")
    if p.suffix.lower() == ".json":
        try:
            data = json.loads(text)
            return _from_json(data)
        except json.JSONDecodeError:
            pass  # fall through to URL regex
    return _dedupe(_URL_RE.findall(text))


def _from_json(items: Iterable[dict]) -> list[str]:
    ids: list[str] = []
    for entry in items:
        title_url = entry.get("titleUrl") or entry.get("title_url") or ""
        m = _URL_RE.search(title_url)
        if m:
            ids.append(m.group(1))
            continue
        # subtitles can carry the URL too
        for sub in entry.get("subtitles", []) or []:
            url = sub.get("url") or ""
            m = _URL_RE.search(url)
            if m:
                ids.append(m.group(1))
                break
    return _dedupe(ids)


def _dedupe(ids: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i in seen:
            continue
        seen.add(i)
        out.append(i)
    return out


async def import_history(
    path: Path,
    *,
    limit: int | None = None,
    concurrency: int = 2,
    progress=None,
) -> list:
    """Returns the list of ingest results (Video or Exception per URL)."""
    from videomemory.ingest import ingest_many

    ids = parse_history_file(path)
    if limit is not None:
        ids = ids[:limit]
    urls = [f"https://youtu.be/{vid}" for vid in ids]

    if progress:
        progress(f"found {len(urls)} unique YouTube URLs in history")
    return await ingest_many(urls, concurrency=concurrency)


__all__ = ["parse_history_file", "import_history"]
