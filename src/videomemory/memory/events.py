"""Atomic temporal events extracted from each scene.

Strategy (deterministic, no LLM required):
- Verb hints: scan the scene transcript for trigger verbs and map to a small,
  canonical verb vocabulary. Object is the noun phrase that follows or the
  dominant topic entity present in the scene.
- Visual fallbacks: if there is no usable transcript, infer from CLIP tags
  (e.g. "a person enters" if the dominant tag implies arrival).
- Merging: consecutive scenes with the same (verb, object) are merged into a
  single event spanning their union.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable

from videomemory.types import Entity, Event, Scene

VERB_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("explains", re.compile(r"\b(explain|explains|explained|describe|describes|describ\w+|talks? about|discuss\w*)\b", re.I)),
    ("introduces", re.compile(r"\b(introduce|introduces|introduced|present\w*|cover\w+|today (we'?ll|i'?ll) )\b", re.I)),
    ("shows", re.compile(r"\b(show|shows|showed|demo\w*|here is|here'?s|look at)\b", re.I)),
    ("references", re.compile(r"\b(refer\w+|mention\w+|cite\w*|recall)\b", re.I)),
    ("argues", re.compile(r"\b(argue\w*|disagree\w*|dispute\w*|object\w+ to)\b", re.I)),
    ("questions", re.compile(r"\b(ask\w*|question\w*|wonder\w*|why does|how does)\b", re.I)),
    ("compares", re.compile(r"\b(compare\w*|versus|vs\.?|trade-?off)\b", re.I)),
]

VISUAL_VERB_HINTS: dict[str, str] = {
    "a person": "appears",
    "a group of people": "gather",
    "a speaker presenting": "presents",
    "a whiteboard with writing": "writes",
    "a slide with text": "shows",
    "code on a screen": "shows",
    "an architecture diagram": "shows",
    "a chart or graph": "shows",
    "an office room": "appears",
    "outdoors": "appears",
}


def _scene_topic_objects(scene: Scene, entities: list[Entity]) -> list[Entity]:
    """Return topic + person entities likely to be the 'object' of an event."""
    sids = {scene.scene_id}
    candidates = [e for e in entities if e.kind == "topic" and sids.intersection(e.scene_ids)]
    if candidates:
        return candidates
    return [e for e in entities if e.kind == "person" and sids.intersection(e.scene_ids)]


def _primary_actor(scene: Scene, entities: list[Entity]) -> Entity | None:
    persons = [e for e in entities if e.kind == "person" and scene.scene_id in e.scene_ids]
    if persons:
        return persons[0]
    return None


def _trigger_event(scene: Scene, entities: list[Entity]) -> list[Event]:
    out: list[Event] = []
    text = scene.transcript_text.strip()
    actor = _primary_actor(scene, entities)
    actor_id = actor.entity_id if actor else None
    topics = _scene_topic_objects(scene, entities)

    triggered = False
    for verb, pat in VERB_PATTERNS:
        if pat.search(text):
            triggered = True
            if topics:
                for topic in topics[:2]:
                    out.append(
                        Event(
                            event_id=str(uuid.uuid4()),
                            video_id=scene.video_id,
                            scene_id=scene.scene_id,
                            t_start=scene.start,
                            t_end=scene.end,
                            verb=verb,
                            subject_entity_id=actor_id,
                            object_entity_id=topic.entity_id,
                            object_label=topic.label,
                            description=f"{actor.label if actor else 'someone'} {verb} {topic.label}",
                        )
                    )
            else:
                # No topic: use first ~6 words after the verb as object_label
                m = pat.search(text)
                start_idx = m.end() if m else 0
                tail = text[start_idx : start_idx + 80].strip(" .,:;!?-")
                tail_clean = " ".join(tail.split()[:6])
                out.append(
                    Event(
                        event_id=str(uuid.uuid4()),
                        video_id=scene.video_id,
                        scene_id=scene.scene_id,
                        t_start=scene.start,
                        t_end=scene.end,
                        verb=verb,
                        subject_entity_id=actor_id,
                        object_entity_id=None,
                        object_label=tail_clean or None,
                        description=(
                            f"{actor.label if actor else 'someone'} {verb} {tail_clean}".strip()
                        ),
                    )
                )
            break  # one verb per scene from transcript

    if not triggered and scene.clip_tags:
        tag = scene.clip_tags[0][0]
        verb = VISUAL_VERB_HINTS.get(tag, "appears")
        desc = f"{tag} {verb}" if not actor else f"{actor.label} {verb} ({tag})"
        out.append(
            Event(
                event_id=str(uuid.uuid4()),
                video_id=scene.video_id,
                scene_id=scene.scene_id,
                t_start=scene.start,
                t_end=scene.end,
                verb=verb,
                subject_entity_id=actor_id,
                object_label=tag,
                description=desc,
                confidence=0.6,
            )
        )

    # OCR-derived events (e.g. slide content)
    if scene.ocr_text:
        ocr_join = " ".join(scene.ocr_text).strip()
        if ocr_join:
            out.append(
                Event(
                    event_id=str(uuid.uuid4()),
                    video_id=scene.video_id,
                    scene_id=scene.scene_id,
                    t_start=scene.start,
                    t_end=scene.end,
                    verb="shows",
                    subject_entity_id=actor_id,
                    object_label=f"text: {ocr_join[:80]}",
                    description=f"on-screen text: “{ocr_join[:120]}”",
                    confidence=0.7,
                )
            )

    return out


def extract_events(scenes: list[Scene], entities: list[Entity]) -> list[Event]:
    all_events: list[Event] = []
    for sc in scenes:
        all_events.extend(_trigger_event(sc, entities))
    all_events.sort(key=lambda e: (e.t_start, e.t_end))
    return _merge_consecutive(all_events)


def _merge_consecutive(events: Iterable[Event]) -> list[Event]:
    """Merge consecutive duplicate (verb, object_label) events."""
    merged: list[Event] = []
    for ev in events:
        if merged:
            last = merged[-1]
            same = (
                last.verb == ev.verb
                and (last.object_entity_id == ev.object_entity_id)
                and (last.object_label == ev.object_label)
                and ev.t_start - last.t_end <= 2.0
            )
            if same:
                last.t_end = max(last.t_end, ev.t_end)
                continue
        merged.append(ev)
    return merged
