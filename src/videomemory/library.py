"""SQLite-backed library: videos + transcript windows + embeddings.

Schema (all in one file — easy to back up, share via Dropbox, ship to a friend):

    videos(video_id PK, source, title, duration, added_at, file_path)
    windows(window_id PK, video_id, idx, start, end, text, vec BLOB)
        vec = float32 numpy array (bge-small = 384 dims = 1536 bytes)
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from videomemory.config import db_path
from videomemory.types import Video, Window

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    video_id   TEXT PRIMARY KEY,
    source     TEXT NOT NULL,
    title      TEXT,
    duration   REAL DEFAULT 0,
    added_at   TEXT NOT NULL,
    file_path  TEXT
);

CREATE TABLE IF NOT EXISTS windows (
    window_id  TEXT PRIMARY KEY,
    video_id   TEXT NOT NULL,
    idx        INTEGER NOT NULL,
    start      REAL NOT NULL,
    end        REAL NOT NULL,
    text       TEXT NOT NULL,
    vec        BLOB
);
CREATE INDEX IF NOT EXISTS idx_windows_video ON windows(video_id);
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


# ----- Videos ------------------------------------------------------------


def upsert_video(v: Video) -> None:
    with connect() as con:
        con.execute(
            """INSERT INTO videos (video_id, source, title, duration, added_at, file_path)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(video_id) DO UPDATE SET
                 source=excluded.source, title=excluded.title,
                 duration=excluded.duration, file_path=excluded.file_path""",
            (v.video_id, v.source, v.title, v.duration, v.added_at.isoformat(), v.file_path),
        )
        con.commit()


def get_video(video_id: str) -> Video | None:
    with connect() as con:
        row = con.execute("SELECT * FROM videos WHERE video_id=?", (video_id,)).fetchone()
    return Video.model_validate(dict(row)) if row else None


def list_videos() -> list[Video]:
    with connect() as con:
        rows = con.execute("SELECT * FROM videos ORDER BY added_at DESC").fetchall()
    return [Video.model_validate(dict(r)) for r in rows]


def delete_video(video_id: str) -> None:
    with connect() as con:
        con.execute("DELETE FROM windows WHERE video_id=?", (video_id,))
        con.execute("DELETE FROM videos WHERE video_id=?", (video_id,))
        con.commit()


def has_windows(video_id: str) -> bool:
    with connect() as con:
        n = con.execute("SELECT COUNT(*) FROM windows WHERE video_id=?", (video_id,)).fetchone()[0]
    return n > 0


# ----- Windows -----------------------------------------------------------


def insert_windows(windows: Iterable[Window], vectors: list[list[float]] | None = None) -> None:
    rows: list[tuple] = []
    for i, w in enumerate(windows):
        vec_blob: bytes | None = None
        if vectors is not None:
            arr = np.asarray(vectors[i], dtype=np.float32)
            vec_blob = arr.tobytes()
        rows.append(
            (w.window_id, w.video_id, w.idx, w.start, w.end, w.text, vec_blob)
        )
    if not rows:
        return
    with connect() as con:
        con.executemany(
            "INSERT OR REPLACE INTO windows (window_id, video_id, idx, start, end, text, vec) VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        con.commit()


def get_windows(video_id: str) -> list[Window]:
    with connect() as con:
        rows = con.execute(
            "SELECT window_id, video_id, idx, start, end, text FROM windows WHERE video_id=? ORDER BY idx",
            (video_id,),
        ).fetchall()
    return [Window.model_validate(dict(r)) for r in rows]


def iter_all_windows() -> list[tuple[Window, np.ndarray]]:
    out: list[tuple[Window, np.ndarray]] = []
    with connect() as con:
        rows = con.execute(
            "SELECT window_id, video_id, idx, start, end, text, vec FROM windows"
        ).fetchall()
    for r in rows:
        vec = r["vec"]
        arr = np.frombuffer(vec, dtype=np.float32) if vec else None
        w = Window(
            window_id=r["window_id"],
            video_id=r["video_id"],
            idx=r["idx"],
            start=r["start"],
            end=r["end"],
            text=r["text"],
        )
        if arr is not None:
            out.append((w, arr))
    return out


def iter_windows_for_video(video_id: str) -> list[tuple[Window, np.ndarray]]:
    with connect() as con:
        rows = con.execute(
            "SELECT window_id, video_id, idx, start, end, text, vec FROM windows WHERE video_id=? ORDER BY idx",
            (video_id,),
        ).fetchall()
    out: list[tuple[Window, np.ndarray]] = []
    for r in rows:
        vec = r["vec"]
        arr = np.frombuffer(vec, dtype=np.float32) if vec else None
        w = Window(
            window_id=r["window_id"],
            video_id=r["video_id"],
            idx=r["idx"],
            start=r["start"],
            end=r["end"],
            text=r["text"],
        )
        if arr is not None:
            out.append((w, arr))
    return out


# ----- Bundle export/import ----------------------------------------------


def export_bundle(out_path: Path) -> Path:
    """Export the library DB as a portable JSON sidecar + sqlite copy."""
    import shutil

    src = db_path()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, out_path)
    return out_path


def import_bundle(in_path: Path, merge: bool = True) -> int:
    """Import another library's videos + windows. Returns count of merged videos."""
    in_path = Path(in_path)
    if not in_path.exists():
        raise FileNotFoundError(in_path)
    src = sqlite3.connect(in_path)
    src.row_factory = sqlite3.Row
    try:
        videos = [dict(r) for r in src.execute("SELECT * FROM videos").fetchall()]
        windows = [dict(r) for r in src.execute("SELECT * FROM windows").fetchall()]
    finally:
        src.close()

    with connect() as con:
        if not merge:
            con.execute("DELETE FROM windows")
            con.execute("DELETE FROM videos")
        con.executemany(
            "INSERT OR REPLACE INTO videos (video_id, source, title, duration, added_at, file_path) "
            "VALUES (:video_id,:source,:title,:duration,:added_at,:file_path)",
            videos,
        )
        con.executemany(
            "INSERT OR REPLACE INTO windows (window_id, video_id, idx, start, end, text, vec) "
            "VALUES (:window_id,:video_id,:idx,:start,:end,:text,:vec)",
            windows,
        )
        con.commit()
    return len(videos)


def stats() -> dict:
    with connect() as con:
        n_videos = con.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        n_windows = con.execute("SELECT COUNT(*) FROM windows").fetchone()[0]
        total_duration = con.execute("SELECT COALESCE(SUM(duration),0) FROM videos").fetchone()[0]
    return {
        "videos": n_videos,
        "windows": n_windows,
        "total_duration_seconds": float(total_duration),
        "db_path": str(db_path()),
    }


__all__ = [
    "Video",
    "Window",
    "upsert_video",
    "get_video",
    "list_videos",
    "delete_video",
    "has_windows",
    "insert_windows",
    "get_windows",
    "iter_all_windows",
    "iter_windows_for_video",
    "export_bundle",
    "import_bundle",
    "stats",
]
