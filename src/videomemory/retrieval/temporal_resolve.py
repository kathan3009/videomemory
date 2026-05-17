"""Resolve a temporal anchor phrase like 'after the OAuth discussion' into a time range."""

from __future__ import annotations

import re
from dataclasses import dataclass

from videomemory.types import Event, SemanticChunk

# "after X" anchors retrieval to chunks that follow X.  Note: "when" is NOT in this
# pattern — "when was X" is a direct question about X's time, not an anchor on X.
AFTER_RE = re.compile(r"\b(after|once|following|since)\s+(.+?)(?:\?|\.|$)", re.I)
BEFORE_RE = re.compile(r"\b(before|prior to|preceding|until|up to)\s+(.+?)(?:\?|\.|$)", re.I)
DURING_RE = re.compile(r"\b(during|while|throughout|in the middle of)\s+(.+?)(?:\?|\.|$)", re.I)


@dataclass
class TemporalAnchor:
    relation: str  # "after" | "before" | "during"
    anchor_phrase: str
    raw_query: str


def detect_anchor(query: str) -> TemporalAnchor | None:
    for rel, pat in (("after", AFTER_RE), ("before", BEFORE_RE), ("during", DURING_RE)):
        m = pat.search(query)
        if m:
            phrase = m.group(2).strip().strip(".?!")
            if phrase:
                return TemporalAnchor(relation=rel, anchor_phrase=phrase, raw_query=query)
    return None


def best_anchor_chunk(
    anchor_phrase: str,
    chunks: list[SemanticChunk],
    similarity_fn,
) -> SemanticChunk | None:
    """Use the provided embedding-based `similarity_fn(query, [docs]) -> [scores]` to pick the best chunk."""
    if not chunks:
        return None
    docs = [
        f"{c.summary}\n{c.transcript_excerpt[:400]}\n{' '.join(c.ocr_excerpts[:4])}"
        for c in chunks
    ]
    scores = similarity_fn(anchor_phrase, docs)
    if not scores:
        return None
    best_idx = max(range(len(scores)), key=lambda i: scores[i])
    return chunks[best_idx]


def chunks_relative_to(
    chunks: list[SemanticChunk],
    anchor: SemanticChunk,
    relation: str,
) -> list[SemanticChunk]:
    if relation == "after":
        return [c for c in chunks if c.start >= anchor.end and c.chunk_id != anchor.chunk_id]
    if relation == "before":
        return [c for c in chunks if c.end <= anchor.start and c.chunk_id != anchor.chunk_id]
    if relation == "during":
        return [
            c for c in chunks if c.start <= anchor.end and c.end >= anchor.start and c.chunk_id != anchor.chunk_id
        ]
    return []


def events_relative_to(events: list[Event], anchor_chunk: SemanticChunk, relation: str) -> list[Event]:
    if relation == "after":
        return sorted([e for e in events if e.t_start >= anchor_chunk.end], key=lambda e: e.t_start)
    if relation == "before":
        return sorted([e for e in events if e.t_end <= anchor_chunk.start], key=lambda e: e.t_start, reverse=True)
    if relation == "during":
        return sorted(
            [e for e in events if e.t_start <= anchor_chunk.end and e.t_end >= anchor_chunk.start],
            key=lambda e: e.t_start,
        )
    return []
