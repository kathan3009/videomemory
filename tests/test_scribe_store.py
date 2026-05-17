"""Round-trip CRUD for scribe SQLite tables."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from videomemory.scribe import store
from videomemory.scribe.types import CaptureContext, Frame, Note, Session


def _frame(i: int, app: str, base: datetime) -> Frame:
    return Frame(
        frame_id=f"f-{i}-{uuid.uuid4().hex[:6]}",
        captured_at=base + timedelta(seconds=i * 2),
        frame_path=f"/tmp/{i}.jpg",
        ocr_text=f"hello {i}",
        context=CaptureContext(app=app, title="t"),
    )


def test_frame_roundtrip():
    f = _frame(0, "VSCode", datetime.now())
    store.insert_frame(f, vec=[0.1] * 384)
    got = store.get_frame(f.frame_id)
    assert got is not None and got.ocr_text == "hello 0"


def test_session_roundtrip_and_mark_noted():
    base = datetime.now()
    s = Session(
        session_id=str(uuid.uuid4()),
        started_at=base,
        ended_at=base + timedelta(minutes=5),
        app="VSCode",
        title_summary="scribe.py",
        url=None,
        frame_ids=["a", "b", "c"],
    )
    store.insert_session(s)
    got = store.get_session(s.session_id)
    assert got is not None and got.app == "VSCode"
    pending = store.sessions_without_notes()
    assert any(x.session_id == s.session_id for x in pending)
    store.mark_session_noted(s.session_id)
    pending2 = store.sessions_without_notes()
    assert not any(x.session_id == s.session_id for x in pending2)


def test_day_lines_roundtrip_and_search_seed():
    store.upsert_day(
        date="2026-05-18",
        markdown_path="/tmp/day.md",
        summary="test day",
        active_seconds=600.0,
        n_sessions=3,
    )
    assert store.get_day("2026-05-18") is not None
    store.insert_day_lines(
        "2026-05-18",
        [("did", "wrote scribe"), ("learned", "WAL mode helps")],
        [[0.1] * 384, [0.2] * 384],
    )
    rows = store.all_day_lines_with_vecs()
    assert any(r[0]["text"] == "wrote scribe" for r in rows)


def test_purge_ephemeral_clears_frames_sessions_notes():
    base = datetime.now()
    f = _frame(99, "VSCode", base)
    store.insert_frame(f, vec=[0.0] * 384)
    s = Session(
        session_id=str(uuid.uuid4()), started_at=base, ended_at=base + timedelta(seconds=30),
        app="VSCode", title_summary="x", url=None, frame_ids=[f.frame_id],
    )
    store.insert_session(s)
    n = Note(
        note_id=str(uuid.uuid4()), session_id=s.session_id, kind="did",
        text="x", t_seconds=0, timestamp_human="00:00", created_at=base,
    )
    store.insert_notes([n])
    stats_before = store.stats()
    assert stats_before["ephemeral_frames"] >= 1

    purged = store.purge_ephemeral()
    assert purged["frames"] >= 1
    stats_after = store.stats()
    assert stats_after["ephemeral_frames"] == 0
    assert stats_after["ephemeral_sessions"] == 0
    assert stats_after["ephemeral_notes"] == 0
    # Day artifact survived
    assert store.get_day("2026-05-18") is not None


def test_forget_since_deletes_recent_only():
    # Set up: two frames, one 2 days ago, one 10 minutes ago.
    base = datetime.now()
    old = base - timedelta(days=2)
    recent = base - timedelta(minutes=10)
    store.insert_frame(
        Frame(
            frame_id=f"old-{uuid.uuid4().hex[:6]}",
            captured_at=old,
            frame_path="/tmp/old.jpg",
            ocr_text="old",
            context=CaptureContext(app="VSCode", title="x"),
        ),
        vec=[0.0] * 384,
    )
    store.insert_frame(
        Frame(
            frame_id=f"new-{uuid.uuid4().hex[:6]}",
            captured_at=recent,
            frame_path="/tmp/new.jpg",
            ocr_text="new",
            context=CaptureContext(app="VSCode", title="x"),
        ),
        vec=[0.0] * 384,
    )
    cutoff = base - timedelta(minutes=20)
    res = store.forget_since(cutoff)
    assert res["frames"] >= 1  # at least the recent one was deleted
    # The 2-day-old one should still be in the table
    assert any(
        f.ocr_text == "old"
        for f in store.recent_frames(limit=100)
    )
