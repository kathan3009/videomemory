"""Shot / scene-boundary detection — frame-accurate cut points per video.

Uses ffmpeg's built-in `scene` score (no extra deps): decode the video, select
the frames where the inter-frame difference exceeds a threshold, and read each
selected frame's true `pts_time` from `showinfo`. Those timestamps are the shot
boundaries — frame-accurate, because they're the actual PTS of the first frame
of each new shot. Shots are the `[boundary, next_boundary)` intervals, the first
starting at 0 and the last ending at the video duration.

This is the editor's tool: it gives a real cut list / EDL skeleton (in/out per
shot + a representative keyframe), where `look` answers visual questions.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

from videomemory.config import min_shot_seconds, scene_threshold
from videomemory.ingest import deep_link, fmt_time  # type: ignore
from videomemory.types import Shot, ShotList
from videomemory.visual_index import _ensure_video  # resolves/downloads + duration

_PTS_RE = re.compile(r"pts_time:([0-9.]+)")


async def _scene_cut_times(local: Path, threshold: float) -> list[float]:
    """Return the timestamps (s) where a new shot begins, via ffmpeg `scene`."""
    if not shutil.which("ffmpeg"):
        return []
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "info",
        "-i", str(local),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-an", "-f", "null", "-",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    times = sorted(float(m) for m in _PTS_RE.findall(err.decode("utf-8", "replace")))
    return times


def _merge_boundaries(cuts: list[float], duration: float, min_shot: float) -> list[float]:
    """[0, ...kept cuts..., duration] with no interval shorter than `min_shot`."""
    kept: list[float] = []
    last = 0.0
    for c in cuts:
        if c - last >= min_shot and duration - c >= min_shot:
            kept.append(c)
            last = c
    return [0.0, *kept, duration]


async def detect_shots(
    url: str,
    *,
    threshold: float | None = None,
    min_shot: float | None = None,
    with_frames: bool = True,
) -> ShotList:
    """Detect frame-accurate shots in a video. Returns an editable cut list."""
    from videomemory.frames import _frame_uri, extract_frames

    thr = scene_threshold() if threshold is None else threshold
    mins = min_shot_seconds() if min_shot is None else min_shot

    vid, source, local, duration = await _ensure_video(url)
    cuts = await _scene_cut_times(local, thr)
    bounds = _merge_boundaries(cuts, duration, mins)

    shots: list[Shot] = []
    for i in range(len(bounds) - 1):
        start, end = bounds[i], bounds[i + 1]
        mid = round((start + end) / 2, 3)
        shots.append(
            Shot(
                index=i + 1,
                start_seconds=round(start, 3),
                end_seconds=round(end, 3),
                duration_seconds=round(end - start, 3),
                start_human=fmt_time(start),
                end_human=fmt_time(end),
                mid_seconds=mid,
                deep_link=deep_link(source, start),
            )
        )

    if with_frames and shots:
        extracted = await extract_frames(vid, source, [s.mid_seconds for s in shots])
        by_t = {round(t, 3): p for t, p in extracted}
        for s in shots:
            if by_t.get(s.mid_seconds) is not None:
                s.frame_uri = _frame_uri(vid, s.mid_seconds)

    return ShotList(video_id=vid, source=source, duration=duration, threshold=thr, shots=shots)


__all__ = ["detect_shots"]
