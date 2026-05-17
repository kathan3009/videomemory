"""Test 11 — resumable pipeline: cached stages must not be re-run."""

from __future__ import annotations

from pathlib import Path

import pytest

from videomemory.pipeline.runner import run_ingest
from videomemory.storage.artifacts import ArtifactPaths


@pytest.mark.asyncio
async def test_resume_skips_completed_stages(tmp_path: Path, tech_talk_path: Path) -> None:
    # First run
    job1 = await run_ingest(str(tech_talk_path), data_dir=tmp_path)
    paths = ArtifactPaths(tmp_path, job1.video_id)
    # Capture mtimes of stage markers
    stages = ("resolve_source", "detect_scenes", "extract_keyframes", "transcribe_audio", "analyze_vision")
    marker_mtimes = {s: paths.stage_marker(s).stat().st_mtime for s in stages if paths.stage_marker(s).exists()}
    assert marker_mtimes, "first run did not create any stage markers"

    # Second run should be a no-op for cached stages
    job2 = await run_ingest(str(tech_talk_path), data_dir=tmp_path)
    assert job2.video_id == job1.video_id
    for s, m in marker_mtimes.items():
        new_m = paths.stage_marker(s).stat().st_mtime
        assert new_m == m, f"stage {s} marker mtime changed: cache was bypassed"
