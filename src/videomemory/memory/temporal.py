"""Derive temporal edges (before/after/during/overlaps) deterministically from event times."""

from __future__ import annotations

from videomemory.types import Event, TemporalEdge


def build_edges(events: list[Event]) -> list[TemporalEdge]:
    edges: list[TemporalEdge] = []
    sorted_events = sorted(events, key=lambda e: (e.t_start, e.t_end))
    for i, a in enumerate(sorted_events):
        for b in sorted_events[i + 1 :]:
            if b.t_start >= a.t_end:
                edges.append(
                    TemporalEdge(
                        src_event_id=a.event_id,
                        dst_event_id=b.event_id,
                        relation="after",
                        delta_seconds=b.t_start - a.t_end,
                    )
                )
                edges.append(
                    TemporalEdge(
                        src_event_id=b.event_id,
                        dst_event_id=a.event_id,
                        relation="before",
                        delta_seconds=a.t_end - b.t_start,
                    )
                )
            elif b.t_start < a.t_end <= b.t_end:
                edges.append(
                    TemporalEdge(
                        src_event_id=a.event_id,
                        dst_event_id=b.event_id,
                        relation="overlaps",
                        delta_seconds=b.t_start - a.t_start,
                    )
                )
            elif b.t_start >= a.t_start and b.t_end <= a.t_end:
                edges.append(
                    TemporalEdge(
                        src_event_id=b.event_id,
                        dst_event_id=a.event_id,
                        relation="during",
                        delta_seconds=b.t_start - a.t_start,
                    )
                )
            # Bound the edge fan-out for very long videos
            if len(edges) > 2000:
                return edges
    return edges
