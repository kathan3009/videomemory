"""Test 5 — selective frame recall must NOT return all frames."""

from __future__ import annotations

from pathlib import Path

import pytest

from videomemory.retrieval.frame_recall import recall_frames
from videomemory.retrieval.store_helpers import load_keyframe_index


@pytest.mark.asyncio
async def test_frame_recall_is_selective(whiteboard_ingest, session_data_dir: Path) -> None:
    vid = whiteboard_ingest.video_id
    all_frames = load_keyframe_index(vid, session_data_dir)
    assert all_frames, "fixture should have keyframes"

    frames = await recall_frames(vid, "whiteboard", limit=3, data_dir=session_data_dir)
    assert frames, "must return at least one frame"
    assert len(frames) <= 3
    # Frames are far fewer than the total inventory (selective recall)
    assert len(frames) <= max(3, int(len(all_frames) * 0.5))
    # Top frame should explain itself
    assert frames[0].why, "frame must have a 'why' explanation"
    # Top frame's score should be > 0 (not pure default)
    assert frames[0].score > 0
