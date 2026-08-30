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
from pathlib import Path
from typing import Any

from videomemory.config import data_dir
from videomemory.control import create_job, pending_jobs, record_usage, update_job, usage_summary
from videomemory.ingest import ingest, video_id_for
from videomemory.library import get_video
from videomemory.memory_graph import record_tool_memory
from videomemory.tenant import tenant_scope
from videomemory.url_safety import validate_public_url

log = logging.getLogger(__name__)
_semaphore = asyncio.Semaphore(max(1, int(os.environ.get("VIDEOMEMORY_JOB_CONCURRENCY", "1"))))
_tasks: set[asyncio.Task] = set()


def _trusted_upload(source: str) -> str:
    uploads = (data_dir() / "uploads").resolve()
    candidate = Path(source).resolve()
    if not candidate.is_relative_to(uploads) or not candidate.is_file():
        raise ValueError("uploaded file is unavailable")
    return str(candidate)


async def _run_ingest(user_id: str, job_id: str, source: str, kind: str = "ingest") -> None:
    async with _semaphore:
        try:
            update_job(job_id, user_id, status="processing", progress=0.1)
            with tenant_scope(user_id):
                safe_source = _trusted_upload(source) if kind == "upload" else await validate_public_url(source)
                file_path = Path(safe_source) if kind == "upload" else None
                was_indexed = get_video(video_id_for(safe_source, file_path=file_path)) is not None
                usage = usage_summary(user_id)
                remaining_minutes = usage["limits"]["minutes"] - usage["totals"].get("minutes", 0)
                if remaining_minutes <= 0:
                    raise ValueError("monthly indexed-minutes limit reached")
                video = await ingest(
                    safe_source,
                    trusted_upload=kind == "upload",
                    max_duration_seconds=remaining_minutes * 60,
                )
                memory_args = (
                    {"display_source": f"upload://{video.title or 'media'}", "source_type": "upload"}
                    if kind == "upload"
                    else {"url": safe_source, "source_type": "url"}
                )
                record_tool_memory("add", memory_args, video.model_dump(mode="json"))
            update_job(job_id, user_id, status="completed", progress=1.0, result_json=json.dumps(video.model_dump(mode="json")))
            if not was_indexed:
                record_usage(user_id, "videos", 1, {"video_id": video.video_id})
                record_usage(user_id, "minutes", max(0, video.duration / 60), {"video_id": video.video_id})
        except Exception as exc:
            log.exception("job %s failed", job_id)
            update_job(job_id, user_id, status="failed", error=str(exc)[:500])
            if kind == "upload":
                with tenant_scope(user_id):
                    try:
                        _trusted_upload(source)
                    except ValueError:
                        pass
                    else:
                        Path(source).unlink(missing_ok=True)
                        Path(source).with_suffix(".name").unlink(missing_ok=True)


def enqueue_ingest(user_id: str, source: str) -> dict[str, Any]:
    job = create_job(user_id, "ingest", source)
    task = asyncio.create_task(_run_ingest(user_id, job["job_id"], source), name=job["job_id"])
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job


def enqueue_upload(user_id: str, source: str) -> dict[str, Any]:
    job = create_job(user_id, "upload", source)
    task = asyncio.create_task(_run_ingest(user_id, job["job_id"], source, "upload"), name=job["job_id"])
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job


def recover_pending_jobs() -> int:
    recovered = pending_jobs()
    for job in recovered:
        task = asyncio.create_task(
            _run_ingest(job["user_id"], job["job_id"], job["source"], job["kind"]), name=job["job_id"]
        )
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    return len(recovered)


async def shutdown_jobs() -> None:
    for task in tuple(_tasks):
        task.cancel()
    if _tasks:
        await asyncio.gather(*_tasks, return_exceptions=True)


__all__ = ["enqueue_ingest", "enqueue_upload", "recover_pending_jobs", "shutdown_jobs"]
