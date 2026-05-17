"""Resume helper — re-enters run_ingest which is fully cache-aware."""

from __future__ import annotations

from pathlib import Path

from videomemory.pipeline.runner import resume as _resume
from videomemory.types import Job


async def resume_job(job_id: str, data_dir: Path) -> Job:
    return await _resume(job_id, data_dir)
