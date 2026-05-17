"""get_frames() — works on visual videos where transcript-based skip falls flat."""

from __future__ import annotations

import asyncio
from pathlib import Path

from videomemory.frames import get_frames


def test_get_frames_count_returns_n_distinct_timestamps(silent_path: Path):
    frames = asyncio.run(get_frames(str(silent_path), count=6))
    assert len(frames) == 6, f"expected 6 frames, got {len(frames)}"
    timestamps = [f.timestamp_seconds for f in frames]
    # all distinct
    assert len(set(timestamps)) == 6
    # in chronological order
    assert timestamps == sorted(timestamps)
    # all have URIs and deep links
    for f in frames:
        assert f.frame_uri.startswith("videomemory://frames/")
        assert "#t=" in f.deep_link


def test_get_frames_every_seconds(silent_path: Path):
    frames = asyncio.run(get_frames(str(silent_path), every=5.0))
    assert frames, "expected at least one frame"
    # 30s video / 5s = ~6 frames
    assert 4 <= len(frames) <= 7


def test_get_frames_explicit_timestamps(silent_path: Path):
    frames = asyncio.run(get_frames(str(silent_path), at=[2.0, 12.0, 22.0]))
    assert len(frames) == 3
    times = [f.timestamp_seconds for f in frames]
    assert times == [2.0, 12.0, 22.0]


def test_get_frames_caps_at_16(silent_path: Path):
    frames = asyncio.run(get_frames(str(silent_path), count=50))
    assert len(frames) <= 16


def test_frames_disk_files_exist(silent_path: Path):
    frames = asyncio.run(get_frames(str(silent_path), count=3))
    assert frames
    # Each URI should map to an actual file on disk
    from videomemory.config import frame_dir

    for f in frames:
        # videomemory://frames/<vid>/<file>
        rest = f.frame_uri.removeprefix("videomemory://frames/")
        vid, fname = rest.split("/", 1)
        assert (frame_dir(vid) / fname).exists()
