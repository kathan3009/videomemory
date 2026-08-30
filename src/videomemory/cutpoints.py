"""Frame-accurate cut suggestions for a take — motion × beat, layered.

This closes the "when exactly do I cut?" gap that `shots` (editorial cuts) and
`look` (which moment matters) leave open for raw continuous takes.

Two signals, combined:

  motion  — a per-frame luma-difference curve (ffmpeg `signalstats` YDIF). Local
            MINIMA = stable framing → good IN-points; local MAXIMA = camera/subject
            motion → good places to cut OUT (cut on motion hides the cut).
  beat    — the soundtrack's beat grid (librosa). Clip *durations* are snapped to a
            whole number of beats so every cut lands on the beat when laid down.

So: motion decides WHERE in the take to cut, the beat decides HOW LONG each cut
runs. Without a music track it degrades to motion + an even target length.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

import numpy as np

from videomemory.config import cut_motion_fps
from videomemory.ingest import deep_link, fmt_time  # type: ignore
from videomemory.types import CutPlan, CutSegment
from videomemory.visual_index import _ensure_video

_PTS_RE = re.compile(r"pts_time:([0-9.]+)")
_YDIF_RE = re.compile(r"YDIF=([0-9.]+)")


# ---------- motion curve -------------------------------------------------


async def _motion_curve(local: Path, fps: float) -> tuple[np.ndarray, np.ndarray]:
    """(times, ydif) — mean luma difference per sampled frame = motion magnitude."""
    if not shutil.which("ffmpeg"):
        return np.array([]), np.array([])
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "info",
        "-i", str(local),
        "-vf", f"fps={fps},signalstats,metadata=print:file=-",
        "-an", "-f", "null", "-",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    text = out.decode("utf-8", "replace")
    times = [float(m) for m in _PTS_RE.findall(text)]
    ydif = [float(m) for m in _YDIF_RE.findall(text)]
    n = min(len(times), len(ydif))
    return np.array(times[:n]), np.array(ydif[:n])


def _smooth(y: np.ndarray, w: int = 5) -> np.ndarray:
    if len(y) < w or w < 2:
        return y
    k = np.ones(w) / w
    return np.convolve(y, k, mode="same")


def _extrema(times: np.ndarray, y: np.ndarray) -> tuple[list[float], list[float]]:
    """(settle_times, peak_times) via prominence-filtered minima/maxima."""
    if len(y) < 3:
        return list(times), list(times)
    ys = _smooth(y)
    try:
        from scipy.signal import find_peaks

        prom = max(1e-6, float(np.std(ys)) * 0.5)
        peaks, _ = find_peaks(ys, prominence=prom)
        valleys, _ = find_peaks(-ys, prominence=prom)
        settle = [float(times[i]) for i in valleys]
        peak = [float(times[i]) for i in peaks]
    except Exception:  # scipy missing → coarse fallback
        settle, peak = [], []
        for i in range(1, len(ys) - 1):
            if ys[i] <= ys[i - 1] and ys[i] <= ys[i + 1]:
                settle.append(float(times[i]))
            if ys[i] >= ys[i - 1] and ys[i] >= ys[i + 1]:
                peak.append(float(times[i]))
    if not settle:
        settle = [float(times[0])]
    return settle, peak


# ---------- beat grid ----------------------------------------------------


def beat_grid(music_path: str) -> tuple[float, float, list[float]] | None:
    """(bpm, beat_period_s, beat_times) from a music track, or None if unavailable."""
    try:
        import librosa
    except ImportError:
        return None
    p = Path(music_path)
    if not p.exists():
        return None
    try:
        y, sr = librosa.load(str(p), mono=True)
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
        bpm = float(np.atleast_1d(tempo)[0])
        if bpm <= 0:
            return None
        return bpm, 60.0 / bpm, [float(b) for b in beats]
    except Exception:
        return None


# ---------- planning -----------------------------------------------------


def _nearest(vals: list[float], target: float, lo: float, hi: float) -> float | None:
    cands = [v for v in vals if lo <= v <= hi]
    return min(cands, key=lambda v: abs(v - target)) if cands else None


def _plan_segments(
    duration: float,
    settles: list[float],
    peaks: list[float],
    *,
    beat_period: float | None,
    beats_per_cut: int,
    target_len: float,
) -> list[CutSegment]:
    clip_len = beat_period * beats_per_cut if beat_period else target_len
    clip_len = max(0.4, clip_len)
    tol = (beat_period or clip_len) * 0.5  # how far we'll move an out-point to hit a peak

    segs: list[CutSegment] = []
    cursor = 0.0
    i = 0
    while cursor < duration - 0.3 and i < 1000:
        i += 1
        in_pt = _nearest(settles, cursor, cursor, cursor + tol)
        in_kind = "settle" if in_pt is not None else ("start" if cursor == 0 else "carry")
        if in_pt is None:
            in_pt = cursor

        desired_out = in_pt + clip_len
        out_pt = _nearest(peaks, desired_out, desired_out - tol, desired_out + tol)
        out_kind = "motion_peak" if out_pt is not None else ("beat" if beat_period else "target")
        if out_pt is None:
            out_pt = desired_out

        if beat_period:  # snap duration to a whole number of beats (timeline alignment)
            n_beats = max(1, round((out_pt - in_pt) / beat_period))
            out_pt = in_pt + n_beats * beat_period
            beats = float(n_beats)
        else:
            beats = None

        out_pt = min(out_pt, duration)
        if out_pt - in_pt < 0.3:
            break
        segs.append(CutSegment(
            index=len(segs) + 1,
            in_seconds=round(in_pt, 3), out_seconds=round(out_pt, 3),
            duration_seconds=round(out_pt - in_pt, 3),
            in_human=fmt_time(in_pt), out_human=fmt_time(out_pt),
            in_kind=in_kind, out_kind=out_kind, beats=beats,
            deep_link="",  # filled by caller (needs source)
        ))
        cursor = out_pt
    return segs


async def suggest_cuts(
    url: str,
    *,
    music: str | None = None,
    beats_per_cut: int = 2,
    target_len: float = 2.0,
    with_frames: bool = True,
) -> CutPlan:
    """Frame-accurate cut plan for a take: motion picks where, beat picks how long."""
    from videomemory.frames import _frame_uri, extract_frames

    beats_per_cut = max(1, min(int(beats_per_cut), 16))
    target_len = max(0.25, min(float(target_len), 30.0))

    vid, source, local, duration = await _ensure_video(url)
    fps = cut_motion_fps()
    times, ydif = await _motion_curve(local, fps)
    settles, peaks = _extrema(times, ydif)

    grid = beat_grid(music) if music else None
    bpm = grid[0] if grid else None
    beat_period = grid[1] if grid else None

    segs = _plan_segments(
        duration, settles, peaks,
        beat_period=beat_period, beats_per_cut=beats_per_cut, target_len=target_len,
    )
    for s in segs:
        s.deep_link = deep_link(source, s.in_seconds)

    if with_frames and segs:
        extracted = await extract_frames(vid, source, [s.in_seconds for s in segs[:64]])
        have = {round(t, 3) for t, p in extracted if p is not None}
        for s in segs:
            if round(s.in_seconds, 3) in have:
                s.frame_uri = _frame_uri(vid, s.in_seconds)

    if grid:
        notes = f"beat-aligned to {bpm:.1f} BPM ({beat_period:.3f}s/beat); each cut = {beats_per_cut} beat(s), snapped to motion."
    elif music:
        notes = "music given but beat detection unavailable (need librosa); used motion + even target length."
    else:
        notes = f"no music supplied — motion-based cuts at ~{target_len:.1f}s. Pass music= for beat alignment."

    return CutPlan(
        video_id=vid, source=source, duration=duration,
        bpm=bpm, beat_period=beat_period, motion_fps=fps, segments=segs, notes=notes,
    )


__all__ = ["suggest_cuts", "beat_grid"]
