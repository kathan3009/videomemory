"""Semantic memory graph: in-memory NetworkX view backed by SQLite."""

from __future__ import annotations

from pathlib import Path

import networkx as nx

from videomemory.storage import sqlite_db
from videomemory.types import Entity, Event, TemporalEdge


class SemanticMemoryGraph:
    def __init__(self, video_id: str) -> None:
        self.video_id = video_id
        self.g: nx.MultiDiGraph = nx.MultiDiGraph()
        self._entities: dict[str, Entity] = {}
        self._events: dict[str, Event] = {}

    def add_entity(self, e: Entity) -> None:
        self._entities[e.entity_id] = e
        self.g.add_node(e.entity_id, kind=e.kind, label=e.label)

    def add_event(self, ev: Event) -> None:
        self._events[ev.event_id] = ev
        self.g.add_node(ev.event_id, kind="event", verb=ev.verb, t_start=ev.t_start, t_end=ev.t_end)
        if ev.subject_entity_id:
            self.g.add_edge(ev.subject_entity_id, ev.event_id, relation="subject")
        if ev.object_entity_id:
            self.g.add_edge(ev.event_id, ev.object_entity_id, relation="object")

    def add_edge(self, edge: TemporalEdge) -> None:
        self.g.add_edge(edge.src_event_id, edge.dst_event_id, relation=edge.relation, delta=edge.delta_seconds)

    @classmethod
    async def load(cls, video_id: str, data_dir: Path | None = None) -> SemanticMemoryGraph:
        g = cls(video_id)
        ents = await sqlite_db.get_entities(video_id, data_dir)
        for e in ents:
            g.add_entity(e)
        evts = await sqlite_db.get_events(video_id, data_dir)
        for ev in evts:
            g.add_event(ev)
        return g

    def events_after(self, anchor_event_id: str) -> list[Event]:
        anchor = self._events.get(anchor_event_id)
        if not anchor:
            return []
        return sorted(
            (e for e in self._events.values() if e.t_start >= anchor.t_end),
            key=lambda e: e.t_start,
        )

    def events_before(self, anchor_event_id: str) -> list[Event]:
        anchor = self._events.get(anchor_event_id)
        if not anchor:
            return []
        return sorted(
            (e for e in self._events.values() if e.t_end <= anchor.t_start),
            key=lambda e: e.t_start,
            reverse=True,
        )

    def all_events(self) -> list[Event]:
        return sorted(self._events.values(), key=lambda e: e.t_start)

    def all_entities(self) -> list[Entity]:
        return list(self._entities.values())
