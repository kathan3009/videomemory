"""Unit tests for shot-boundary merging (pure logic, no ffmpeg needed)."""

from __future__ import annotations

from videomemory.shots import _merge_boundaries


def test_no_cuts_is_single_shot():
    assert _merge_boundaries([], 12.0, 0.6) == [0.0, 12.0]


def test_cuts_become_boundaries():
    assert _merge_boundaries([4.0, 8.0], 12.0, 0.6) == [0.0, 4.0, 8.0, 12.0]


def test_short_shots_are_merged():
    # 0.2s and 0.3s gaps are below min_shot=0.6 → dropped.
    assert _merge_boundaries([0.2, 0.5, 5.0], 10.0, 0.6) == [0.0, 5.0, 10.0]


def test_cut_too_close_to_end_is_dropped():
    # 9.9 leaves only 0.1s tail (< min_shot) → dropped.
    assert _merge_boundaries([5.0, 9.9], 10.0, 0.6) == [0.0, 5.0, 10.0]
