"""Shared Pydantic schemas for the v1 surface."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Video(BaseModel):
    video_id: str           # e.g. "yt_BM70fDqUo3c" or "f_<sha256[:16]>"
    source: str             # original URL or path
    title: str | None = None
    duration: float = 0.0
    added_at: datetime = Field(default_factory=datetime.utcnow)
    file_path: str | None = None


class Window(BaseModel):
    """A ~30s slice of a transcript with one embedding."""

    window_id: str          # f"{video_id}__{idx:05d}"
    video_id: str
    idx: int
    start: float
    end: float
    text: str


class Hit(BaseModel):
    """A single retrieval result, ready to hand to an MCP client."""

    video_id: str
    title: str | None = None
    source: str
    start: float
    end: float
    timestamp_human: str    # "14:23"
    deep_link: str          # youtube.com/watch?v=...&t=863s OR file:// path with #t=
    transcript_excerpt: str
    score: float
    frame_uri: str | None = None  # videomemory://frames/<video_id>/<ts>.jpg


class Frame(BaseModel):
    """A standalone keyframe (not tied to a transcript hit)."""

    video_id: str
    timestamp_seconds: float
    timestamp_human: str
    deep_link: str
    frame_uri: str


class SkipResult(BaseModel):
    """Result of `skip(url, question)` — always usable, regardless of audio richness.

    - mode='transcript': we found a confident transcript match.
      `deep_link`, `timestamp_human`, `transcript_excerpt` are populated.
      `frames` carries one frame at the hit timestamp.

    - mode='visual': audio was too sparse / no confident match. `frames`
      carries N sampled keyframes covering the video; the agent should look
      at them with its own vision to answer.
    """

    mode: str                          # "transcript" | "visual"
    video_id: str
    title: str | None = None
    source: str
    confidence: float                  # 0..1; below ~0.30 triggers visual fallback
    note: str                          # short hint for the agent
    timestamp_human: str | None = None
    deep_link: str | None = None
    transcript_excerpt: str = ""
    frames: list[Frame] = Field(default_factory=list)


class Summary(BaseModel):
    """Used by `understand()`."""

    video_id: str
    title: str | None
    duration: float
    source: str
    bullets: list[str]      # 4–8 one-line takeaways
    chapters: list[Hit]     # auto-detected chapter markers
    full_transcript_chars: int
    full_transcript: str    # may be truncated if huge; the URL points to artifacts/full
