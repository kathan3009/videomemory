"""FastAPI app exposing the same surface as MCP, for the web frontend and direct HTTP clients."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from videomemory.api.safety import (
    assert_local_duration_ok,
    assert_url_duration_ok,
    require_ingest_token,
)
from videomemory.config import get_settings
from videomemory.pipeline.runner import run_ingest
from videomemory.query.engine import answer_question
from videomemory.retrieval.router import retrieve_chunks, retrieve_frames
from videomemory.retrieval.store_helpers import load_chunks
from videomemory.storage import sqlite_db
from videomemory.storage.artifacts import ArtifactPaths

log = logging.getLogger(__name__)

# In-memory job tracking (also persisted in SQLite). Maps job_id -> status events.
_job_events: dict[str, asyncio.Queue] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    await sqlite_db.init_db(settings.data_dir)
    yield


app = FastAPI(
    title="VideoMemory API",
    version="0.1.0",
    description="HTTP surface for VideoMemory. Same capabilities as the MCP server.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _data_dir() -> Path:
    return Path(get_settings().data_dir)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/videos")
async def list_videos() -> dict:
    return {"videos": await sqlite_db.list_videos(_data_dir())}


@app.post("/videos/ingest_url", dependencies=[Depends(require_ingest_token)])
async def ingest_url(body: dict, background: BackgroundTasks) -> dict:
    source = body.get("source")
    if not source:
        raise HTTPException(status_code=400, detail="source is required")
    await assert_url_duration_ok(source)
    job_id = str(uuid.uuid4())
    _job_events[job_id] = asyncio.Queue()
    background.add_task(_run_ingest_async, source, job_id)
    return {"job_id": job_id}


@app.post("/videos/upload", dependencies=[Depends(require_ingest_token)])
async def upload(file: UploadFile = File(...), background: BackgroundTasks = None) -> dict:
    data_dir = _data_dir()
    incoming = data_dir / "uploads"
    incoming.mkdir(parents=True, exist_ok=True)
    dest = incoming / f"{uuid.uuid4().hex}_{file.filename}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    await assert_local_duration_ok(dest)
    job_id = str(uuid.uuid4())
    _job_events[job_id] = asyncio.Queue()
    if background is not None:
        background.add_task(_run_ingest_async, str(dest), job_id)
    else:
        asyncio.create_task(_run_ingest_async(str(dest), job_id))
    return {"job_id": job_id, "filename": file.filename}


async def _run_ingest_async(source: str, job_id: str) -> None:
    q = _job_events.get(job_id) or asyncio.Queue()
    _job_events[job_id] = q
    try:
        await q.put({"event": "started", "source": source})
        job = await run_ingest(source, data_dir=_data_dir())
        await q.put({"event": "completed", "video_id": job.video_id, "stages_done": job.stages_done})
    except Exception as exc:
        log.exception("ingest failed")
        await q.put({"event": "failed", "error": str(exc)})


@app.get("/jobs/{job_id}/events")
async def job_events(job_id: str) -> EventSourceResponse:
    q = _job_events.get(job_id)
    if q is None:
        raise HTTPException(status_code=404, detail="unknown job")

    async def gen():
        while True:
            ev = await q.get()
            yield {"data": json.dumps(ev)}
            if ev.get("event") in ("completed", "failed"):
                break

    return EventSourceResponse(gen())


@app.get("/videos/{video_id}/timeline")
async def get_timeline(video_id: str, granularity: str = "chunk") -> dict:
    chunks = load_chunks(video_id, _data_dir())
    if granularity == "scene":
        scenes = await sqlite_db.get_scenes(video_id, _data_dir())
        return {"granularity": "scene", "entries": [s.model_dump(mode="json") for s in scenes]}
    if granularity == "event":
        events = await sqlite_db.get_events(video_id, _data_dir())
        return {"granularity": "event", "entries": [e.model_dump(mode="json") for e in events]}
    return {"granularity": "chunk", "entries": [c.model_dump(mode="json") for c in chunks]}


@app.get("/videos/{video_id}/transcript")
async def get_transcript(video_id: str, speaker: str | None = None) -> dict:
    scenes = await sqlite_db.get_scenes(video_id, _data_dir())
    segs = []
    for sc in scenes:
        for seg in sc.transcript_segments:
            if speaker and seg.speaker != speaker:
                continue
            segs.append(seg.model_dump(mode="json"))
    return {"segments": segs}


@app.post("/videos/{video_id}/query")
async def query(video_id: str, body: dict) -> dict:
    q = body.get("query")
    if not q:
        raise HTTPException(status_code=400, detail="query is required")
    res = await answer_question(
        video_id=video_id,
        query=q,
        data_dir=_data_dir(),
        max_chunks=int(body.get("max_chunks", 5)),
        max_frames=int(body.get("max_frames", 8)),
        include_frames=bool(body.get("include_frames", True)),
    )
    return res.model_dump(mode="json")


@app.post("/videos/{video_id}/semantic_search")
async def semantic_search(video_id: str, body: dict) -> dict:
    q = body.get("query")
    if not q:
        raise HTTPException(status_code=400, detail="query is required")
    chunks = retrieve_chunks(
        video_id=video_id,
        query=q,
        data_dir=_data_dir(),
        top_k=int(body.get("top_k", 10)),
        modalities=body.get("modalities"),
    )
    return {"results": [c.model_dump(mode="json") for c in chunks]}


@app.get("/videos/{video_id}/frames")
async def get_frames(
    video_id: str,
    query: str | None = None,
    at_time: float | None = None,
    limit: int = 8,
) -> dict:
    frames = retrieve_frames(
        video_id=video_id,
        query=query,
        data_dir=_data_dir(),
        limit=limit,
        at_time=at_time,
    )
    return {"frames": [f.model_dump(mode="json") for f in frames]}


@app.get("/videos/{video_id}/frames/{name}")
async def frame_file(video_id: str, name: str) -> FileResponse:
    path = ArtifactPaths(_data_dir(), video_id).frames_dir / name
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path)
