"""Memory exporters (markdown / json / yaml / llm-context)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from videomemory.retrieval.store_helpers import load_chunks
from videomemory.storage import sqlite_db


def _fmt_time(t: float) -> str:
    m, s = divmod(int(t), 60)
    return f"{m:02d}:{s:02d}"


async def export_memory(video_id: str, fmt: str, data_dir: Path) -> str:
    chunks = load_chunks(video_id, data_dir)
    events = await sqlite_db.get_events(video_id, data_dir)
    entities = await sqlite_db.get_entities(video_id, data_dir)
    meta = await sqlite_db.get_video(video_id, data_dir)

    payload = {
        "video": meta.model_dump(mode="json") if meta else {"video_id": video_id},
        "chunks": [c.model_dump(mode="json") for c in chunks],
        "events": [e.model_dump(mode="json") for e in events],
        "entities": [e.model_dump(mode="json") for e in entities],
    }

    fmt = fmt.lower()
    if fmt == "json":
        return json.dumps(payload, indent=2)
    if fmt == "yaml":
        return yaml.safe_dump(payload, sort_keys=False)
    if fmt == "markdown":
        return _to_markdown(payload)
    if fmt == "llm-context":
        return _to_llm_context(payload)
    raise ValueError(f"unknown format: {fmt}")


def _to_markdown(p: dict) -> str:
    lines: list[str] = []
    v = p["video"]
    lines.append(f"# {v.get('title') or v.get('video_id')}")
    lines.append("")
    lines.append(f"- duration: {v.get('duration', 0):.1f}s")
    lines.append(f"- source: {v.get('source', '')}")
    lines.append("")
    lines.append("## Timeline")
    for c in p["chunks"]:
        lines.append(f"- **{_fmt_time(c['start'])}–{_fmt_time(c['end'])}** — {c['summary']}")
    lines.append("")
    lines.append("## Entities")
    for e in p["entities"]:
        lines.append(f"- {e['kind']}: {e['label']}")
    lines.append("")
    lines.append("## Events")
    for ev in p["events"]:
        lines.append(f"- [{_fmt_time(ev['t_start'])}] {ev['description']}")
    return "\n".join(lines)


def _to_llm_context(p: dict, max_chunks: int = 10) -> str:
    v = p["video"]
    lines = [f"VIDEO: {v.get('title') or v.get('video_id')} (duration {v.get('duration', 0):.0f}s)\n"]
    lines.append("TIMELINE:")
    for c in p["chunks"][:max_chunks]:
        lines.append(f"  [{_fmt_time(c['start'])}–{_fmt_time(c['end'])}] {c['summary'][:140]}")
    lines.append("\nKEY EVENTS:")
    for ev in p["events"][:20]:
        lines.append(f"  [{_fmt_time(ev['t_start'])}] {ev['description'][:140]}")
    lines.append("\nENTITIES:")
    for e in p["entities"][:30]:
        lines.append(f"  - {e['kind']}: {e['label']}")
    return "\n".join(lines)
