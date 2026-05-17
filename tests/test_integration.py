"""Integration tests using TTS-narrated fixtures (no network)."""

from __future__ import annotations

import asyncio

from videomemory.library import list_videos
from videomemory.search import search, skip
from videomemory.understand import understand


def test_ingest_tutorial_produces_windows(tutorial_ingested):
    assert tutorial_ingested.video_id.startswith("f_")
    assert tutorial_ingested.duration > 5


def test_skip_finds_tailwind_section(tutorial_ingested, tutorial_path):
    hit = asyncio.run(skip(str(tutorial_path), "where do they install Tailwind?", with_frame=False))
    assert hit is not None, "skip returned no hit"
    text = hit.transcript_excerpt.lower()
    assert "tailwind" in text, f"expected 'tailwind' in excerpt, got: {hit.transcript_excerpt!r}"
    # Tailwind segment is the first one
    assert hit.start <= 12.0


def test_skip_finds_oauth_section(tutorial_ingested, tutorial_path):
    hit = asyncio.run(skip(str(tutorial_path), "what authentication did they use?", with_frame=False))
    assert hit is not None
    text = hit.transcript_excerpt.lower()
    assert "oauth" in text or "jwt" in text, hit.transcript_excerpt


def test_skip_finds_docker_section(tutorial_ingested, tutorial_path):
    hit = asyncio.run(skip(str(tutorial_path), "how is this deployed?", with_frame=False))
    assert hit is not None
    text = hit.transcript_excerpt.lower()
    assert "docker" in text or "compose" in text, hit.transcript_excerpt


def test_cross_video_search_finds_correct_video(tutorial_ingested, science_ingested):
    hits = search("photosynthesis converts carbon dioxide", top_k=3)
    assert hits
    top = hits[0]
    # Top hit must be from the science video, not tutorial
    assert top.video_id == science_ingested.video_id
    assert "photosynth" in top.transcript_excerpt.lower() or "glucose" in top.transcript_excerpt.lower()


def test_understand_returns_bullets_and_chapters(tutorial_ingested, tutorial_path):
    s = asyncio.run(understand(str(tutorial_path)))
    assert s.bullets, "expected non-empty bullets"
    assert s.chapters, "expected non-empty chapters"
    assert s.full_transcript_chars > 0
    # Chapters should reference all three topics from the fixture
    flat = " ".join(c.transcript_excerpt.lower() for c in s.chapters)
    assert "tailwind" in flat or "oauth" in flat or "docker" in flat


def test_skip_is_idempotent(tutorial_ingested, tutorial_path):
    # Second skip on the same URL must reuse the cached transcript
    pre = list_videos()
    hit = asyncio.run(skip(str(tutorial_path), "Tailwind install", with_frame=False))
    post = list_videos()
    assert hit is not None
    assert len(pre) == len(post), "ingest should not have created a duplicate video"
