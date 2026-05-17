"""SQLite store for scribe — lives in the same library DB as videos.

Schema:
    scribe_frames(frame_id PK, captured_at, frame_path, app, title, url,
                  ocr_text, vec BLOB)
    scribe_sessions(session_id PK, started_at, ended_at, app, title_summary,
                    url, frame_ids JSON)
    scribe_notes(note_id PK, session_id, kind, text, t_seconds, timestamp_human,
                 created_at, vec BLOB)
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import numpy as np

from videomemory.config import db_path
from videomemory.scribe.types import CaptureContext, Frame, Note, Session

SCHEMA = """
-- EPHEMERAL: cleared at end-of-day digest. Holds today's raw frames + sessions + notes.
CREATE TABLE IF NOT EXISTS scribe_frames (
    frame_id    TEXT PRIMARY KEY,
    captured_at TEXT NOT NULL,
    frame_path  TEXT NOT NULL,
    app         TEXT NOT NULL,
    title       TEXT NOT NULL,
    url         TEXT,
    ocr_text    TEXT NOT NULL DEFAULT '',
    vec         BLOB
);
CREATE INDEX IF NOT EXISTS idx_sframes_time ON scribe_frames(captured_at);
CREATE INDEX IF NOT EXISTS idx_sframes_app  ON scribe_frames(app);

CREATE TABLE IF NOT EXISTS scribe_sessions (
    session_id    TEXT PRIMARY KEY,
    started_at    TEXT NOT NULL,
    ended_at      TEXT NOT NULL,
    app           TEXT NOT NULL,
    title_summary TEXT NOT NULL DEFAULT '',
    url           TEXT,
    frame_ids     TEXT NOT NULL DEFAULT '[]',
    notes_done    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ssessions_time ON scribe_sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_ssessions_app  ON scribe_sessions(app);
CREATE INDEX IF NOT EXISTS idx_ssessions_notes ON scribe_sessions(notes_done);

CREATE TABLE IF NOT EXISTS scribe_notes (
    note_id         TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    kind            TEXT NOT NULL,
    text            TEXT NOT NULL,
    t_seconds       REAL NOT NULL,
    timestamp_human TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    vec             BLOB
);
CREATE INDEX IF NOT EXISTS idx_snotes_session ON scribe_notes(session_id);
CREATE INDEX IF NOT EXISTS idx_snotes_time    ON scribe_notes(created_at);
CREATE INDEX IF NOT EXISTS idx_snotes_kind    ON scribe_notes(kind);

-- DURABLE: the day artifact. Kept until user explicitly deletes.
CREATE TABLE IF NOT EXISTS scribe_days (
    date            TEXT PRIMARY KEY,         -- 'YYYY-MM-DD'
    markdown_path   TEXT NOT NULL,
    summary         TEXT NOT NULL DEFAULT '',
    active_seconds  REAL NOT NULL DEFAULT 0,
    n_sessions      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scribe_day_lines (
    line_id    TEXT PRIMARY KEY,
    date       TEXT NOT NULL,
    kind       TEXT NOT NULL,                -- did|learned|decided|todo|saw|seen|other
    text       TEXT NOT NULL,
    vec        BLOB
);
CREATE INDEX IF NOT EXISTS idx_sdlines_date ON scribe_day_lines(date);
CREATE INDEX IF NOT EXISTS idx_sdlines_kind ON scribe_day_lines(kind);
"""


@contextmanager
def connect():
    p = db_path()
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        yield con
    finally:
        con.close()


# ----- Frames ------------------------------------------------------------


def insert_frame(f: Frame, vec: list[float] | None = None) -> None:
    blob = np.asarray(vec, dtype=np.float32).tobytes() if vec else None
    with connect() as con:
        con.execute(
            """INSERT OR REPLACE INTO scribe_frames
               (frame_id, captured_at, frame_path, app, title, url, ocr_text, vec)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                f.frame_id,
                f.captured_at.isoformat(),
                f.frame_path,
                f.context.app,
                f.context.title,
                f.context.url,
                f.ocr_text,
                blob,
            ),
        )
        con.commit()


def get_frame(frame_id: str) -> Frame | None:
    with connect() as con:
        r = con.execute("SELECT * FROM scribe_frames WHERE frame_id=?", (frame_id,)).fetchone()
    if not r:
        return None
    return _row_to_frame(r)


def frames_between(start: datetime, end: datetime) -> list[Frame]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM scribe_frames WHERE captured_at BETWEEN ? AND ? ORDER BY captured_at",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    return [_row_to_frame(r) for r in rows]


def recent_frames(limit: int = 200) -> list[Frame]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM scribe_frames ORDER BY captured_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_frame(r) for r in reversed(rows)]


def _row_to_frame(r) -> Frame:
    return Frame(
        frame_id=r["frame_id"],
        captured_at=datetime.fromisoformat(r["captured_at"]),
        frame_path=r["frame_path"],
        ocr_text=r["ocr_text"] or "",
        context=CaptureContext(
            app=r["app"] or "unknown",
            title=r["title"] or "",
            url=r["url"],
        ),
    )


# ----- Sessions ----------------------------------------------------------


def insert_session(s: Session) -> None:
    with connect() as con:
        con.execute(
            """INSERT OR REPLACE INTO scribe_sessions
               (session_id, started_at, ended_at, app, title_summary, url, frame_ids, notes_done)
               VALUES (?,?,?,?,?,?,?,COALESCE((SELECT notes_done FROM scribe_sessions WHERE session_id=?), 0))""",
            (
                s.session_id,
                s.started_at.isoformat(),
                s.ended_at.isoformat(),
                s.app,
                s.title_summary,
                s.url,
                json.dumps(s.frame_ids),
                s.session_id,
            ),
        )
        con.commit()


def get_session(session_id: str) -> Session | None:
    with connect() as con:
        r = con.execute("SELECT * FROM scribe_sessions WHERE session_id=?", (session_id,)).fetchone()
    return _row_to_session(r) if r else None


def sessions_without_notes(limit: int = 50) -> list[Session]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM scribe_sessions WHERE notes_done=0 ORDER BY started_at LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_session(r) for r in rows]


def sessions_between(start: datetime, end: datetime) -> list[Session]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM scribe_sessions WHERE started_at BETWEEN ? AND ? ORDER BY started_at",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    return [_row_to_session(r) for r in rows]


def mark_session_noted(session_id: str) -> None:
    with connect() as con:
        con.execute(
            "UPDATE scribe_sessions SET notes_done=1 WHERE session_id=?",
            (session_id,),
        )
        con.commit()


def _row_to_session(r) -> Session:
    return Session(
        session_id=r["session_id"],
        started_at=datetime.fromisoformat(r["started_at"]),
        ended_at=datetime.fromisoformat(r["ended_at"]),
        app=r["app"],
        title_summary=r["title_summary"] or "",
        url=r["url"],
        frame_ids=json.loads(r["frame_ids"] or "[]"),
    )


# ----- Notes -------------------------------------------------------------


def insert_notes(notes: list[Note], vectors: list[list[float]] | None = None) -> None:
    if not notes:
        return
    rows = []
    for i, n in enumerate(notes):
        vec = vectors[i] if vectors else None
        blob = np.asarray(vec, dtype=np.float32).tobytes() if vec else None
        rows.append(
            (
                n.note_id,
                n.session_id,
                n.kind,
                n.text,
                n.t_seconds,
                n.timestamp_human,
                n.created_at.isoformat(),
                blob,
            )
        )
    with connect() as con:
        con.executemany(
            """INSERT OR REPLACE INTO scribe_notes
               (note_id, session_id, kind, text, t_seconds, timestamp_human, created_at, vec)
               VALUES (?,?,?,?,?,?,?,?)""",
            rows,
        )
        con.commit()


def get_notes_for_session(session_id: str) -> list[Note]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM scribe_notes WHERE session_id=? ORDER BY t_seconds",
            (session_id,),
        ).fetchall()
    return [_row_to_note(r) for r in rows]


def all_notes_with_vecs() -> list[tuple[Note, np.ndarray]]:
    out: list[tuple[Note, np.ndarray]] = []
    with connect() as con:
        rows = con.execute("SELECT * FROM scribe_notes").fetchall()
    for r in rows:
        vec_b = r["vec"]
        if not vec_b:
            continue
        arr = np.frombuffer(vec_b, dtype=np.float32)
        out.append((_row_to_note(r), arr))
    return out


def notes_between(start: datetime, end: datetime) -> list[Note]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM scribe_notes WHERE created_at BETWEEN ? AND ? ORDER BY created_at",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    return [_row_to_note(r) for r in rows]


def _row_to_note(r) -> Note:
    return Note(
        note_id=r["note_id"],
        session_id=r["session_id"],
        kind=r["kind"],
        text=r["text"],
        t_seconds=float(r["t_seconds"]),
        timestamp_human=r["timestamp_human"],
        created_at=datetime.fromisoformat(r["created_at"]),
    )


# ----- Forget / retention ------------------------------------------------


def forget_since(start: datetime) -> dict:
    """Delete everything captured after `start`. Returns counts of rows deleted."""
    with connect() as con:
        affected_frames = list(
            con.execute(
                "SELECT frame_id, frame_path FROM scribe_frames WHERE captured_at >= ?",
                (start.isoformat(),),
            ).fetchall()
        )
        n_frames = len(affected_frames)
        con.execute("DELETE FROM scribe_frames WHERE captured_at >= ?", (start.isoformat(),))
        # Sessions whose end is after `start` → kill those + their notes
        sessions = list(
            con.execute(
                "SELECT session_id FROM scribe_sessions WHERE ended_at >= ?",
                (start.isoformat(),),
            ).fetchall()
        )
        n_sessions = len(sessions)
        session_ids = [s["session_id"] for s in sessions]
        if session_ids:
            placeholders = ",".join("?" * len(session_ids))
            con.execute(f"DELETE FROM scribe_notes WHERE session_id IN ({placeholders})", session_ids)
            con.execute(f"DELETE FROM scribe_sessions WHERE session_id IN ({placeholders})", session_ids)
        con.commit()
    # Best-effort: unlink the JPGs
    for r in affected_frames:
        try:
            Path(r["frame_path"]).unlink(missing_ok=True)
        except Exception:
            pass
    return {"frames": n_frames, "sessions": n_sessions}


def forget_app(app: str) -> dict:
    """Delete every frame/session/note for a given app (exact match)."""
    with connect() as con:
        affected_frames = list(
            con.execute("SELECT frame_id, frame_path FROM scribe_frames WHERE app=?", (app,)).fetchall()
        )
        n_frames = len(affected_frames)
        con.execute("DELETE FROM scribe_frames WHERE app=?", (app,))
        sessions = list(
            con.execute("SELECT session_id FROM scribe_sessions WHERE app=?", (app,)).fetchall()
        )
        n_sessions = len(sessions)
        ids = [s["session_id"] for s in sessions]
        if ids:
            placeholders = ",".join("?" * len(ids))
            con.execute(f"DELETE FROM scribe_notes WHERE session_id IN ({placeholders})", ids)
            con.execute(f"DELETE FROM scribe_sessions WHERE session_id IN ({placeholders})", ids)
        con.commit()
    for r in affected_frames:
        try:
            Path(r["frame_path"]).unlink(missing_ok=True)
        except Exception:
            pass
    return {"frames": n_frames, "sessions": n_sessions}


def purge_older_than(cutoff: datetime) -> dict:
    """Retention purge — opposite of forget_since."""
    with connect() as con:
        affected_frames = list(
            con.execute(
                "SELECT frame_id, frame_path FROM scribe_frames WHERE captured_at < ?",
                (cutoff.isoformat(),),
            ).fetchall()
        )
        n_frames = len(affected_frames)
        con.execute("DELETE FROM scribe_frames WHERE captured_at < ?", (cutoff.isoformat(),))
        sessions = list(
            con.execute(
                "SELECT session_id FROM scribe_sessions WHERE ended_at < ?",
                (cutoff.isoformat(),),
            ).fetchall()
        )
        n_sessions = len(sessions)
        ids = [s["session_id"] for s in sessions]
        if ids:
            placeholders = ",".join("?" * len(ids))
            con.execute(f"DELETE FROM scribe_notes WHERE session_id IN ({placeholders})", ids)
            con.execute(f"DELETE FROM scribe_sessions WHERE session_id IN ({placeholders})", ids)
        con.commit()
    for r in affected_frames:
        try:
            Path(r["frame_path"]).unlink(missing_ok=True)
        except Exception:
            pass
    return {"frames": n_frames, "sessions": n_sessions}


def stats() -> dict:
    with connect() as con:
        n_frames = con.execute("SELECT COUNT(*) FROM scribe_frames").fetchone()[0]
        n_sessions = con.execute("SELECT COUNT(*) FROM scribe_sessions").fetchone()[0]
        n_notes = con.execute("SELECT COUNT(*) FROM scribe_notes").fetchone()[0]
        n_days = con.execute("SELECT COUNT(*) FROM scribe_days").fetchone()[0]
        n_lines = con.execute("SELECT COUNT(*) FROM scribe_day_lines").fetchone()[0]
        first = con.execute("SELECT MIN(captured_at) FROM scribe_frames").fetchone()[0]
        last = con.execute("SELECT MAX(captured_at) FROM scribe_frames").fetchone()[0]
    return {
        "ephemeral_frames": n_frames,
        "ephemeral_sessions": n_sessions,
        "ephemeral_notes": n_notes,
        "durable_days": n_days,
        "durable_lines": n_lines,
        "first_capture": first,
        "last_capture": last,
    }


# ----- Durable day artifacts ---------------------------------------------


def upsert_day(date: str, markdown_path: str, summary: str, active_seconds: float, n_sessions: int) -> None:
    from datetime import datetime as _dt

    with connect() as con:
        con.execute(
            """INSERT OR REPLACE INTO scribe_days
               (date, markdown_path, summary, active_seconds, n_sessions, created_at)
               VALUES (?,?,?,?,?,?)""",
            (date, markdown_path, summary, active_seconds, n_sessions, _dt.utcnow().isoformat()),
        )
        con.commit()


def get_day(date: str) -> dict | None:
    with connect() as con:
        r = con.execute("SELECT * FROM scribe_days WHERE date=?", (date,)).fetchone()
    return dict(r) if r else None


def list_days(limit: int = 30) -> list[dict]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM scribe_days ORDER BY date DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def insert_day_lines(date: str, lines: list[tuple[str, str]], vectors: list[list[float]]) -> None:
    """lines = [(kind, text), ...]"""
    import uuid as _uuid

    rows = []
    for i, (kind, text) in enumerate(lines):
        vec = vectors[i] if i < len(vectors) else None
        blob = np.asarray(vec, dtype=np.float32).tobytes() if vec is not None else None
        rows.append((str(_uuid.uuid4()), date, kind, text, blob))
    if not rows:
        return
    with connect() as con:
        con.executemany(
            "INSERT INTO scribe_day_lines (line_id, date, kind, text, vec) VALUES (?,?,?,?,?)",
            rows,
        )
        con.commit()


def all_day_lines_with_vecs() -> list[tuple[dict, np.ndarray]]:
    out: list[tuple[dict, np.ndarray]] = []
    with connect() as con:
        rows = con.execute("SELECT * FROM scribe_day_lines").fetchall()
    for r in rows:
        vec_b = r["vec"]
        if not vec_b:
            continue
        arr = np.frombuffer(vec_b, dtype=np.float32)
        out.append(
            (
                {"line_id": r["line_id"], "date": r["date"], "kind": r["kind"], "text": r["text"]},
                arr,
            )
        )
    return out


def purge_ephemeral() -> dict:
    """Wipe all today's raw frames + ephemeral sessions/notes (called by digest)."""
    with connect() as con:
        frame_paths = [r[0] for r in con.execute("SELECT frame_path FROM scribe_frames").fetchall()]
        n_frames = con.execute("SELECT COUNT(*) FROM scribe_frames").fetchone()[0]
        n_sessions = con.execute("SELECT COUNT(*) FROM scribe_sessions").fetchone()[0]
        n_notes = con.execute("SELECT COUNT(*) FROM scribe_notes").fetchone()[0]
        con.execute("DELETE FROM scribe_notes")
        con.execute("DELETE FROM scribe_sessions")
        con.execute("DELETE FROM scribe_frames")
        con.commit()
    for p in frame_paths:
        try:
            Path(p).unlink(missing_ok=True)
        except Exception:
            pass
    return {"frames": n_frames, "sessions": n_sessions, "notes": n_notes}


def delete_day(date: str) -> bool:
    with connect() as con:
        n = con.execute("DELETE FROM scribe_day_lines WHERE date=?", (date,)).rowcount
        m = con.execute("DELETE FROM scribe_days WHERE date=?", (date,)).rowcount
        con.commit()
    return n > 0 or m > 0
