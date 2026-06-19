"""Search across durable scribe day-lines and visual CLIP embeddings.

Two modalities are fused:
  - text: cosine over bge-small embeddings of "did" / "saw" lines
  - visual: cosine over CLIP-ViT-B-32 embeddings of representative keyframes,
            using the same CLIP text encoder for the query

Results are merged and ranked by score, with visual hits tagged ``kind="visual"``.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from videomemory.embed import embed_text
from videomemory.scribe import visual_embed
from videomemory.scribe.store import all_day_lines_with_vecs, all_day_visuals_with_vecs


def _within(date_iso: str, since: datetime | None, until: datetime | None) -> bool:
    if since and date_iso < since.date().isoformat():
        return False
    if until and date_iso > until.date().isoformat():
        return False
    return True


def _search_text(query: str, since: datetime | None, until: datetime | None) -> list[tuple[dict, float]]:
    rows = all_day_lines_with_vecs()
    if not rows:
        return []
    qv = np.asarray(embed_text(query), dtype=np.float32)
    out: list[tuple[dict, float]] = []
    for line, vec in rows:
        if not _within(line["date"], since, until):
            continue
        out.append((line, float(vec @ qv)))
    return out


def _search_visual(query: str, since: datetime | None, until: datetime | None) -> list[tuple[dict, float]]:
    rows = all_day_visuals_with_vecs()
    if not rows:
        return []
    qv = visual_embed.embed_query(query)
    if qv is None:
        return []
    qa = np.asarray(qv, dtype=np.float32)
    out: list[tuple[dict, float]] = []
    for v, vec in rows:
        if not _within(v["date"], since, until):
            continue
        out.append((v, float(vec @ qa)))
    return out


def _format_visual_text(v: dict) -> str:
    ts = v.get("timestamp_human", "")
    app = v.get("app") or ""
    title = v.get("title") or ""
    url = v.get("url")
    cap = v.get("caption") or ""
    parts = [f"[{ts}]" if ts else ""]
    if app and app != "unknown":
        parts.append(app)
    if title and title != app:
        parts.append(f"— {title}")
    if url:
        parts.append(f"· {url}")
    if cap:
        parts.append(f"· {cap}")
    return " ".join(p for p in parts if p).strip() or "(screenshot)"


def scribe_search(query: str, *, top_k: int = 8, since: datetime | None = None, until: datetime | None = None) -> list[dict]:
    """Hybrid text + visual search with reciprocal-rank fusion.

    Text uses bge-small cosine (~0.5–0.8 for relevant). Visual uses CLIP cosine
    (~0.2 for relevant). Raw scores aren't comparable so we fuse by rank position
    via RRF, which is the standard cross-modal merging technique.
    """
    text_hits = sorted(_search_text(query, since, until), key=lambda kv: -kv[1])
    visual_hits = sorted(_search_visual(query, since, until), key=lambda kv: -kv[1])

    K = 60  # RRF damping constant; 60 is the canonical value
    by_key: dict[str, dict] = {}
    for rank, (line, raw) in enumerate(text_hits):
        key = f"t:{line['line_id']}"
        by_key[key] = {
            "date": line["date"],
            "kind": line["kind"],
            "text": line["text"],
            "score": raw,                   # keep raw cosine for display
            "_rrf": 1.0 / (K + rank + 1),
        }
    for rank, (v, raw) in enumerate(visual_hits):
        key = f"v:{v['visual_id']}"
        by_key[key] = {
            "date": v["date"],
            "kind": "visual",
            "text": _format_visual_text(v),
            "score": raw,
            "_rrf": 1.0 / (K + rank + 1),
        }
    merged = list(by_key.values())
    merged.sort(key=lambda r: -r["_rrf"])
    for r in merged:
        r.pop("_rrf", None)
    return merged[:top_k]


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
