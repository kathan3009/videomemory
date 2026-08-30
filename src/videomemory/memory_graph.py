"""Tenant-scoped property graph for searches, videos, moments, and branched notes."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from videomemory.ingest import video_id_for
from videomemory.library import connect, get_video


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _digest(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:24]}"


def _upsert_node(node_id: str, node_type: str, label: str, properties: dict[str, Any] | None = None) -> None:
    now = _now()
    with connect() as con:
        con.execute(
            """INSERT INTO memory_nodes
               (node_id,node_type,label,properties_json,access_count,created_at,updated_at)
               VALUES (?,?,?,?,1,?,?)
               ON CONFLICT(node_id) DO UPDATE SET
                 label=excluded.label, properties_json=excluded.properties_json,
                 access_count=memory_nodes.access_count+1, updated_at=excluded.updated_at""",
            (node_id, node_type, label[:240], json.dumps(properties or {}), now, now),
        )
        con.commit()


def _connect(
    source_id: str,
    target_id: str,
    relation: str,
    properties: dict[str, Any] | None = None,
) -> None:
    now = _now()
    edge_id = _digest("edge", f"{source_id}|{target_id}|{relation}")
    with connect() as con:
        con.execute(
            """INSERT INTO memory_edges
               (edge_id,source_id,target_id,relation,weight,properties_json,created_at,updated_at)
               VALUES (?,?,?,?,1,?,?,?)
               ON CONFLICT(source_id,target_id,relation) DO UPDATE SET
                 weight=memory_edges.weight+1,
                 properties_json=excluded.properties_json,updated_at=excluded.updated_at""",
            (edge_id, source_id, target_id, relation, json.dumps(properties or {}), now, now),
        )
        con.commit()


def _walk_results(value: object) -> tuple[set[str], list[tuple[str, float]]]:
    videos: set[str] = set()
    moments: list[tuple[str, float]] = []

    def walk(item: object, inherited_video: str | None = None) -> None:
        if isinstance(item, dict):
            video_id = str(item.get("video_id") or inherited_video or "") or None
            if video_id:
                videos.add(video_id)
            moment = item.get("timestamp_seconds", item.get("start", item.get("in_seconds")))
            if video_id and isinstance(moment, int | float):
                moments.append((video_id, float(moment)))
            for child in item.values():
                walk(child, video_id)
        elif isinstance(item, list):
            for child in item:
                walk(child, inherited_video)

    walk(value)
    return videos, moments


def record_tool_memory(tool: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
    """Record a successful tool interaction and strengthen repeated relations."""
    if result.get("error"):
        return
    query = str(arguments.get("question") or arguments.get("query") or "").strip()
    source = str(arguments.get("url") or "").strip()
    videos, moments = _walk_results(result)
    if source:
        videos.add(video_id_for(source))

    query_id: str | None = None
    if query:
        normalized = " ".join(query.lower().split())
        query_id = _digest("qry", normalized)
        _upsert_node(query_id, "query", query, {"normalized": normalized, "last_tool": tool})

    for video_id in videos:
        video = get_video(video_id)
        label = (video.title if video else None) or (source[:160] if source else video_id)
        stored_source = video.source if video else source
        if stored_source and not stored_source.startswith(("http://", "https://")):
            stored_source = str(arguments.get("display_source") or f"upload://{video.title if video else video_id}")
        properties = {
            "source": stored_source,
            "duration": video.duration if video else 0,
            "title": video.title if video else None,
        }
        _upsert_node(video_id, "video", label, properties)
        if query_id:
            _connect(query_id, video_id, "REFERENCES", {"tool": tool})

    for video_id, seconds in moments[:40]:
        moment_id = _digest("mom", f"{video_id}|{round(seconds, 3)}")
        _upsert_node(moment_id, "moment", f"{seconds:.1f}s", {"video_id": video_id, "seconds": seconds})
        _connect(video_id, moment_id, "HAS_MOMENT", {"tool": tool})
        if query_id:
            _connect(query_id, moment_id, "ANSWERED_AT", {"tool": tool})

    with connect() as con:
        con.execute(
            """INSERT INTO memory_events
               (event_id,tool,query,video_id,moment_seconds,result_summary,created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                f"mev_{uuid.uuid4().hex}",
                tool,
                query or None,
                next(iter(videos), None),
                moments[0][1] if moments else None,
                json.dumps(result, default=str)[:1200],
                _now(),
            ),
        )
        con.commit()


def add_note(
    video_id: str,
    title: str,
    body: str,
    parent_note_id: str | None = None,
) -> dict[str, Any]:
    title = " ".join(title.strip().split())
    body = body.strip()
    if not get_video(video_id):
        raise ValueError("video not found in this memory")
    if not title or len(title) > 160:
        raise ValueError("note title must be between 1 and 160 characters")
    if not body or len(body) > 20_000:
        raise ValueError("note body must be between 1 and 20,000 characters")
    version = 1
    if parent_note_id:
        with connect() as con:
            parent = con.execute(
                "SELECT * FROM video_notes WHERE note_id=? AND video_id=?", (parent_note_id, video_id)
            ).fetchone()
        if not parent:
            raise ValueError("parent note was not found for this video")
        version = int(parent["version"]) + 1
    note_id = f"note_{uuid.uuid4().hex}"
    now = _now()
    with connect() as con:
        con.execute(
            """INSERT INTO video_notes
               (note_id,video_id,parent_note_id,title,body,version,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (note_id, video_id, parent_note_id, title, body, version, now, now),
        )
        con.commit()
    _upsert_node(note_id, "note", title, {"video_id": video_id, "body": body[:1000], "version": version})
    _connect(video_id, note_id, "HAS_NOTE", {"version": version})
    if parent_note_id:
        _connect(note_id, parent_note_id, "BRANCHES_FROM", {"version": version})
    return {
        "note_id": note_id,
        "video_id": video_id,
        "parent_note_id": parent_note_id,
        "title": title,
        "body": body,
        "version": version,
        "created_at": now,
        "updated_at": now,
    }


def list_notes(video_id: str | None = None) -> list[dict[str, Any]]:
    with connect() as con:
        if video_id:
            rows = con.execute(
                "SELECT * FROM video_notes WHERE video_id=? ORDER BY created_at DESC", (video_id,)
            ).fetchall()
        else:
            rows = con.execute("SELECT * FROM video_notes ORDER BY created_at DESC LIMIT 100").fetchall()
    return [dict(row) for row in rows]


def connect_artifact_memory(artifact: dict[str, Any]) -> None:
    """Project an artifact into the same relation graph as video memory."""
    artifact_id = str(artifact["artifact_id"])
    _upsert_node(
        artifact_id,
        "artifact",
        str(artifact.get("title") or artifact_id),
        {
            "kind": artifact.get("kind"),
            "locator": artifact.get("locator"),
            "project": artifact.get("project"),
            "version": artifact.get("version"),
            "summary": artifact.get("summary"),
            "access_instructions": artifact.get("access_instructions"),
        },
    )
    parent = artifact.get("parent_artifact_id")
    if parent:
        _connect(str(parent), artifact_id, "DERIVED_INTO", {"version": artifact.get("version")})
    project = str(artifact.get("project") or "").strip()
    if project:
        project_id = _digest("prj", project.lower())
        _upsert_node(project_id, "project", project, {"normalized": project.lower()})
        _connect(project_id, artifact_id, "CONTAINS_ARTIFACT", {"agent": artifact.get("agent")})


def graph_snapshot(limit: int = 80) -> dict[str, Any]:
    limit = max(10, min(limit, 200))
    with connect() as con:
        nodes = con.execute(
            """SELECT node_id,node_type,label,properties_json,access_count,created_at,updated_at
               FROM memory_nodes ORDER BY updated_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        node_ids = [row["node_id"] for row in nodes]
        if node_ids:
            placeholders = ",".join("?" for _ in node_ids)
            edges = con.execute(
                f"""SELECT edge_id,source_id,target_id,relation,weight,properties_json,updated_at
                    FROM memory_edges WHERE source_id IN ({placeholders}) AND target_id IN ({placeholders})
                    ORDER BY weight DESC, updated_at DESC LIMIT 300""",
                (*node_ids, *node_ids),
            ).fetchall()
        else:
            edges = []
        events = con.execute(
            "SELECT event_id,tool,query,video_id,moment_seconds,created_at FROM memory_events ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    return {
        "nodes": [{**dict(row), "properties": json.loads(row["properties_json"])} for row in nodes],
        "edges": [{**dict(row), "properties": json.loads(row["properties_json"])} for row in edges],
        "events": [dict(row) for row in events],
        "notes": list_notes(),
    }


def recall_context(query: str, limit: int = 12) -> dict[str, Any]:
    tokens = {token for token in re.findall(r"[a-z0-9]{2,}", query.lower())}
    graph = graph_snapshot(200)
    scored: list[tuple[float, dict[str, Any]]] = []
    for node in graph["nodes"]:
        haystack = f"{node['label']} {json.dumps(node['properties'])}".lower()
        overlap = sum(1 for token in tokens if token in haystack)
        if overlap:
            score = overlap * 10 + min(int(node["access_count"]), 20)
            scored.append((score, node))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [node for _, node in scored[: max(1, min(limit, 30))]]
    selected_ids = {node["node_id"] for node in selected}
    related_edges = [
        edge
        for edge in graph["edges"]
        if edge["source_id"] in selected_ids or edge["target_id"] in selected_ids
    ][:60]
    return {"query": query, "matches": selected, "relations": related_edges}


__all__ = [
    "add_note",
    "connect_artifact_memory",
    "graph_snapshot",
    "list_notes",
    "recall_context",
    "record_tool_memory",
]
