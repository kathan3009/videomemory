"""Tool handlers used by the MCP server."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from videomemory.pipeline.runner import run_ingest
from videomemory.query.engine import answer_question
from videomemory.retrieval.router import retrieve_chunks, retrieve_frames
from videomemory.retrieval.store_helpers import load_chunks
from videomemory.storage import sqlite_db


def _frame_uri(video_id: str, frame_path: str) -> str:
    name = Path(frame_path).name
    return f"videomemory://frames/{video_id}/{name}"


async def handle_ingest_video(args: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    source = args["source"]
    job = await run_ingest(source=source, data_dir=data_dir)
    return {
        "job_id": job.job_id,
        "video_id": job.video_id,
        "status": job.status.value,
        "stages_done": job.stages_done,
    }


async def handle_list_videos(args: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    videos = await sqlite_db.list_videos(data_dir)
    return {"videos": videos}


async def handle_query_video(args: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    video_id = args["video_id"]
    query = args["query"]
    max_chunks = int(args.get("max_chunks", 5))
    max_frames = int(args.get("max_frames", 8))
    include_frames = bool(args.get("include_frames", True))
    result = await answer_question(
        video_id=video_id,
        query=query,
        data_dir=data_dir,
        max_chunks=max_chunks,
        max_frames=max_frames,
        include_frames=include_frames,
    )
    return {
        "video_id": result.video_id,
        "query": result.query,
        "answer": result.answer,
        "chunks": [
            {
                "chunk_id": c.chunk_id,
                "start": c.start,
                "end": c.end,
                "summary": c.summary,
                "transcript_excerpt": c.transcript_excerpt[:600],
                "entities": c.entities,
                "ocr_excerpts": c.ocr_excerpts[:4],
                "score": c.score,
            }
            for c in result.chunks
        ],
        "frames": [
            {
                "uri": _frame_uri(result.video_id, f.frame_path),
                "timestamp": f.timestamp,
                "scene_id": f.scene_id,
                "why": f.why,
                "score": f.score,
            }
            for f in result.frames
        ],
        "events": [
            {"event_id": e.event_id, "t_start": e.t_start, "t_end": e.t_end, "description": e.description}
            for e in result.events
        ],
        "token_estimate": result.token_estimate,
    }


async def handle_get_timeline(args: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    video_id = args["video_id"]
    granularity = args.get("granularity", "chunk")
    if granularity == "scene":
        scenes = await sqlite_db.get_scenes(video_id, data_dir)
        return {
            "video_id": video_id,
            "granularity": "scene",
            "entries": [
                {"start": s.start, "end": s.end, "summary": s.caption, "scene_id": s.scene_id, "entities": s.entity_ids}
                for s in scenes
            ],
        }
    if granularity == "event":
        events = await sqlite_db.get_events(video_id, data_dir)
        return {
            "video_id": video_id,
            "granularity": "event",
            "entries": [
                {"start": e.t_start, "end": e.t_end, "summary": e.description, "verb": e.verb}
                for e in events
            ],
        }
    # default: chunk
    chunks = load_chunks(video_id, data_dir)
    return {
        "video_id": video_id,
        "granularity": "chunk",
        "entries": [
            {"start": c.start, "end": c.end, "summary": c.summary, "entities": c.entities, "scene_ids": c.scene_ids}
            for c in chunks
        ],
    }


async def handle_get_frames(args: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    video_id = args["video_id"]
    query = args.get("query")
    at_time = args.get("at_time")
    rng = args.get("range")
    limit = int(args.get("limit", 8))
    time_range = tuple(rng) if rng and len(rng) == 2 else None  # type: ignore[assignment]
    frames = retrieve_frames(
        video_id=video_id,
        query=query,
        data_dir=data_dir,
        limit=limit,
        at_time=at_time,
        time_range=time_range,
    )
    return {
        "video_id": video_id,
        "frames": [
            {
                "uri": _frame_uri(video_id, f.frame_path),
                "timestamp": f.timestamp,
                "scene_id": f.scene_id,
                "why": f.why,
                "score": f.score,
            }
            for f in frames
        ],
    }


async def handle_semantic_search(args: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    video_id = args["video_id"]
    query = args["query"]
    modalities = args.get("modalities") or ["semantic", "transcript", "ocr"]
    top_k = int(args.get("top_k", 10))
    if "fuse" in modalities:
        modalities = ["semantic", "transcript", "ocr"]
    chunks = retrieve_chunks(video_id, query, data_dir, top_k=top_k, modalities=modalities)
    return {
        "video_id": video_id,
        "query": query,
        "modalities": modalities,
        "results": [
            {
                "chunk_id": c.chunk_id,
                "start": c.start,
                "end": c.end,
                "score": c.score,
                "summary": c.summary,
            }
            for c in chunks
        ],
    }


async def handle_get_transcript(args: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    video_id = args["video_id"]
    speaker = args.get("speaker")
    start = args.get("start")
    end = args.get("end")
    scenes = await sqlite_db.get_scenes(video_id, data_dir)
    segs = []
    for sc in scenes:
        for seg in sc.transcript_segments:
            if speaker and seg.speaker != speaker:
                continue
            if start is not None and seg.end < float(start):
                continue
            if end is not None and seg.start > float(end):
                continue
            segs.append(seg.model_dump(mode="json"))
    return {"video_id": video_id, "segments": segs}
