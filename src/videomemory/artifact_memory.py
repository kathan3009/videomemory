"""Tenant-private memory for agent-created artifacts and their versions."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from videomemory.library import connect
from videomemory.memory_graph import connect_artifact_memory

KINDS = {"code", "document", "image", "video", "audio", "dataset", "design", "report", "other"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _public(row: Any, *, include_content: bool = False) -> dict[str, Any]:
    item = dict(row)
    item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
    if not include_content:
        item.pop("content", None)
    return item


def remember_artifact(
    *,
    title: str,
    locator: str,
    kind: str = "other",
    access_instructions: str = "",
    summary: str = "",
    content: str = "",
    project: str = "",
    agent: str = "",
    parent_artifact_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    title = " ".join(title.split())[:240]
    locator = locator.strip()[:2048]
    kind = kind.strip().lower()
    if not title or not locator:
        raise ValueError("artifact title and locator are required")
    if kind not in KINDS:
        raise ValueError(f"artifact kind must be one of: {', '.join(sorted(KINDS))}")
    if len(content) > 200_000:
        raise ValueError("artifact content is limited to 200,000 characters")
    if len(summary) > 10_000 or len(access_instructions) > 10_000:
        raise ValueError("artifact summary and access instructions are limited to 10,000 characters")
    project = " ".join(project.split())[:240]
    agent = " ".join(agent.split())[:120]
    metadata_json = json.dumps(metadata or {}, separators=(",", ":"), default=str)
    if len(metadata_json) > 50_000:
        raise ValueError("artifact metadata is too large")
    content_hash = _digest(content or f"{summary}|{locator}")
    now = _now()

    with connect() as con:
        existing = con.execute(
            "SELECT * FROM artifacts WHERE locator=? AND project=?", (locator, project)
        ).fetchone()
        if existing:
            artifact_id = existing["artifact_id"]
            version = int(existing["version"]) + (existing["content_hash"] != content_hash)
            created_at = existing["created_at"]
        else:
            artifact_id = f"art_{_digest(f'{project}|{locator}')[:20]}"
            version = 1
            created_at = now
        con.execute(
            """INSERT INTO artifacts
               (artifact_id,kind,title,locator,access_instructions,summary,content,content_hash,
                project,agent,parent_artifact_id,version,metadata_json,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(artifact_id) DO UPDATE SET
                 kind=excluded.kind,title=excluded.title,locator=excluded.locator,
                 access_instructions=excluded.access_instructions,summary=excluded.summary,
                 content=excluded.content,content_hash=excluded.content_hash,project=excluded.project,
                 agent=excluded.agent,parent_artifact_id=excluded.parent_artifact_id,
                 version=excluded.version,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at""",
            (
                artifact_id, kind, title, locator, access_instructions, summary, content, content_hash,
                project, agent, parent_artifact_id, version, metadata_json, created_at, now,
            ),
        )
        con.execute(
            """INSERT OR IGNORE INTO artifact_versions
               (version_id,artifact_id,version,content_hash,summary,content,locator,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (f"av_{uuid.uuid4().hex}", artifact_id, version, content_hash, summary, content, locator, now),
        )
        con.commit()
        row = con.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
    assert row is not None
    item = _public(row, include_content=True)
    connect_artifact_memory(item)
    return item


def artifact_memory(
    query: str = "", *, artifact_id: str | None = None, limit: int = 20, include_content: bool = False
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 50))
    with connect() as con:
        if artifact_id:
            row = con.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
            if not row:
                raise ValueError("artifact not found")
            versions = con.execute(
                "SELECT * FROM artifact_versions WHERE artifact_id=? ORDER BY version DESC", (artifact_id,)
            ).fetchall()
            return {
                "artifact": _public(row, include_content=include_content),
                "versions": [
                    dict(version) if include_content else {k: v for k, v in dict(version).items() if k != "content"}
                    for version in versions
                ],
            }
        terms = " ".join(query.split())
        if terms:
            like = f"%{terms}%"
            rows = con.execute(
                """SELECT * FROM artifacts WHERE title LIKE ? OR summary LIKE ? OR content LIKE ?
                   OR locator LIKE ? OR project LIKE ? ORDER BY updated_at DESC LIMIT ?""",
                (like, like, like, like, like, limit),
            ).fetchall()
        else:
            rows = con.execute("SELECT * FROM artifacts ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return {"artifacts": [_public(row, include_content=include_content) for row in rows], "query": terms}


__all__ = ["KINDS", "artifact_memory", "remember_artifact"]
