"""Shared Pydantic schemas for the entire VideoMemory pipeline.

Every module in `videomemory.*` imports from here. Schemas are stable contracts —
changes go through a migration in `storage/sqlite_db.py`.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Pipeline metadata
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class Job(BaseModel):
    job_id: str
    video_id: str
    source: str
    status: JobStatus = JobStatus.PENDING
    stages_done: list[str] = Field(default_factory=list)
    current_stage: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    artifacts_dir: str = ""

    def mark_stage_done(self, stage: str) -> None:
        if stage not in self.stages_done:
            self.stages_done.append(stage)
        self.updated_at = datetime.utcnow()


class VideoMetadata(BaseModel):
    video_id: str
    source: str
    title: str | None = None
    duration: float = 0.0          # seconds
    fps: float = 0.0
    width: int = 0
    height: int = 0
    codec: str | None = None
    audio_codec: str | None = None
    file_size: int | None = None
    file_path: str | None = None   # local path after download
    sha256: str | None = None
    ingested_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Audio / transcription
# ---------------------------------------------------------------------------


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    speaker: str = "speaker_unknown"
    confidence: float | None = None


# ---------------------------------------------------------------------------
# Vision per-keyframe
# ---------------------------------------------------------------------------


class KeyframeAnnotation(BaseModel):
    frame_path: str
    timestamp: float
    scene_id: str
    ocr_text: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    clip_tags: list[tuple[str, float]] = Field(default_factory=list)
    caption: str = ""
    image_embedding: list[float] | None = None


# ---------------------------------------------------------------------------
# Scene (the time-bounded multimodal unit)
# ---------------------------------------------------------------------------


class Scene(BaseModel):
    scene_id: str
    video_id: str
    index: int
    start: float
    end: float
    keyframe_paths: list[str] = Field(default_factory=list)
    keyframe_timestamps: list[float] = Field(default_factory=list)
    transcript_text: str = ""
    transcript_segments: list[TranscriptSegment] = Field(default_factory=list)
    ocr_text: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    clip_tags: list[tuple[str, float]] = Field(default_factory=list)
    caption: str = ""
    entity_ids: list[str] = Field(default_factory=list)
    embedding: list[float] | None = None

    @property
    def duration(self) -> float:
        return max(self.end - self.start, 0.0)


# ---------------------------------------------------------------------------
# Entity / Event / Edge
# ---------------------------------------------------------------------------


EntityKind = Literal["person", "object", "topic", "location"]


class Entity(BaseModel):
    entity_id: str
    video_id: str
    kind: EntityKind
    label: str
    first_seen: float
    last_seen: float
    scene_ids: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)


class Event(BaseModel):
    event_id: str
    video_id: str
    scene_id: str
    t_start: float
    t_end: float
    verb: str
    subject_entity_id: str | None = None
    object_entity_id: str | None = None
    object_label: str | None = None
    description: str
    embedding: list[float] | None = None
    confidence: float = 1.0


TemporalRelation = Literal["before", "after", "during", "overlaps", "causes"]


class TemporalEdge(BaseModel):
    src_event_id: str
    dst_event_id: str
    relation: TemporalRelation
    delta_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Frame recall
# ---------------------------------------------------------------------------


class FrameRef(BaseModel):
    frame_path: str
    timestamp: float
    scene_id: str
    why: str = ""
    score: float = 0.0


# ---------------------------------------------------------------------------
# Semantic chunk (the retrieval primitive)
# ---------------------------------------------------------------------------


class SemanticChunk(BaseModel):
    chunk_id: str
    video_id: str
    start: float
    end: float
    scene_ids: list[str]
    summary: str
    transcript_excerpt: str = ""
    key_events: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    ocr_excerpts: list[str] = Field(default_factory=list)
    keyframe_refs: list[FrameRef] = Field(default_factory=list)
    embedding: list[float] | None = None
    score: float = 0.0  # populated by retrieval


# ---------------------------------------------------------------------------
# Query result
# ---------------------------------------------------------------------------


class QueryResult(BaseModel):
    video_id: str
    query: str
    answer: str | None = None
    chunks: list[SemanticChunk] = Field(default_factory=list)
    frames: list[FrameRef] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    token_estimate: int = 0
    strategy: str = "fuse"
    debug: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Timeline (lightweight for UI / agents)
# ---------------------------------------------------------------------------


class TimelineEntry(BaseModel):
    start: float
    end: float
    summary: str
    entities: list[str] = Field(default_factory=list)
    scene_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class PipelineConfig(BaseModel):
    """User-tunable pipeline parameters. Loaded from yaml or env."""

    target_fps: float = 1.0
    scene_threshold: float = 27.0
    max_keyframes_per_scene: int = 3
    whisper_model: str = "small"
    whisper_language: str | None = None
    clip_model: str = "ViT-B-32"
    clip_pretrained: str = "openai"
    use_yolo: bool = False
    yolo_model: str = "yolov8n.pt"
    use_diarization: bool = False
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    max_chunk_seconds: float = 90.0
    chunk_similarity_threshold: float = 0.85
    ocr_enabled: bool = True
    vector_backend: Literal["qdrant", "memory"] = "qdrant"
    qdrant_url: str = "http://localhost:6333"
    device: Literal["auto", "cpu", "mps", "cuda"] = "auto"
