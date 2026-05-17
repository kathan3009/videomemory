"""Entity extraction & tracking from scenes + transcript.

Light, deterministic implementation:
- Person entities: pulled from diarization speakers, otherwise a single `speaker_unknown`.
- Object entities: union of YOLO labels across scenes, capped.
- Topic entities: noun-phrase candidates from transcript text, filtered by frequency.
- Location entities: a very small CLIP-derived heuristic.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter

from videomemory.types import Entity, Scene, TranscriptSegment

_STOP = set("""
a an the of to in for and or with on by at is are was were be been being it this that these those
i you he she they we us our your their my mine ours yours its his hers some any all most more less
many much few several no not also as if then than from into out about over under between among about
""".split())

_TOPIC_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_-]{2,}(?:\s+[A-Za-z][A-Za-z0-9_-]{2,}){0,2}\b")


def _topic_candidates(text: str) -> list[str]:
    cands: list[str] = []
    for m in _TOPIC_RE.finditer(text):
        phrase = m.group(0).strip()
        words = [w for w in phrase.split() if w.lower() not in _STOP]
        if not words:
            continue
        if not any(w[0].isupper() or w.isupper() for w in words):
            # Heuristic: topics tend to capitalise (Kubernetes, OAuth, Docker)
            if len(words) > 1:
                cands.append(" ".join(words).lower())
            continue
        cands.append(" ".join(words))
    return cands


def extract_entities(
    video_id: str,
    scenes: list[Scene],
    transcript: list[TranscriptSegment],
) -> list[Entity]:
    entities: dict[str, Entity] = {}

    # 1. Person entities from diarization
    speakers: dict[str, list[TranscriptSegment]] = {}
    for seg in transcript:
        speakers.setdefault(seg.speaker, []).append(seg)
    for speaker, segs in speakers.items():
        if not segs:
            continue
        eid = f"person_{speaker}"
        entities[eid] = Entity(
            entity_id=eid,
            video_id=video_id,
            kind="person",
            label=speaker,
            first_seen=min(s.start for s in segs),
            last_seen=max(s.end for s in segs),
            scene_ids=[],
        )

    # 2. Object entities
    obj_first: dict[str, float] = {}
    obj_last: dict[str, float] = {}
    obj_scenes: dict[str, list[str]] = {}
    for sc in scenes:
        for o in sc.objects:
            obj_first.setdefault(o, sc.start)
            obj_last[o] = sc.end
            obj_scenes.setdefault(o, []).append(sc.scene_id)
    for label, first in obj_first.items():
        eid = f"object_{re.sub(r'[^a-z0-9]+', '_', label.lower()).strip('_') or uuid.uuid4().hex[:6]}"
        entities[eid] = Entity(
            entity_id=eid,
            video_id=video_id,
            kind="object",
            label=label,
            first_seen=first,
            last_seen=obj_last[label],
            scene_ids=obj_scenes[label],
        )

    # 3. Topic entities — frequent capitalised noun phrases across transcript + OCR
    counts: Counter[str] = Counter()
    occurrences: dict[str, list[float]] = {}
    for seg in transcript:
        for cand in _topic_candidates(seg.text):
            counts[cand] += 1
            occurrences.setdefault(cand, []).append((seg.start + seg.end) / 2.0)
    for sc in scenes:
        for line in sc.ocr_text:
            for cand in _topic_candidates(line):
                counts[cand] += 1
                occurrences.setdefault(cand, []).append((sc.start + sc.end) / 2.0)
    for label, freq in counts.most_common(30):
        if freq < 1:
            continue
        eid = f"topic_{re.sub(r'[^a-z0-9]+', '_', label.lower()).strip('_')}"
        times = occurrences.get(label, [])
        if not times:
            continue
        entities[eid] = Entity(
            entity_id=eid,
            video_id=video_id,
            kind="topic",
            label=label,
            first_seen=min(times),
            last_seen=max(times),
            scene_ids=[],
        )

    # Attach scene_ids for topics by scanning scene transcripts
    for sc in scenes:
        text = sc.transcript_text.lower()
        for ent in entities.values():
            if ent.kind != "topic":
                continue
            if ent.label.lower() in text:
                if sc.scene_id not in ent.scene_ids:
                    ent.scene_ids.append(sc.scene_id)

    # Back-fill scene_ids for persons via per-scene segments
    for sc in scenes:
        for seg in sc.transcript_segments:
            eid = f"person_{seg.speaker}"
            if eid in entities and sc.scene_id not in entities[eid].scene_ids:
                entities[eid].scene_ids.append(sc.scene_id)

    return list(entities.values())


def link_entities_to_scenes(scenes: list[Scene], entities: list[Entity]) -> None:
    """Mutate `scenes` in place to set `entity_ids` based on overlap rules."""
    by_id = {e.entity_id: e for e in entities}
    for sc in scenes:
        ids: set[str] = set()
        for ent in entities:
            if ent.kind == "person" and sc.scene_id in ent.scene_ids:
                ids.add(ent.entity_id)
            elif ent.kind == "object" and ent.label in sc.objects:
                ids.add(ent.entity_id)
            elif ent.kind == "topic" and ent.label.lower() in sc.transcript_text.lower():
                ids.add(ent.entity_id)
        sc.entity_ids = sorted(ids)
    _ = by_id
