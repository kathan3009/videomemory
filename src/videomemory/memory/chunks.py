"""Build SemanticChunks from scenes + events + entities.

Boundaries are hybrid: start with scene cuts, then greedily merge consecutive
scenes whose `embedding`s are cosine-similar AND whose entity sets overlap,
capping chunk duration at `max_chunk_seconds`.
"""

from __future__ import annotations

import uuid

import numpy as np

from videomemory.types import Entity, Event, FrameRef, Scene, SemanticChunk


def _cos(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    av = np.asarray(a, dtype=np.float32)
    bv = np.asarray(b, dtype=np.float32)
    na = np.linalg.norm(av) + 1e-9
    nb = np.linalg.norm(bv) + 1e-9
    return float((av @ bv) / (na * nb))


def _summary_for(scenes_window: list[Scene], events: list[Event]) -> str:
    """Compose a chunk summary that prefers concrete content (OCR, transcript) over
    generic visual fallbacks like 'appears'.
    """
    # 1. If the chunk has events with OCR content ("shows ...") use the most informative one.
    shows = [e for e in events if e.verb == "shows" and e.object_label]
    if shows:
        return shows[0].description.strip()[:240]

    # 2. Otherwise pick an event whose description isn't a generic visual fallback.
    concrete = [e for e in events if e.verb not in {"appears", "gather"} and e.description]
    if concrete:
        return concrete[0].description.strip()[:240]

    # 3. Fall back to the richest scene caption in the window.
    captions = sorted((s.caption.strip() for s in scenes_window if s.caption), key=len, reverse=True)
    if captions:
        return captions[0][:240]

    # 4. Last resort.
    return f"scene segment {scenes_window[0].start:.1f}–{scenes_window[-1].end:.1f}s"


def build_chunks(
    scenes: list[Scene],
    events: list[Event],
    entities: list[Entity],
    *,
    similarity_threshold: float = 0.85,
    max_seconds: float = 90.0,
    max_keyframes_per_chunk: int = 3,
) -> list[SemanticChunk]:
    if not scenes:
        return []

    # Index events by scene_id for cheap lookup
    events_by_scene: dict[str, list[Event]] = {}
    for ev in events:
        events_by_scene.setdefault(ev.scene_id, []).append(ev)

    chunks: list[SemanticChunk] = []
    cur: list[Scene] = [scenes[0]]
    for nxt in scenes[1:]:
        ref = cur[-1]
        merged_duration = nxt.end - cur[0].start
        sim = _cos(ref.embedding, nxt.embedding)
        ent_overlap = bool(set(ref.entity_ids) & set(nxt.entity_ids))
        same_topic = sim >= similarity_threshold and ent_overlap
        if same_topic and merged_duration <= max_seconds:
            cur.append(nxt)
        else:
            chunks.append(_finalize_chunk(cur, events_by_scene, max_keyframes_per_chunk))
            cur = [nxt]
    chunks.append(_finalize_chunk(cur, events_by_scene, max_keyframes_per_chunk))
    return chunks


def _finalize_chunk(
    window: list[Scene],
    events_by_scene: dict[str, list[Event]],
    max_frames: int,
) -> SemanticChunk:
    video_id = window[0].video_id
    scene_ids = [s.scene_id for s in window]
    transcripts = " ".join(s.transcript_text for s in window if s.transcript_text).strip()
    ocr_excerpts: list[str] = []
    for s in window:
        ocr_excerpts.extend(s.ocr_text)

    entities: set[str] = set()
    for s in window:
        entities.update(s.entity_ids)

    chunk_events: list[Event] = []
    for sid in scene_ids:
        chunk_events.extend(events_by_scene.get(sid, []))
    chunk_events.sort(key=lambda e: e.t_start)

    # Pick keyframes: one per scene up to max_frames
    frames: list[FrameRef] = []
    for s in window:
        if not s.keyframe_paths:
            continue
        idx = 0
        frames.append(
            FrameRef(
                frame_path=s.keyframe_paths[idx],
                timestamp=s.keyframe_timestamps[idx] if s.keyframe_timestamps else s.start,
                scene_id=s.scene_id,
                why="scene representative",
                score=1.0,
            )
        )
        if len(frames) >= max_frames:
            break

    summary = _summary_for(window, chunk_events)
    transcript_excerpt = transcripts[:1200]
    return SemanticChunk(
        chunk_id=str(uuid.uuid4()),
        video_id=video_id,
        start=window[0].start,
        end=window[-1].end,
        scene_ids=scene_ids,
        summary=summary,
        transcript_excerpt=transcript_excerpt,
        key_events=[ev.event_id for ev in chunk_events][:8],
        entities=sorted(entities),
        ocr_excerpts=ocr_excerpts[:8],
        keyframe_refs=frames,
    )
