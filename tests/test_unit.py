"""Fast unit tests — no transcription, no ML, no network."""

from __future__ import annotations

import json
from pathlib import Path

from videomemory.deps import check
from videomemory.ingest import _is_url, _youtube_id, deep_link, fmt_time, video_id_for
from videomemory.youtube_history import parse_history_file


def test_youtube_id_extraction():
    assert _youtube_id("https://youtu.be/BM70fDqUo3c") == "BM70fDqUo3c"
    assert _youtube_id("https://www.youtube.com/watch?v=BM70fDqUo3c") == "BM70fDqUo3c"
    assert _youtube_id("https://www.youtube.com/watch?v=BM70fDqUo3c&t=42s") == "BM70fDqUo3c"
    assert _youtube_id("https://youtube.com/shorts/BM70fDqUo3c") == "BM70fDqUo3c"
    assert _youtube_id("https://example.com/video") is None
    assert _youtube_id("hello world") is None


def test_video_id_is_stable_per_source():
    assert video_id_for("https://youtu.be/BM70fDqUo3c") == "yt_BM70fDqUo3c"
    a = video_id_for("https://example.com/video")
    b = video_id_for("https://example.com/video")
    assert a == b
    assert a.startswith("u_")


def test_video_id_for_local_file(tmp_path: Path):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"\x00" * 128)
    vid = video_id_for(str(f), file_path=f)
    assert vid.startswith("f_")
    assert vid == video_id_for(str(f), file_path=f)  # deterministic


def test_deep_link_for_youtube():
    link = deep_link("https://youtu.be/BM70fDqUo3c", 73.4)
    assert link == "https://youtu.be/BM70fDqUo3c?t=73"


def test_deep_link_for_local_file():
    link = deep_link("/tmp/video.mp4", 73.4)
    assert link == "/tmp/video.mp4#t=73"


def test_fmt_time():
    assert fmt_time(0) == "00:00"
    assert fmt_time(73) == "01:13"
    assert fmt_time(3754) == "1:02:34"


def test_is_url():
    assert _is_url("https://youtu.be/x")
    assert _is_url("http://example.com")
    assert not _is_url("/tmp/v.mp4")
    assert not _is_url("video.mp4")


def test_deps_check_runs_without_crashing():
    rows = check()
    assert any(r.name == "ffmpeg" for r in rows)
    assert any(r.name == "yt-dlp" for r in rows)
    # we expect ffmpeg+yt-dlp installed on dev machines
    by_name = {r.name: r for r in rows}
    assert by_name["ffmpeg"].ok
    assert by_name["yt-dlp"].ok


def test_youtube_history_parser_json(tmp_path: Path):
    history = [
        {
            "header": "YouTube",
            "title": "Watched Some Talk",
            "titleUrl": "https://www.youtube.com/watch?v=BM70fDqUo3c",
        },
        {
            "header": "YouTube",
            "title": "Watched another",
            "titleUrl": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        },
        {
            "header": "YouTube",
            "title": "Already-seen",
            "titleUrl": "https://www.youtube.com/watch?v=BM70fDqUo3c",
        },
        {"header": "YouTube", "title": "no-url-here"},
    ]
    p = tmp_path / "watch-history.json"
    p.write_text(json.dumps(history))
    ids = parse_history_file(p)
    assert ids == ["BM70fDqUo3c", "dQw4w9WgXcQ"]


def test_youtube_history_parser_html(tmp_path: Path):
    html = """<html>
      Watched <a href="https://www.youtube.com/watch?v=BM70fDqUo3c">Some video</a>
      Watched <a href="https://youtu.be/dQw4w9WgXcQ">Another</a>
    </html>"""
    p = tmp_path / "watch-history.html"
    p.write_text(html)
    ids = parse_history_file(p)
    assert "BM70fDqUo3c" in ids
    assert "dQw4w9WgXcQ" in ids
