"""End-of-day digest: take ephemeral frames+sessions → durable day markdown.

After the digest is written and embedded, ephemeral storage is purged.

LLM selection (in order):
  1. Anthropic Claude Haiku  (if ANTHROPIC_API_KEY is set)
  2. Ollama (if reachable at $VIDEOMEMORY_OLLAMA_URL or http://localhost:11434)
  3. Heuristic extractive fallback — deterministic, no LLM, lower quality but
     works offline with zero API spend.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date as _date
from pathlib import Path

import httpx

from videomemory.config import data_dir
from videomemory.embed import embed_texts
from videomemory.scribe.store import (
    insert_day_lines,
    purge_ephemeral,
    recent_frames,
    sessions_between,
    upsert_day,
)
from videomemory.scribe.types import Frame, Session

DAY_KINDS = {"did", "learned", "decided", "todo", "saw", "seen"}


def _today_str() -> str:
    return _date.today().isoformat()


def days_dir() -> Path:
    p = data_dir() / "days"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------- session brief building ----------


def _session_brief(session: Session, frames: list[Frame]) -> dict:
    """Build a compact JSON brief of a session for the LLM (text only, no images)."""
    if not frames:
        return {}
    n_samples = min(5, len(frames))
    # evenly-spaced indices
    step = max(1, len(frames) // n_samples)
    samples = [frames[i] for i in range(0, len(frames), step)][:n_samples]
    return {
        "app": session.app,
        "title": session.title_summary,
        "url": session.url,
        "started": session.started_at.strftime("%H:%M"),
        "ended": session.ended_at.strftime("%H:%M"),
        "duration_minutes": round(session.duration_seconds / 60.0, 1),
        "ocr_samples": [
            {"at": f.captured_at.strftime("%H:%M"), "text": (f.ocr_text or "")[:600]}
            for f in samples
        ],
    }


# ---------- LLM-driven digest ----------


PROMPT = """You are reconstructing the user's day from quiet screen captures.
You see only OCR text snippets and window titles — never images. Your output is
the user's *day digest*, a markdown file they will keep forever.

Style:
  - first person, present tense, dry and factual ("Debugged a SQLite locking…")
  - aggregate across sessions; don't recap every window-switch
  - skip noise: ads, idle screens, system menus, empty captures
  - timestamps as [HH:MM]
  - separate sections: 'What you did', 'What you learned', 'What you decided',
    'Open threads', 'Tomorrow' (only if mentioned)
  - 6-15 bullets total across all sections

INPUT (JSON list of session briefs):
{sessions_json}

Return STRICT JSON with this shape, no preamble:
{{
  "summary": "<1-paragraph plain English overview>",
  "lines": [
    {{"kind": "did", "text": "[09:32] Debugged a SQLite locking issue…"}},
    {{"kind": "learned", "text": "[10:02] ScreenCaptureKit's enum changed in macOS 15."}},
    ...
  ]
}}

kind ∈ {{ "did", "learned", "decided", "todo", "saw" }}."""


def _build_sessions_json(sessions: list[Session], frames_by_session: dict[str, list[Frame]]) -> str:
    briefs = []
    for s in sessions:
        b = _session_brief(s, frames_by_session.get(s.session_id, []))
        if b:
            briefs.append(b)
    return json.dumps(briefs, indent=2)


def _try_anthropic(prompt: str) -> dict | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": os.environ.get("VIDEOMEMORY_LLM_MODEL", "claude-haiku-4-5-20251001"),
                "max_tokens": 1200,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        r.raise_for_status()
        text = r.json()["content"][0]["text"]
        return _extract_json(text)
    except Exception:
        return None


def _try_ollama(prompt: str) -> dict | None:
    url = (os.environ.get("VIDEOMEMORY_OLLAMA_URL") or "http://localhost:11434").rstrip("/")
    model = os.environ.get("VIDEOMEMORY_OLLAMA_MODEL", "qwen2.5:3b")
    try:
        r = httpx.post(
            f"{url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False,
                  "options": {"num_predict": 1200, "temperature": 0.2}},
            timeout=120,
        )
        r.raise_for_status()
        text = r.json().get("response", "")
        return _extract_json(text)
    except Exception:
        return None


def _extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of an LLM reply."""
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        if not isinstance(data, dict):
            return None
        return data
    except json.JSONDecodeError:
        return None


# ---------- extractive fallback (no LLM) ----------


def _heuristic_digest(sessions: list[Session], frames_by_session: dict[str, list[Frame]]) -> dict:
    """Produce a deterministic, useful-enough digest without any LLM."""
    lines: list[dict] = []
    total = sum(s.duration_seconds for s in sessions)
    for s in sessions:
        ts = s.started_at.strftime("%H:%M")
        dur_min = round(s.duration_seconds / 60.0, 1)
        title = s.title_summary or s.app
        if dur_min < 1:
            continue
        if s.url:
            lines.append({"kind": "did", "text": f"[{ts}] {s.app} — {title} ({dur_min}m) · {s.url}"})
        else:
            lines.append({"kind": "did", "text": f"[{ts}] {s.app} — {title} ({dur_min}m)"})
        frames = frames_by_session.get(s.session_id, [])
        if frames:
            # surface one distinctive OCR snippet per session, if any
            seen: set[str] = set()
            for f in frames[:3]:
                txt = (f.ocr_text or "").strip()
                if not txt:
                    continue
                snippet = " ".join(txt.split())[:140]
                if snippet not in seen and len(snippet) > 12:
                    lines.append({"kind": "saw", "text": f"[{ts}] {snippet}"})
                    seen.add(snippet)
                    break
    summary = f"{len(sessions)} session(s), ~{round(total/60.0,1)} active minutes."
    return {"summary": summary, "lines": lines}


# ---------- top-level orchestration ----------


def _md_from_digest(date_str: str, digest: dict, active_seconds: float) -> str:
    lines = digest.get("lines") or []
    summary = digest.get("summary") or ""
    by_kind: dict[str, list[str]] = {}
    for ln in lines:
        if not isinstance(ln, dict):
            continue
        k = (ln.get("kind") or "did").lower()
        if k not in DAY_KINDS:
            k = "did"
        by_kind.setdefault(k, []).append(str(ln.get("text") or "").strip())

    out: list[str] = []
    out.append(f"# {date_str}")
    out.append("")
    out.append(f"_Active screen time: {round(active_seconds/60.0, 1)} min_")
    out.append("")
    if summary:
        out.append(summary.strip())
        out.append("")
    order = [
        ("did", "## What you did"),
        ("learned", "## What you learned"),
        ("decided", "## Decisions"),
        ("todo", "## Open threads"),
        ("saw", "## Notable on-screen content"),
    ]
    for k, heading in order:
        bullets = by_kind.get(k) or []
        if not bullets:
            continue
        out.append(heading)
        for b in bullets:
            out.append(f"- {b}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


async def build_today_digest(*, force: bool = False) -> Path | None:
    """Run the end-of-day digest. Returns the path to the markdown file."""
    frames = recent_frames(limit=20_000)
    if not frames and not force:
        return None

    # Cluster on the fly if no sessions exist yet
    from videomemory.scribe.sessions import rebuild_today_sessions

    rebuild_today_sessions()
    # Pull all sessions seen today
    if frames:
        sessions = sessions_between(frames[0].captured_at, frames[-1].captured_at)
    else:
        sessions = []
    if not sessions and not force:
        return None

    frames_by_session: dict[str, list[Frame]] = {}
    for s in sessions:
        frames_by_session[s.session_id] = [
            f for f in frames if f.frame_id in set(s.frame_ids)
        ]

    sessions_json = _build_sessions_json(sessions, frames_by_session)
    prompt = PROMPT.format(sessions_json=sessions_json)

    digest = _try_anthropic(prompt) or _try_ollama(prompt) or _heuristic_digest(sessions, frames_by_session)

    date_str = _today_str()
    active_seconds = sum(s.duration_seconds for s in sessions)
    md = _md_from_digest(date_str, digest, active_seconds)

    out_path = days_dir() / f"{date_str}.md"
    out_path.write_text(md)

    # Embed every line for search
    lines_for_embed: list[tuple[str, str]] = []
    for ln in digest.get("lines") or []:
        if isinstance(ln, dict) and ln.get("text"):
            lines_for_embed.append(((ln.get("kind") or "did"), str(ln["text"])))
    vecs = embed_texts([t for _, t in lines_for_embed]) if lines_for_embed else []

    upsert_day(
        date=date_str,
        markdown_path=str(out_path),
        summary=str(digest.get("summary") or ""),
        active_seconds=active_seconds,
        n_sessions=len(sessions),
    )
    if lines_for_embed:
        insert_day_lines(date_str, lines_for_embed, vecs)

    # Purge the raw ephemeral storage. This is the privacy-critical step.
    purge_ephemeral()

    return out_path


__all__ = ["build_today_digest", "days_dir"]
