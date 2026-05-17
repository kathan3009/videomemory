"""Test 6 — exact OCR-text retrieval."""

from __future__ import annotations

from pathlib import Path

import pytest

from videomemory.retrieval.router import retrieve_chunks


@pytest.mark.asyncio
async def test_ocr_term_finds_slide(tech_talk_ingest, session_data_dir: Path) -> None:
    vid = tech_talk_ingest.video_id
    chunks = retrieve_chunks(vid, "Kubernetes Networking", session_data_dir, top_k=3)
    assert chunks
    top = chunks[0]
    # Slide 1 is 0–10s
    assert top.start <= 5.0
    flat_ocr = " ".join(top.ocr_excerpts).lower()
    assert "kubernetes" in flat_ocr or "networking" in flat_ocr
