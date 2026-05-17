"""Helpers to load chunks and frame indices for a video."""

from __future__ import annotations

import json
from pathlib import Path

from videomemory.storage.artifacts import ArtifactPaths
from videomemory.types import KeyframeAnnotation, Scene, SemanticChunk


def load_chunks(video_id: str, data_dir: Path) -> list[SemanticChunk]:
    p = ArtifactPaths(data_dir=data_dir, video_id=video_id).chunks_json
    if not p.exists():
        return []
    data = json.loads(p.read_text())
    return [SemanticChunk.model_validate(c) for c in data]


def load_scenes_artifact(video_id: str, data_dir: Path) -> list[Scene]:
    p = ArtifactPaths(data_dir=data_dir, video_id=video_id).scenes_json
    if not p.exists():
        return []
    data = json.loads(p.read_text())
    return [Scene.model_validate(s) for s in data]


def load_keyframe_index(video_id: str, data_dir: Path) -> list[KeyframeAnnotation]:
    p = ArtifactPaths(data_dir=data_dir, video_id=video_id).vision_json
    if not p.exists():
        return []
    data = json.loads(p.read_text())
    return [KeyframeAnnotation.model_validate(k) for k in data]


def chunk_collection(video_id: str) -> str:
    return f"chunks__{video_id}"


def frames_collection(video_id: str) -> str:
    return f"frames__{video_id}"
