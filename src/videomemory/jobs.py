"""Bounded in-process job runner for video ingestion.

The first hosted release runs one persistent worker and records job state durably.
The interface is intentionally small so execution can move to a separate worker
queue without changing the dashboard API.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from videomemory.control import create_job, pending_jobs, record_usage, update_job
from videomemory.ingest import ingest, video_id_for
from videomemory.library import get_video
from videomemory.memory_graph import record_tool_memory
from videomemory.tenant import tenant_scope
from videomemory.url_safety import validate_public_url

log = logging.getLogger(__name__)
_semaphore = asyncio.Semaphore(max(1, int(os.environ.get("VIDEOMEMORY_JOB_CONCURRENCY", "1"))))
_tasks: set[asyncio.Task] = set()


async def _run_ingest(user_id: str, job_id: str, source: str) -> None:
    async with _semaphore:
        try:
            update_job(job_id, user_id, status="processing", progress=0.1)
            safe_source = await validate_public_url(source)
            with tenant_scope(user_id):
                was_indexed = get_video(video_id_for(safe_source)) is not None
                video = await ingest(safe_source)
                record_tool_memory("add", {"url": safe_source}, video.model_dump(mode="json"))
            update_job(job_id, user_id, status="completed", progress=1.0, result_json=json.dumps(video.model_dump(mode="json")))
            if not was_indexed:
                record_usage(user_id, "videos", 1, {"video_id": video.video_id})
                record_usage(user_id, "minutes", max(0, video.duration / 60), {"video_id": video.video_id})
        except Exception as exc:
            log.exception("job %s failed", job_id)
            update_job(job_id, user_id, status="failed", error=str(exc)[:500])


def enqueue_ingest(user_id: str, source: str) -> dict[str, Any]:
    job = create_job(user_id, "ingest", source)
    task = asyncio.create_task(_run_ingest(user_id, job["job_id"], source), name=job["job_id"])
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job


def recover_pending_jobs() -> int:
    recovered = pending_jobs()
    for job in recovered:
        task = asyncio.create_task(
            _run_ingest(job["user_id"], job["job_id"], job["source"]), name=job["job_id"]
        )
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    return len(recovered)


async def shutdown_jobs() -> None:
    for task in tuple(_tasks):
        task.cancel()
    if _tasks:
        await asyncio.gather(*_tasks, return_exceptions=True)


__all__ = ["enqueue_ingest", "recover_pending_jobs", "shutdown_jobs"]
