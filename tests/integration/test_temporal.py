"""Test 3 — temporal ordering. 'What happened after X' must return chunks after X."""

from __future__ import annotations

from pathlib import Path

import pytest

from videomemory.retrieval.router import retrieve_chunks
from videomemory.retrieval.store_helpers import load_chunks
from videomemory.retrieval.temporal_resolve import detect_anchor


@pytest.mark.asyncio
async def test_temporal_anchor_detection() -> None:
    a = detect_anchor("What happened after Kubernetes was introduced?")
    assert a is not None
    assert a.relation == "after"
    assert "kubernetes" in a.anchor_phrase.lower()

    b = detect_anchor("What was shown before the OAuth slide?")
    assert b is not None
    assert b.relation == "before"

    # "when" alone is NOT an anchor — it's a direct question about timing
    c = detect_anchor("When was OAuth discussed?")
    assert c is None, f"'when' should not produce a temporal anchor, got: {c}"


@pytest.mark.asyncio
async def test_after_kubernetes_returns_later_chunks(tech_talk_ingest, session_data_dir: Path) -> None:
    vid = tech_talk_ingest.video_id
    all_chunks = load_chunks(vid, session_data_dir)
    k_chunk = next((c for c in all_chunks if "kubernetes" in c.summary.lower()), None)
    assert k_chunk is not None, "fixture should contain a Kubernetes chunk"

    results = retrieve_chunks(
        vid, "What happened after Kubernetes was introduced?", session_data_dir, top_k=5
    )
    assert results, "no chunks returned for temporal query"
    # Every returned chunk must start at or after the end of the Kubernetes chunk
    for c in results:
        assert c.start >= k_chunk.end - 0.5, (
            f"chunk {c.start:.1f}-{c.end:.1f} comes BEFORE anchor end {k_chunk.end}"
        )
    # And the Kubernetes chunk itself should not be the top result
    assert "kubernetes" not in results[0].summary.lower()
