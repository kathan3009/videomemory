"""Test 2 — real YouTube clip ingest. Network-gated: skipped offline."""

from __future__ import annotations

from pathlib import Path

import pytest

from videomemory.pipeline.runner import run_ingest
from videomemory.retrieval.router import retrieve_chunks

YT_URL = "https://youtu.be/BM70fDqUo3c"


@pytest.mark.network
@pytest.mark.slow
@pytest.mark.asyncio
async def test_youtube_ingest_and_query(tmp_path: Path) -> None:
    job = await run_ingest(YT_URL, data_dir=tmp_path)
    assert job.video_id.startswith("yt_")
    assert job.status.value == "completed"

    # Ask a question — we just want non-empty retrieval, not a specific answer
    chunks = retrieve_chunks(job.video_id, "summarize the main topic", tmp_path, top_k=3)
    assert chunks, "retrieval should return at least one chunk"
    assert any(c.summary for c in chunks)
