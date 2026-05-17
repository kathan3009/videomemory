"""Deterministic frame → session clustering.

Cluster boundary rules:
  - app change ⇒ new session
  - title fundamentally changes (different first 3 tokens) ⇒ new session
  - time gap between consecutive frames > 60 s ⇒ new session
  - sessions shorter than `min_session_seconds` are dropped (just glancing)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from videomemory.scribe.store import (
    frames_between,
    insert_session,
    recent_frames,
)
from videomemory.scribe.types import Frame, Session

MIN_SESSION_SECONDS = 20.0
MAX_GAP_SECONDS = 60.0


def _title_signature(title: str) -> str:
    """Coarse title fingerprint: lowercased first 3 words."""
    tokens = (title or "").lower().split()
    return " ".join(tokens[:3])


def cluster(frames: list[Frame], *, min_session_seconds: float = MIN_SESSION_SECONDS) -> list[Session]:
    if not frames:
        return []
    frames = sorted(frames, key=lambda f: f.captured_at)
    clusters: list[list[Frame]] = []
    cur: list[Frame] = [frames[0]]
    for f in frames[1:]:
        prev = cur[-1]
        gap = (f.captured_at - prev.captured_at).total_seconds()
        same_app = f.context.app == prev.context.app
        same_title = _title_signature(f.context.title) == _title_signature(prev.context.title)
        if gap <= MAX_GAP_SECONDS and same_app and same_title:
            cur.append(f)
        else:
            clusters.append(cur)
            cur = [f]
    clusters.append(cur)

    sessions: list[Session] = []
    for group in clusters:
        start = group[0].captured_at
        end = group[-1].captured_at
        duration = (end - start).total_seconds()
        if duration < min_session_seconds and len(group) < 3:
            continue
        # Title summary = most-frequent non-empty title in the group
        titles = [g.context.title for g in group if g.context.title]
        title_summary = max(set(titles), key=titles.count) if titles else group[0].context.app
        # Pick representative URL (most frequent)
        urls = [g.context.url for g in group if g.context.url]
        url = max(set(urls), key=urls.count) if urls else None
        sessions.append(
            Session(
                session_id=str(uuid.uuid4()),
                started_at=start,
                ended_at=end,
                app=group[0].context.app,
                title_summary=title_summary[:200],
                url=url,
                frame_ids=[g.frame_id for g in group],
            )
        )
    return sessions


def rebuild_today_sessions() -> list[Session]:
    """Replace ephemeral sessions with a fresh cluster over current scribe_frames."""
    frames = recent_frames(limit=20_000)
    sessions = cluster(frames)
    for s in sessions:
        insert_session(s)
    return sessions


def cluster_range(start: datetime, end: datetime) -> list[Session]:
    return cluster(frames_between(start, end))
