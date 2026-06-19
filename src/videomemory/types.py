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


class VisualFrame(BaseModel):
    """One query-relevant frame chosen by the visual funnel."""

    timestamp_seconds: float
    timestamp_human: str
    deep_link: str
    frame_uri: str
    score: float            # CLIP cosine to the query (visual relevance)


class VisualAnalysis(BaseModel):
    """Result of the visual-understanding funnel for one (video, question)."""

    video_id: str
    source: str
    question: str
    duration: float
    indexed_frames: int     # distinct frames in the visual index after dedup
    candidates_scanned: int # raw candidates sampled before dedup
    packing: str            # "contact_sheet" | "separate"
    sheet_uri: str | None = None      # one labeled grid image (contact_sheet mode)
    frames: list[VisualFrame] = Field(default_factory=list)
    guidance: str = ""      # how Claude should read the returned image(s)


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
