"""Public API for selective frame recall."""

from __future__ import annotations

from pathlib import Path

from videomemory.retrieval.router import retrieve_frames
from videomemory.types import FrameRef


async def recall_frames(
    video_id: str,
    query: str | None = None,
    limit: int = 8,
    data_dir: Path = Path("./data"),
    at_time: float | None = None,
    time_range: tuple[float, float] | None = None,
) -> list[FrameRef]:
    return retrieve_frames(
        video_id=video_id,
        query=query,
        data_dir=data_dir,
        limit=limit,
        at_time=at_time,
        time_range=time_range,
    )
