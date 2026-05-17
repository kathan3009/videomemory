"""Search: cosine over SQLite-stored bge-small vectors.

skip(url, question)   → top hit in one video
search(query)         → top hits across every video in the library
"""

from __future__ import annotations

import numpy as np

from videomemory.embed import embed_text
from videomemory.ingest import deep_link, fmt_time, ingest, video_id_for
from videomemory.library import (
    get_video,
    has_windows,
    iter_all_windows,
    iter_windows_for_video,
)
from videomemory.types import Hit


def _frame_uri(video_id: str, t: float) -> str:
    return f"videomemory://frames/{video_id}/{int(t * 1000):010d}.jpg"


def _topk_cosine(query_vec: np.ndarray, windows: list, top_k: int) -> list[tuple[object, float]]:
    """windows = list of (Window, np.ndarray). Returns top_k pairs ranked by cosine."""
    if not windows:
        return []
    mat = np.stack([v for _, v in windows], axis=0)
    # vectors are already normalized in embed; dot = cosine
    scores = mat @ query_vec
    idx = np.argsort(-scores)[:top_k]
    return [(windows[i][0], float(scores[i])) for i in idx]


def _excerpt_around(text: str, max_chars: int = 320) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


async def skip(url: str, question: str, *, with_frame: bool = True) -> Hit | None:
    """Single-video find. Ingests the URL if not cached, then returns the top hit."""
    pre_id = video_id_for(url)
    v = get_video(pre_id) if pre_id.startswith(("yt_", "f_", "u_")) else None
    if not v or not has_windows(pre_id):
        v = await ingest(url)

    rows = iter_windows_for_video(v.video_id)
    if not rows:
        return None

    qv = np.asarray(embed_text(question), dtype=np.float32)
    top = _topk_cosine(qv, rows, top_k=1)
    if not top:
        return None
    w, score = top[0]

    hit_time = (w.start + w.end) / 2
    hit = Hit(
        video_id=v.video_id,
        title=v.title,
        source=v.source,
        start=w.start,
        end=w.end,
        timestamp_human=fmt_time(hit_time),
        deep_link=deep_link(v.source, hit_time),
        transcript_excerpt=_excerpt_around(w.text),
        score=score,
    )
    if with_frame:
        from videomemory.frames import extract_frame_at

        try:
            path = await extract_frame_at(v.video_id, v.source, hit_time)
            if path:
                hit.frame_uri = _frame_uri(v.video_id, hit_time)
        except Exception:
            pass
    return hit


def search(query: str, *, top_k: int = 5) -> list[Hit]:
    """Cross-video search. Reads everything in the library."""
    rows = iter_all_windows()
    if not rows:
        return []
    qv = np.asarray(embed_text(query), dtype=np.float32)
    top = _topk_cosine(qv, rows, top_k=top_k)
    hits: list[Hit] = []
    for w, score in top:
        v = get_video(w.video_id)
        if not v:
            continue
        hit_time = (w.start + w.end) / 2
        hits.append(
            Hit(
                video_id=w.video_id,
                title=v.title,
                source=v.source,
                start=w.start,
                end=w.end,
                timestamp_human=fmt_time(hit_time),
                deep_link=deep_link(v.source, hit_time),
                transcript_excerpt=_excerpt_around(w.text),
                score=score,
                frame_uri=_frame_uri(w.video_id, hit_time),
            )
        )
    return hits


__all__ = ["skip", "search"]
