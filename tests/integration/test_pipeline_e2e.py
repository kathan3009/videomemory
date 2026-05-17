"""Test 1 — full ingest pipeline produces all expected artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from videomemory.storage.artifacts import ArtifactPaths


@pytest.mark.asyncio
async def test_full_pipeline_artifacts(tech_talk_ingest, session_data_dir: Path) -> None:
    video_id = tech_talk_ingest.video_id
    paths = ArtifactPaths(session_data_dir, video_id)

    # All artifact files exist
    assert paths.metadata_json.exists()
    assert paths.scenes_json.exists()
    assert paths.transcript_json.exists()
    assert paths.vision_json.exists()
    assert paths.memory_json.exists()
    assert paths.chunks_json.exists()
    assert paths.frames_dir.exists()

    # Schemas validate
    scenes = json.load(open(paths.scenes_json))
    assert len(scenes) >= 2

    chunks = json.load(open(paths.chunks_json))
    assert len(chunks) >= 2
    for c in chunks:
        assert "chunk_id" in c
        assert "summary" in c
        assert "embedding" in c
        assert isinstance(c["embedding"], list)
        assert len(c["embedding"]) >= 256  # bge-small is 384

    memory = json.load(open(paths.memory_json))
    assert "entities" in memory
    assert "events" in memory
    assert "edges" in memory
    assert len(memory["events"]) >= 1
