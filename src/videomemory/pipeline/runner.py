"""Async pipeline orchestrator with on-disk stage caching for resumability.

Stages:
    1. resolve_source     → download + ffprobe
    2. detect_scenes      → scenes.json with empty payloads
    3. extract_keyframes  → frames/*.jpg per scene
    4. transcribe_audio   → transcript.json
    5. analyze_vision     → vision.json (CLIP tags, OCR, objects, captions, embeddings)
    6. assemble_scenes    → updated scenes.json with multimodal payloads + embeddings
    7. build_memory       → memory.json (entities + events + edges)
    8. build_chunks       → chunks.json
    9. index_vectors      → Qdrant collection

Each stage writes a marker file under <video>/.stages/<name>.done so a resume
can skip completed steps.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from videomemory.audio.transcribe import transcribe_wav
from videomemory.config import get_settings, load_pipeline_config, select_device
from videomemory.embeddings.bge import dim_for, embed_texts
from videomemory.ingest.source import resolve_source
from videomemory.memory.chunks import build_chunks
from videomemory.memory.entities import extract_entities, link_entities_to_scenes
from videomemory.memory.events import extract_events
from videomemory.memory.temporal import build_edges
from videomemory.retrieval.store_helpers import chunk_collection
from videomemory.storage import sqlite_db
from videomemory.storage.artifacts import ArtifactPaths
from videomemory.types import (
    Job,
    JobStatus,
    KeyframeAnnotation,
    Scene,
    TranscriptSegment,
)
from videomemory.vector.qdrant_store import get_store
from videomemory.video.extract import extract_audio_wav, select_keyframes_for_scene
from videomemory.video.scenes import detect_scenes
from videomemory.vision.caption import compose_caption
from videomemory.vision.clip_tags import embed_images, score_tags
from videomemory.vision.ocr import ocr_frame

log = logging.getLogger(__name__)


def _stage_done(paths: ArtifactPaths, name: str) -> bool:
    return paths.stage_marker(name).exists()


def _mark_done(paths: ArtifactPaths, name: str) -> None:
    paths.stage_marker(name).write_text(datetime.utcnow().isoformat())


async def run_ingest(
    source: str,
    data_dir: Path,
    config_path: Path | None = None,
) -> Job:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_pipeline_config(config_path)
    device = select_device(cfg.device)

    job_id = str(uuid.uuid4())
    job = Job(job_id=job_id, video_id="pending", source=source)
    await sqlite_db.upsert_job(job, data_dir)

    # 1. resolve source
    # If this is a re-ingest of the same source whose metadata is cached, reuse it.
    from videomemory.ingest.hash import video_id_for_source
    from videomemory.ingest.source import _is_url  # type: ignore[attr-defined]

    cached_meta = None
    if not _is_url(source):
        # Compute the deterministic video_id from the file content and check cache.
        local_probe = Path(source).expanduser().resolve()
        if local_probe.exists():
            probe_id = video_id_for_source(source, file_path=local_probe)
            probe_paths = ArtifactPaths(data_dir=data_dir, video_id=probe_id)
            if probe_paths.stage_marker("resolve_source").exists() and probe_paths.metadata_json.exists():
                from videomemory.types import VideoMetadata

                cached_meta = VideoMetadata.model_validate_json(probe_paths.metadata_json.read_text())
                paths = probe_paths
                meta = cached_meta
                log.info("[%s] using cached metadata", meta.video_id)
    if cached_meta is None:
        meta, paths = await resolve_source(source, data_dir)
        _mark_done(paths, "resolve_source")
    job.video_id = meta.video_id
    job.artifacts_dir = str(paths.root)
    job.status = JobStatus.RUNNING
    job.current_stage = "resolve_source"
    await sqlite_db.upsert_job(job, data_dir)
    await sqlite_db.upsert_video(meta, data_dir)
    log.info("[%s] resolved %s (%.1fs)", meta.video_id, meta.title, meta.duration)

    source_path = Path(meta.file_path or paths.find_source() or paths.source_path("mp4"))

    # 2. scenes
    if not _stage_done(paths, "detect_scenes"):
        log.info("[%s] detecting scenes...", meta.video_id)
        scene_times = await asyncio.to_thread(detect_scenes, source_path, cfg.scene_threshold)
        scenes: list[Scene] = [
            Scene(
                scene_id=str(uuid.uuid4()),
                video_id=meta.video_id,
                index=i,
                start=s,
                end=e,
            )
            for i, (s, e) in enumerate(scene_times)
        ]
        paths.scenes_json.write_text(json.dumps([sc.model_dump(mode="json") for sc in scenes], indent=2))
        _mark_done(paths, "detect_scenes")
        job.mark_stage_done("detect_scenes")
        await sqlite_db.upsert_job(job, data_dir)
    else:
        scenes = [Scene.model_validate(s) for s in json.loads(paths.scenes_json.read_text())]
    log.info("[%s] %d scenes", meta.video_id, len(scenes))

    # 3. keyframes per scene
    if not _stage_done(paths, "extract_keyframes"):
        log.info("[%s] extracting keyframes...", meta.video_id)
        for sc in scenes:
            picked = await asyncio.to_thread(
                select_keyframes_for_scene,
                source_path,
                sc.start,
                sc.end,
                paths.frames_dir,
                cfg.max_keyframes_per_scene,
            )
            sc.keyframe_paths = [str(p) for p, _ in picked]
            sc.keyframe_timestamps = [t for _, t in picked]
        paths.scenes_json.write_text(json.dumps([sc.model_dump(mode="json") for sc in scenes], indent=2))
        _mark_done(paths, "extract_keyframes")
        job.mark_stage_done("extract_keyframes")
        await sqlite_db.upsert_job(job, data_dir)
    else:
        scenes = [Scene.model_validate(s) for s in json.loads(paths.scenes_json.read_text())]

    # 4. transcribe audio
    transcript: list[TranscriptSegment] = []
    transcript_path = paths.transcript_json
    if not _stage_done(paths, "transcribe_audio"):
        wav_path = paths.root / "audio.wav"
        try:
            await extract_audio_wav(source_path, wav_path)
            log.info("[%s] transcribing...", meta.video_id)
            transcript = await asyncio.to_thread(
                transcribe_wav,
                wav_path,
                cfg.whisper_model,
                cfg.whisper_language,
                device,
            )
        except Exception as exc:
            log.warning("[%s] transcription failed: %s", meta.video_id, exc)
            transcript = []
        transcript_path.write_text(
            json.dumps([s.model_dump(mode="json") for s in transcript], indent=2)
        )
        _mark_done(paths, "transcribe_audio")
        job.mark_stage_done("transcribe_audio")
        await sqlite_db.upsert_job(job, data_dir)
    else:
        transcript = [TranscriptSegment.model_validate(t) for t in json.loads(transcript_path.read_text())]
    log.info("[%s] %d transcript segments", meta.video_id, len(transcript))

    # 5. vision: per-keyframe OCR, CLIP tags, image embeddings, optional YOLO
    if not _stage_done(paths, "analyze_vision"):
        log.info("[%s] analysing vision per keyframe...", meta.video_id)
        all_frames: list[KeyframeAnnotation] = []
        for sc in scenes:
            paths_list = [Path(p) for p in sc.keyframe_paths]
            if not paths_list:
                continue
            tags_per_frame = await asyncio.to_thread(
                score_tags, paths_list, top_k=5, model_name=cfg.clip_model, pretrained=cfg.clip_pretrained
            )
            embs = await asyncio.to_thread(
                embed_images, paths_list, model_name=cfg.clip_model, pretrained=cfg.clip_pretrained
            )
            ocrs = [await asyncio.to_thread(ocr_frame, p) for p in paths_list] if cfg.ocr_enabled else [[] for _ in paths_list]
            objects_per_frame: list[list[str]]
            if cfg.use_yolo:
                from videomemory.vision.detect import detect_frame

                objects_per_frame = [await asyncio.to_thread(detect_frame, p, cfg.yolo_model) for p in paths_list]
            else:
                objects_per_frame = [[] for _ in paths_list]
            for i, fp in enumerate(paths_list):
                all_frames.append(
                    KeyframeAnnotation(
                        frame_path=str(fp),
                        timestamp=sc.keyframe_timestamps[i] if i < len(sc.keyframe_timestamps) else sc.start,
                        scene_id=sc.scene_id,
                        ocr_text=ocrs[i],
                        objects=objects_per_frame[i],
                        clip_tags=tags_per_frame[i] if i < len(tags_per_frame) else [],
                        image_embedding=embs[i] if i < len(embs) else None,
                    )
                )
        paths.vision_json.write_text(
            json.dumps([k.model_dump(mode="json") for k in all_frames], indent=2)
        )
        _mark_done(paths, "analyze_vision")
        job.mark_stage_done("analyze_vision")
        await sqlite_db.upsert_job(job, data_dir)
    else:
        all_frames = [
            KeyframeAnnotation.model_validate(k) for k in json.loads(paths.vision_json.read_text())
        ]

    # 6. assemble scenes — attach transcript window + vision payloads + scene embedding
    log.info("[%s] assembling scenes...", meta.video_id)
    frames_by_scene: dict[str, list[KeyframeAnnotation]] = {}
    for kf in all_frames:
        frames_by_scene.setdefault(kf.scene_id, []).append(kf)

    scene_texts_for_embed: list[str] = []
    for sc in scenes:
        segs = [s for s in transcript if not (s.end < sc.start or s.start > sc.end)]
        sc.transcript_segments = segs
        sc.transcript_text = " ".join(s.text for s in segs).strip()
        kfs = frames_by_scene.get(sc.scene_id, [])
        sc.ocr_text = sorted({t for kf in kfs for t in kf.ocr_text})
        sc.objects = sorted({o for kf in kfs for o in kf.objects})
        all_tags: list[tuple[str, float]] = []
        for kf in kfs:
            all_tags.extend(kf.clip_tags)
        all_tags.sort(key=lambda kv: -kv[1])
        sc.clip_tags = all_tags[:5]
        sc.caption = compose_caption(sc.objects, sc.ocr_text, sc.clip_tags, sc.transcript_text[:200])
        scene_texts_for_embed.append(
            f"{sc.caption}\n{sc.transcript_text[:400]}\nobjects: {', '.join(sc.objects)}\n"
            f"ocr: {' | '.join(sc.ocr_text[:5])}"
        )

    scene_embeddings = await asyncio.to_thread(embed_texts, scene_texts_for_embed, cfg.embedding_model)
    for sc, vec in zip(scenes, scene_embeddings, strict=True):
        sc.embedding = vec

    # 7. memory — entities, events, edges
    log.info("[%s] building temporal memory...", meta.video_id)
    entities = extract_entities(meta.video_id, scenes, transcript)
    link_entities_to_scenes(scenes, entities)
    events = extract_events(scenes, entities)
    edges = build_edges(events)
    paths.memory_json.write_text(
        json.dumps(
            {
                "entities": [e.model_dump(mode="json") for e in entities],
                "events": [e.model_dump(mode="json") for e in events],
                "edges": [e.model_dump(mode="json") for e in edges],
            },
            indent=2,
        )
    )
    await sqlite_db.replace_scenes(meta.video_id, scenes, data_dir)
    await sqlite_db.replace_entities(meta.video_id, entities, data_dir)
    await sqlite_db.replace_events(meta.video_id, events, data_dir)
    await sqlite_db.replace_temporal_edges(meta.video_id, edges, data_dir)
    paths.scenes_json.write_text(json.dumps([sc.model_dump(mode="json") for sc in scenes], indent=2))
    _mark_done(paths, "build_memory")

    # 8. chunks
    log.info("[%s] building semantic chunks...", meta.video_id)
    chunks = build_chunks(
        scenes,
        events,
        entities,
        similarity_threshold=cfg.chunk_similarity_threshold,
        max_seconds=cfg.max_chunk_seconds,
    )
    chunk_texts = [
        f"{c.summary}\n{c.transcript_excerpt[:600]}\nocr: {' | '.join(c.ocr_excerpts[:4])}"
        for c in chunks
    ]
    chunk_embeddings = await asyncio.to_thread(embed_texts, chunk_texts, cfg.embedding_model)
    for c, v in zip(chunks, chunk_embeddings, strict=True):
        c.embedding = v
    paths.chunks_json.write_text(json.dumps([c.model_dump(mode="json") for c in chunks], indent=2))
    _mark_done(paths, "build_chunks")

    # 9. vector index
    log.info("[%s] indexing %d chunks in Qdrant...", meta.video_id, len(chunks))
    settings = get_settings()
    local_qdrant = (paths.root / "qdrant_local") if settings.qdrant_in_memory else None
    dim = dim_for(cfg.embedding_model)
    coll = chunk_collection(meta.video_id)
    with get_store(qdrant_url=settings.qdrant_url, local_path=local_qdrant) as store:
        store.ensure_collection(coll, dim)
        store.upsert(
            coll,
            ids=[c.chunk_id for c in chunks],
            vectors=[c.embedding or [0.0] * dim for c in chunks],
            payloads=[
                {
                    "video_id": c.video_id,
                    "start": c.start,
                    "end": c.end,
                    "summary": c.summary[:300],
                    "entities": c.entities[:8],
                }
                for c in chunks
            ],
        )
    _mark_done(paths, "index_vectors")
    job.mark_stage_done("index_vectors")

    job.status = JobStatus.COMPLETED
    job.current_stage = None
    await sqlite_db.upsert_job(job, data_dir)
    await sqlite_db.set_video_status(meta.video_id, "completed", data_dir)
    log.info("[%s] ingest complete", meta.video_id)
    return job


# Convenience for resume
async def resume(job_id: str, data_dir: Path) -> Job:
    job = await sqlite_db.get_job(job_id, data_dir)
    if not job:
        raise ValueError(f"job not found: {job_id}")
    return await run_ingest(job.source, data_dir=data_dir)
