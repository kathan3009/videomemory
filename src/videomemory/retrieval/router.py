"""Query router: temporal / OCR / visual / semantic + multimodal fusion."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from videomemory.config import get_settings
from videomemory.embeddings.bge import cosine, embed_text, embed_texts
from videomemory.retrieval.fuse import rrf
from videomemory.retrieval.store_helpers import (
    chunk_collection,
    load_chunks,
    load_keyframe_index,
)
from videomemory.retrieval.temporal_resolve import (
    best_anchor_chunk,
    chunks_relative_to,
    detect_anchor,
)
from videomemory.storage.artifacts import ArtifactPaths
from videomemory.types import FrameRef, KeyframeAnnotation, SemanticChunk
from videomemory.vector.qdrant_store import get_store

log = logging.getLogger(__name__)

OBJECT_LIKE_RE = re.compile(r"\b(show|find|frames? with|scenes? containing|images? of)\b", re.I)
OCR_HINT_RE = re.compile(r"\b(slides?|text|mentioning|reads?|that says?)\b", re.I)


def _similarity_fn(query: str, docs: list[str]) -> list[float]:
    qv = embed_text(query)
    dvs = embed_texts(docs)
    return [cosine(qv, dv) for dv in dvs]


def _ocr_search(chunks: list[SemanticChunk], query: str) -> list[tuple[str, float]]:
    q = query.lower().strip()
    # Strip quotes if present
    quoted = re.findall(r'"([^"]+)"', query)
    needles = [s.lower() for s in quoted] or [q]
    scored: list[tuple[str, float]] = []
    for c in chunks:
        flat = " ".join(c.ocr_excerpts).lower()
        score = 0.0
        for needle in needles:
            if needle in flat:
                score += 1.0
            else:
                # token overlap fallback
                tokens = needle.split()
                hits = sum(1 for t in tokens if len(t) > 2 and t in flat)
                if tokens:
                    score += hits / len(tokens)
        if score > 0:
            scored.append((c.chunk_id, score))
    scored.sort(key=lambda kv: -kv[1])
    return scored


def _semantic_search(qdrant, video_id: str, query: str, top_k: int) -> list[tuple[str, float]]:
    qv = embed_text(query)
    hits = qdrant.search(chunk_collection(video_id), qv, top_k=top_k)
    return [(h.id, h.score) for h in hits]


def _visual_search(
    query: str,
    keyframes: list[KeyframeAnnotation],
    top_k: int,
    use_clip: bool = True,
) -> list[tuple[str, float, FrameRef]]:
    """Score keyframes against the query using CLIP image embeddings + object/tag overlap."""
    if not keyframes:
        return []
    out: list[tuple[str, float, FrameRef]] = []

    q_lower = query.lower()
    q_tokens = {t for t in re.findall(r"\w+", q_lower) if len(t) > 2}

    clip_scores: list[float] = []
    if use_clip:
        embs = [k.image_embedding or [] for k in keyframes]
        if any(embs):
            try:
                from videomemory.vision.clip_tags import score_query_against_frames

                clip_scores = score_query_against_frames(query, embs)
            except Exception as exc:
                log.warning("CLIP score failed: %s", exc)
                clip_scores = [0.0] * len(keyframes)
        else:
            clip_scores = [0.0] * len(keyframes)
    else:
        clip_scores = [0.0] * len(keyframes)

    for k, clip_score in zip(keyframes, clip_scores, strict=True):
        tag_score = 0.0
        for tag, conf in k.clip_tags:
            tag_tokens = set(re.findall(r"\w+", tag.lower()))
            if tag_tokens & q_tokens:
                tag_score = max(tag_score, conf)
        obj_score = 0.0
        for obj in k.objects:
            if obj.lower() in q_lower or any(t in obj.lower() for t in q_tokens):
                obj_score = max(obj_score, 0.8)
        ocr_score = 0.0
        flat_ocr = " ".join(k.ocr_text).lower()
        for needle in q_tokens:
            if needle in flat_ocr:
                ocr_score = max(ocr_score, 0.6)

        score = 0.6 * float(clip_score) + 0.2 * tag_score + 0.15 * obj_score + 0.05 * ocr_score
        why_parts: list[str] = []
        if clip_score > 0.2:
            why_parts.append(f"CLIP {float(clip_score):.2f}")
        if tag_score > 0:
            why_parts.append(f"tag {tag_score:.2f}")
        if obj_score > 0:
            why_parts.append("object match")
        if ocr_score > 0:
            why_parts.append("OCR match")
        why = ", ".join(why_parts) or "weak match"

        ref = FrameRef(
            frame_path=k.frame_path,
            timestamp=k.timestamp,
            scene_id=k.scene_id,
            why=why,
            score=score,
        )
        out.append((k.frame_path, score, ref))
    out.sort(key=lambda t: -t[1])
    return out[:top_k]


def retrieve_chunks(
    video_id: str,
    query: str,
    data_dir: Path,
    top_k: int = 5,
    modalities: list[str] | None = None,
) -> list[SemanticChunk]:
    """Multimodal chunk retrieval with optional temporal anchor resolution."""
    chunks = load_chunks(video_id, data_dir)
    if not chunks:
        return []

    settings = get_settings()
    qdrant_path = ArtifactPaths(data_dir=data_dir, video_id=video_id).root / "qdrant_local"

    # Temporal anchor handling
    anchor = detect_anchor(query)
    if anchor:
        anchor_chunk = best_anchor_chunk(anchor.anchor_phrase, chunks, _similarity_fn)
        if anchor_chunk:
            related = chunks_relative_to(chunks, anchor_chunk, anchor.relation)
            if related:
                # Within the related slice, re-rank by semantic similarity to the original query
                if modalities is None or "semantic" in modalities or "transcript" in modalities:
                    scored = _similarity_fn(query, [c.summary + " " + c.transcript_excerpt[:400] for c in related])
                    paired = sorted(zip(related, scored, strict=True), key=lambda kv: -kv[1])
                    out: list[SemanticChunk] = []
                    for c, s in paired[:top_k]:
                        c.score = float(s)
                        out.append(c)
                    return out
                return related[:top_k]

    # No anchor → multimodal fusion
    modalities = modalities or ["semantic", "transcript", "ocr"]

    rankings: list[list[str]] = []
    weights: list[float] = []
    by_id = {c.chunk_id: c for c in chunks}

    if "semantic" in modalities:
        sem_hits: list[tuple[str, float]] = []
        try:
            with get_store(
                qdrant_url=settings.qdrant_url,
                local_path=qdrant_path if settings.qdrant_in_memory else None,
            ) as qdrant:
                sem_hits = _semantic_search(qdrant, video_id, query, top_k=top_k * 3)
        except Exception as exc:
            log.debug("qdrant unavailable, using local cosine fallback: %s", exc)
        if not sem_hits:
            sem_hits = [
                (c.chunk_id, cosine(embed_text(query), c.embedding or [0.0]))
                for c in chunks
                if c.embedding
            ]
            sem_hits.sort(key=lambda kv: -kv[1])
        rankings.append([cid for cid, _ in sem_hits[: top_k * 3]])
        weights.append(0.4)

    if "transcript" in modalities:
        scored = _similarity_fn(query, [c.transcript_excerpt[:800] or c.summary for c in chunks])
        ranked = sorted(zip(chunks, scored, strict=True), key=lambda kv: -kv[1])
        rankings.append([c.chunk_id for c, _ in ranked[: top_k * 3]])
        weights.append(0.3)

    if "ocr" in modalities:
        rankings.append([cid for cid, _ in _ocr_search(chunks, query)[: top_k * 3]])
        weights.append(0.2)

    fused = rrf(rankings, weights=weights)
    out: list[SemanticChunk] = []
    for cid, score in fused[:top_k]:
        if cid in by_id:
            c = by_id[cid]
            c.score = score
            out.append(c)
    return out


def retrieve_frames(
    video_id: str,
    query: str | None,
    data_dir: Path,
    limit: int = 8,
    at_time: float | None = None,
    time_range: tuple[float, float] | None = None,
) -> list[FrameRef]:
    keyframes = load_keyframe_index(video_id, data_dir)
    if not keyframes:
        return []

    if at_time is not None:
        # Return the nearest keyframe
        sorted_kf = sorted(keyframes, key=lambda k: abs(k.timestamp - at_time))
        ref = sorted_kf[0]
        return [
            FrameRef(
                frame_path=ref.frame_path,
                timestamp=ref.timestamp,
                scene_id=ref.scene_id,
                why=f"closest to t={at_time:.1f}s",
                score=1.0,
            )
        ]

    if time_range is not None:
        a, b = time_range
        return [
            FrameRef(
                frame_path=k.frame_path,
                timestamp=k.timestamp,
                scene_id=k.scene_id,
                why=f"in range [{a:.1f},{b:.1f}]",
                score=1.0,
            )
            for k in keyframes
            if a <= k.timestamp <= b
        ][:limit]

    if not query:
        # Default: return the first `limit` keyframes
        return [
            FrameRef(
                frame_path=k.frame_path,
                timestamp=k.timestamp,
                scene_id=k.scene_id,
                why="default sample",
                score=0.0,
            )
            for k in keyframes[:limit]
        ]

    visual = _visual_search(query, keyframes, top_k=limit)
    return [v[2] for v in visual]
