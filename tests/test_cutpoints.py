"""Unit tests for cut-planning logic (pure, no ffmpeg/librosa needed)."""

from __future__ import annotations

from videomemory.cutpoints import _nearest, _plan_segments


def test_nearest_within_window():
    assert _nearest([1.0, 5.0, 9.0], 4.5, 0.0, 10.0) == 5.0
    assert _nearest([1.0, 5.0, 9.0], 4.5, 4.6, 10.0) == 5.0
    assert _nearest([1.0], 4.5, 4.0, 5.0) is None  # nothing in window


def test_beat_aligned_durations_are_whole_beats():
    bp = 0.5
    segs = _plan_segments(
        10.0, settles=[0.0, 2.0, 4.0, 6.0, 8.0], peaks=[1.0, 3.0, 5.0, 7.0, 9.0],
        beat_period=bp, beats_per_cut=4, target_len=2.0,
    )
    assert segs, "should produce segments"
    for s in segs:
        # every cut spans a whole number of beats
        assert abs((s.duration_seconds / bp) - round(s.duration_seconds / bp)) < 1e-6
        assert s.beats == round(s.duration_seconds / bp)


def test_no_music_uses_target_len():
    segs = _plan_segments(
        9.0, settles=[0.0], peaks=[], beat_period=None, beats_per_cut=2, target_len=3.0,
    )
    assert segs
    assert all(s.beats is None for s in segs)
    # without peaks/beat snapping, cuts run the target length
    assert abs(segs[0].duration_seconds - 3.0) < 1e-6


def test_segments_are_contiguous_and_bounded():
    segs = _plan_segments(
        8.0, settles=[0.0], peaks=[], beat_period=0.5, beats_per_cut=2, target_len=2.0,
    )
    for a, b in zip(segs, segs[1:], strict=False):
        assert b.in_seconds == a.out_seconds  # no gaps/overlaps
    assert segs[-1].out_seconds <= 8.0
