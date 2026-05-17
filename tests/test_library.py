"""Library CRUD + bundle export/import."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from videomemory.library import (
    Video,
    Window,
    delete_video,
    export_bundle,
    get_video,
    has_windows,
    import_bundle,
    insert_windows,
    iter_windows_for_video,
    list_videos,
    stats,
    upsert_video,
)


def _video(vid: str, source: str) -> Video:
    return Video(
        video_id=vid, source=source, title=f"title-{vid}", duration=60.0,
        added_at=datetime.utcnow(), file_path=None,
    )


def test_upsert_get_list_roundtrip():
    v = _video("yt_abc12345678", "https://youtu.be/abc12345678")
    upsert_video(v)
    got = get_video(v.video_id)
    assert got is not None
    assert got.video_id == v.video_id
    assert got.title == v.title
    assert any(x.video_id == v.video_id for x in list_videos())


def test_windows_insert_and_iterate():
    v = _video("yt_def12345678", "https://youtu.be/def12345678")
    upsert_video(v)
    windows = [
        Window(window_id=f"{v.video_id}__00000", video_id=v.video_id, idx=0, start=0, end=30, text="hello"),
        Window(window_id=f"{v.video_id}__00001", video_id=v.video_id, idx=1, start=30, end=60, text="world"),
    ]
    insert_windows(windows, [[0.1] * 384, [0.2] * 384])
    assert has_windows(v.video_id)
    rows = iter_windows_for_video(v.video_id)
    assert len(rows) == 2
    assert rows[0][1].shape == (384,)


def test_bundle_export_import(tmp_path: Path):
    v = _video("yt_ghi12345678", "https://youtu.be/ghi12345678")
    upsert_video(v)
    insert_windows(
        [Window(window_id=f"{v.video_id}__00000", video_id=v.video_id, idx=0, start=0, end=30, text="bundle test")],
        [[0.5] * 384],
    )
    out = tmp_path / "bundle.sqlite"
    export_bundle(out)
    assert out.exists()

    # Clear library, then import the bundle
    delete_video(v.video_id)
    assert get_video(v.video_id) is None

    n = import_bundle(out)
    assert n >= 1
    assert get_video(v.video_id) is not None
    rows = iter_windows_for_video(v.video_id)
    assert rows  # vectors preserved


def test_stats_returns_counts():
    s = stats()
    assert "videos" in s and "windows" in s
