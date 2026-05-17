"""Tests 4, 6, 9 — semantic retrieval, OCR queries, multimodal fusion."""

from __future__ import annotations

from pathlib import Path

import pytest

from videomemory.retrieval.router import retrieve_chunks


@pytest.mark.asyncio
async def test_oauth_semantic_retrieval(tech_talk_ingest, session_data_dir: Path) -> None:
    """Test 4: 'When was OAuth discussed?' must return the OAuth chunk first."""
    vid = tech_talk_ingest.video_id
    chunks = retrieve_chunks(vid, "When was OAuth discussed?", session_data_dir, top_k=3)
    assert chunks, "no chunks returned"
    top = chunks[0]
    summary = top.summary.lower()
    assert "oauth" in summary, f"expected OAuth chunk first, got: {top.summary!r}"
    # OAuth slide is at 10–20s
    assert 8.0 <= top.start <= 12.0, f"OAuth chunk should start near 10s, got {top.start}"


@pytest.mark.asyncio
async def test_kubernetes_networking_ocr_query(tech_talk_ingest, session_data_dir: Path) -> None:
    """Test 6: OCR-driven query 'Kubernetes Networking' returns the slide's chunk."""
    vid = tech_talk_ingest.video_id
    chunks = retrieve_chunks(vid, "find scenes mentioning Kubernetes Networking", session_data_dir, top_k=3)
    assert chunks
    top = chunks[0]
    summary = top.summary.lower()
    assert "kubernetes" in summary or "networking" in summary, top.summary
    assert top.start <= 2.0


@pytest.mark.asyncio
async def test_multimodal_fusion_outranks_single_mode(tech_talk_ingest, session_data_dir: Path) -> None:
    """Test 9: fused multimodal retrieval should rank the relevant chunk top."""
    vid = tech_talk_ingest.video_id
    chunks = retrieve_chunks(
        vid,
        "Docker container orchestration",
        session_data_dir,
        top_k=3,
        modalities=["semantic", "transcript", "ocr"],
    )
    assert chunks
    summary = chunks[0].summary.lower()
    assert "docker" in summary, f"top chunk should be Docker; got {chunks[0].summary!r}"
