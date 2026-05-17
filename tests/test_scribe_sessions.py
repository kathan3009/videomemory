"""scribe session clustering: deterministic boundary rules."""

from __future__ import annotations

from datetime import datetime, timedelta

from videomemory.scribe.sessions import cluster
from videomemory.scribe.types import CaptureContext, Frame


def _frame(i: int, app: str, title: str, base: datetime, gap_s: float = 2.0) -> Frame:
    ts = base + timedelta(seconds=i * gap_s)
    return Frame(
        frame_id=f"f{i}",
        captured_at=ts,
        frame_path=f"/tmp/{i}.jpg",
        ocr_text="",
        context=CaptureContext(app=app, title=title),
    )


def test_consecutive_same_app_clusters_into_one_session():
    base = datetime(2026, 5, 18, 9, 0, 0)
    frames = [_frame(i, "VSCode", "videomemory — scribe.py", base) for i in range(20)]
    sessions = cluster(frames, min_session_seconds=5)
    assert len(sessions) == 1
    assert sessions[0].app == "VSCode"


def test_app_switch_creates_new_session():
    base = datetime(2026, 5, 18, 9, 0, 0)
    frames = (
        [_frame(i, "VSCode", "scribe.py", base) for i in range(15)]
        + [_frame(15 + j, "Safari", "Hacker News", base) for j in range(15)]
    )
    sessions = cluster(frames, min_session_seconds=5)
    assert len(sessions) == 2
    assert sessions[0].app == "VSCode"
    assert sessions[1].app == "Safari"


def test_long_gap_creates_new_session():
    base = datetime(2026, 5, 18, 9, 0, 0)
    a = [_frame(i, "VSCode", "scribe.py", base) for i in range(10)]
    # Big gap (5 min) before next frame
    later = datetime(2026, 5, 18, 9, 30, 0)
    b = [_frame(j, "VSCode", "scribe.py", later) for j in range(10)]
    sessions = cluster(a + b, min_session_seconds=5)
    assert len(sessions) == 2


def test_short_glance_below_threshold_is_dropped():
    base = datetime(2026, 5, 18, 9, 0, 0)
    # 2 frames total, 2-second gap = 2s duration (below 20s default)
    frames = [_frame(i, "Finder", "Downloads", base) for i in range(2)]
    sessions = cluster(frames)  # min defaults to 20s
    assert sessions == []
