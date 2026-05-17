"""SQLite metadata store (videos, jobs, scenes, events, entities).

Uses `aiosqlite` for async; provides sync helpers for the CLI's `list` command.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

from videomemory.config import get_settings
from videomemory.storage.artifacts import db_path
from videomemory.types import Entity, Event, Job, JobStatus, Scene, TemporalEdge, VideoMetadata

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    video_id    TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    title       TEXT,
    duration    REAL DEFAULT 0,
    fps         REAL DEFAULT 0,
    width       INTEGER DEFAULT 0,
    height      INTEGER DEFAULT 0,
    codec       TEXT,
    audio_codec TEXT,
    file_size   INTEGER,
    file_path   TEXT,
    sha256      TEXT,
    ingested_at TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    raw         TEXT
);
CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);

CREATE TABLE IF NOT EXISTS jobs (
    job_id        TEXT PRIMARY KEY,
    video_id      TEXT NOT NULL,
    source        TEXT NOT NULL,
    status        TEXT NOT NULL,
    stages_done   TEXT NOT NULL DEFAULT '[]',
    current_stage TEXT,
    error         TEXT,
    artifacts_dir TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_video ON jobs(video_id);

CREATE TABLE IF NOT EXISTS scenes (
    scene_id  TEXT PRIMARY KEY,
    video_id  TEXT NOT NULL,
    idx       INTEGER NOT NULL,
    start     REAL NOT NULL,
    end       REAL NOT NULL,
    raw       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scenes_video ON scenes(video_id);
CREATE INDEX IF NOT EXISTS idx_scenes_time  ON scenes(video_id, start);

CREATE TABLE IF NOT EXISTS entities (
    entity_id  TEXT PRIMARY KEY,
    video_id   TEXT NOT NULL,
    kind       TEXT NOT NULL,
    label      TEXT NOT NULL,
    first_seen REAL NOT NULL,
    last_seen  REAL NOT NULL,
    raw        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entities_video ON entities(video_id);

CREATE TABLE IF NOT EXISTS events (
    event_id  TEXT PRIMARY KEY,
    video_id  TEXT NOT NULL,
    scene_id  TEXT NOT NULL,
    t_start   REAL NOT NULL,
    t_end     REAL NOT NULL,
    verb      TEXT NOT NULL,
    raw       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_video ON events(video_id);
CREATE INDEX IF NOT EXISTS idx_events_time  ON events(video_id, t_start);

CREATE TABLE IF NOT EXISTS temporal_edges (
    src_event_id  TEXT NOT NULL,
    dst_event_id  TEXT NOT NULL,
    relation      TEXT NOT NULL,
    delta_seconds REAL NOT NULL,
    PRIMARY KEY (src_event_id, dst_event_id, relation)
);
"""


def _resolve_db_path(data_dir: Path | None = None) -> Path:
    if data_dir is None:
        data_dir = get_settings().data_dir
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    return db_path(data_dir)


async def init_db(data_dir: Path | None = None) -> None:
    path = _resolve_db_path(data_dir)
    async with aiosqlite.connect(path) as db:
        await db.executescript(SCHEMA)
        await db.commit()


@asynccontextmanager
async def connect(data_dir: Path | None = None) -> AsyncIterator[aiosqlite.Connection]:
    path = _resolve_db_path(data_dir)
    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        await db.executescript(SCHEMA)
        yield db


# --- Videos ---------------------------------------------------------------


async def upsert_video(meta: VideoMetadata, data_dir: Path | None = None) -> None:
    async with connect(data_dir) as db:
        await db.execute(
            """
            INSERT INTO videos (video_id, source, title, duration, fps, width, height,
                                codec, audio_codec, file_size, file_path, sha256,
                                ingested_at, status, raw)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(video_id) DO UPDATE SET
                source=excluded.source, title=excluded.title, duration=excluded.duration,
                fps=excluded.fps, width=excluded.width, height=excluded.height,
                codec=excluded.codec, audio_codec=excluded.audio_codec,
                file_size=excluded.file_size, file_path=excluded.file_path,
                sha256=excluded.sha256, raw=excluded.raw
            """,
            (
                meta.video_id,
                meta.source,
                meta.title,
                meta.duration,
                meta.fps,
                meta.width,
                meta.height,
                meta.codec,
                meta.audio_codec,
                meta.file_size,
                meta.file_path,
                meta.sha256,
                meta.ingested_at.isoformat(),
                "pending",
                meta.model_dump_json(),
            ),
        )
        await db.commit()


async def set_video_status(video_id: str, status: str, data_dir: Path | None = None) -> None:
    async with connect(data_dir) as db:
        await db.execute("UPDATE videos SET status = ? WHERE video_id = ?", (status, video_id))
        await db.commit()


async def get_video(video_id: str, data_dir: Path | None = None) -> VideoMetadata | None:
    async with connect(data_dir) as db:
        cur = await db.execute("SELECT raw FROM videos WHERE video_id = ?", (video_id,))
        row = await cur.fetchone()
    if not row:
        return None
    return VideoMetadata.model_validate_json(row["raw"])


async def list_videos(data_dir: Path | None = None) -> list[dict[str, Any]]:
    async with connect(data_dir) as db:
        cur = await db.execute(
            "SELECT video_id, title, duration, status, ingested_at FROM videos ORDER BY ingested_at DESC"
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


def list_videos_sync(data_dir: Path | None = None) -> list[dict[str, Any]]:
    path = _resolve_db_path(data_dir)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        cur = con.execute(
            "SELECT video_id, title, duration, status, ingested_at FROM videos ORDER BY ingested_at DESC"
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()


# --- Jobs -----------------------------------------------------------------


async def upsert_job(job: Job, data_dir: Path | None = None) -> None:
    async with connect(data_dir) as db:
        await db.execute(
            """
            INSERT INTO jobs (job_id, video_id, source, status, stages_done,
                              current_stage, error, artifacts_dir, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET
                status=excluded.status, stages_done=excluded.stages_done,
                current_stage=excluded.current_stage, error=excluded.error,
                updated_at=excluded.updated_at
            """,
            (
                job.job_id,
                job.video_id,
                job.source,
                job.status.value,
                json.dumps(job.stages_done),
                job.current_stage,
                job.error,
                job.artifacts_dir,
                job.created_at.isoformat(),
                job.updated_at.isoformat(),
            ),
        )
        await db.commit()


async def get_job(job_id: str, data_dir: Path | None = None) -> Job | None:
    async with connect(data_dir) as db:
        cur = await db.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = await cur.fetchone()
    if not row:
        return None
    return Job(
        job_id=row["job_id"],
        video_id=row["video_id"],
        source=row["source"],
        status=JobStatus(row["status"]),
        stages_done=json.loads(row["stages_done"]),
        current_stage=row["current_stage"],
        error=row["error"],
        artifacts_dir=row["artifacts_dir"] or "",
    )


# --- Scenes / Entities / Events / Edges -----------------------------------


async def replace_scenes(video_id: str, scenes: list[Scene], data_dir: Path | None = None) -> None:
    async with connect(data_dir) as db:
        await db.execute("DELETE FROM scenes WHERE video_id = ?", (video_id,))
        await db.executemany(
            "INSERT INTO scenes (scene_id, video_id, idx, start, end, raw) VALUES (?,?,?,?,?,?)",
            [(s.scene_id, s.video_id, s.index, s.start, s.end, s.model_dump_json()) for s in scenes],
        )
        await db.commit()


async def replace_entities(video_id: str, ents: list[Entity], data_dir: Path | None = None) -> None:
    async with connect(data_dir) as db:
        await db.execute("DELETE FROM entities WHERE video_id = ?", (video_id,))
        await db.executemany(
            "INSERT INTO entities (entity_id, video_id, kind, label, first_seen, last_seen, raw) VALUES (?,?,?,?,?,?,?)",
            [
                (e.entity_id, e.video_id, e.kind, e.label, e.first_seen, e.last_seen, e.model_dump_json())
                for e in ents
            ],
        )
        await db.commit()


async def replace_events(video_id: str, events: list[Event], data_dir: Path | None = None) -> None:
    async with connect(data_dir) as db:
        await db.execute("DELETE FROM events WHERE video_id = ?", (video_id,))
        await db.executemany(
            "INSERT INTO events (event_id, video_id, scene_id, t_start, t_end, verb, raw) VALUES (?,?,?,?,?,?,?)",
            [
                (e.event_id, e.video_id, e.scene_id, e.t_start, e.t_end, e.verb, e.model_dump_json())
                for e in events
            ],
        )
        await db.commit()


async def replace_temporal_edges(
    video_id: str, edges: list[TemporalEdge], data_dir: Path | None = None
) -> None:
    async with connect(data_dir) as db:
        # Delete edges whose src event belongs to this video
        await db.execute(
            "DELETE FROM temporal_edges WHERE src_event_id IN (SELECT event_id FROM events WHERE video_id = ?)",
            (video_id,),
        )
        await db.executemany(
            "INSERT OR REPLACE INTO temporal_edges (src_event_id, dst_event_id, relation, delta_seconds) VALUES (?,?,?,?)",
            [(e.src_event_id, e.dst_event_id, e.relation, e.delta_seconds) for e in edges],
        )
        await db.commit()


async def get_scenes(video_id: str, data_dir: Path | None = None) -> list[Scene]:
    async with connect(data_dir) as db:
        cur = await db.execute("SELECT raw FROM scenes WHERE video_id = ? ORDER BY idx", (video_id,))
        rows = await cur.fetchall()
    return [Scene.model_validate_json(r["raw"]) for r in rows]


async def get_events(video_id: str, data_dir: Path | None = None) -> list[Event]:
    async with connect(data_dir) as db:
        cur = await db.execute("SELECT raw FROM events WHERE video_id = ? ORDER BY t_start", (video_id,))
        rows = await cur.fetchall()
    return [Event.model_validate_json(r["raw"]) for r in rows]


async def get_entities(video_id: str, data_dir: Path | None = None) -> list[Entity]:
    async with connect(data_dir) as db:
        cur = await db.execute("SELECT raw FROM entities WHERE video_id = ?", (video_id,))
        rows = await cur.fetchall()
    return [Entity.model_validate_json(r["raw"]) for r in rows]
