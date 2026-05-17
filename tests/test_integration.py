"""Integration tests using TTS-narrated fixtures (no network)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from videomemory.library import list_videos
from videomemory.search import search, skip
from videomemory.understand import understand


def test_ingest_tutorial_produces_windows(tutorial_ingested):
    assert tutorial_ingested.video_id.startswith("f_")
    assert tutorial_ingested.duration > 5


def test_skip_returns_transcript_mode_on_audio_rich_video(tutorial_ingested, tutorial_path):
    r = asyncio.run(skip(str(tutorial_path), "where do they install Tailwind?"))
    assert r.mode == "transcript", f"expected transcript mode on audio-rich video, got {r.mode}"
    assert r.confidence >= 0.30
    assert "tailwind" in r.transcript_excerpt.lower()
    assert r.timestamp_human is not None
    assert r.deep_link is not None
    assert len(r.frames) == 1  # one frame at the hit timestamp


def test_skip_finds_tailwind_section(tutorial_ingested, tutorial_path):
    r = asyncio.run(skip(str(tutorial_path), "where do they install Tailwind?"))
    assert r.mode == "transcript"
    # Tailwind segment is the first one
    # (start is implicit via timestamp_human; transcript_excerpt is the proof)
    assert "tailwind" in r.transcript_excerpt.lower()


def test_skip_finds_oauth_section(tutorial_ingested, tutorial_path):
    r = asyncio.run(skip(str(tutorial_path), "what authentication did they use?"))
    assert r.mode == "transcript"
    text = r.transcript_excerpt.lower()
    assert "oauth" in text or "jwt" in text


def test_skip_finds_docker_section(tutorial_ingested, tutorial_path):
    r = asyncio.run(skip(str(tutorial_path), "how is this deployed?"))
    assert r.mode == "transcript"
    text = r.transcript_excerpt.lower()
    assert "docker" in text or "compose" in text


def test_skip_falls_back_to_visual_on_silent_video(silent_path):
    """The key fix — for a silent visual video, skip auto-returns frames so
    the agent can look at them with its own vision instead of giving up."""
    r = asyncio.run(skip(str(silent_path), "what colour is the second panel?"))
    assert r.mode == "visual", f"expected visual mode on silent video, got {r.mode}: {r.note}"
    assert len(r.frames) >= 3, f"expected at least 3 frames, got {len(r.frames)}"
    assert all(f.frame_uri.startswith("videomemory://frames/") for f in r.frames)
    assert "sparse" in r.note.lower() or "no confident" in r.note.lower()


def test_cross_video_search_finds_correct_video(tutorial_ingested, science_ingested):
    hits = search("photosynthesis converts carbon dioxide", top_k=3)
    assert hits
    top = hits[0]
    assert top.video_id == science_ingested.video_id
    assert "photosynth" in top.transcript_excerpt.lower() or "glucose" in top.transcript_excerpt.lower()


def test_understand_returns_bullets_and_chapters(tutorial_ingested, tutorial_path):
    s = asyncio.run(understand(str(tutorial_path)))
    assert s.bullets, "expected non-empty bullets"
    assert s.chapters, "expected non-empty chapters"
    assert s.full_transcript_chars > 0
    flat = " ".join(c.transcript_excerpt.lower() for c in s.chapters)
    assert "tailwind" in flat or "oauth" in flat or "docker" in flat


def test_skip_is_idempotent(tutorial_ingested, tutorial_path):
    pre = list_videos()
    r = asyncio.run(skip(str(tutorial_path), "Tailwind install"))
    post = list_videos()
    assert r.mode in ("transcript", "visual")
    assert len(pre) == len(post), "ingest should not have created a duplicate video"
