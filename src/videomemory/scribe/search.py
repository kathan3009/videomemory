"""Search across durable scribe day-lines (cosine over bge-small embeddings)."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from videomemory.embed import embed_text
from videomemory.scribe.store import all_day_lines_with_vecs


def scribe_search(query: str, *, top_k: int = 8, since: datetime | None = None, until: datetime | None = None) -> list[dict]:
    rows = all_day_lines_with_vecs()
    if not rows:
        return []
    qv = np.asarray(embed_text(query), dtype=np.float32)
    candidates: list[tuple[dict, float]] = []
    for line, vec in rows:
        if since and line["date"] < since.date().isoformat():
            continue
        if until and line["date"] > until.date().isoformat():
            continue
        candidates.append((line, float(vec @ qv)))
    candidates.sort(key=lambda kv: -kv[1])
    out = []
    for line, score in candidates[:top_k]:
        out.append({
            "date": line["date"],
            "kind": line["kind"],
            "text": line["text"],
            "score": score,
        })
    return out


def parse_relative(spec: str) -> datetime:
    """Parse `1d`, `2h`, `30m`, `7d`, or an ISO date / datetime."""
    spec = spec.strip()
    if spec.endswith("d") and spec[:-1].isdigit():
        return datetime.now() - timedelta(days=int(spec[:-1]))
    if spec.endswith("h") and spec[:-1].isdigit():
        return datetime.now() - timedelta(hours=int(spec[:-1]))
    if spec.endswith("m") and spec[:-1].isdigit():
        return datetime.now() - timedelta(minutes=int(spec[:-1]))
    try:
        return datetime.fromisoformat(spec)
    except ValueError as exc:
        raise ValueError(f"could not parse relative time: {spec}") from exc
