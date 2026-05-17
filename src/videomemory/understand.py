"""understand(url): full transcript + 4-8 bullet takeaways + chapter markers.

Bullets are produced from a simple extractive heuristic by default. If an
LLM provider is configured (Anthropic / OpenAI), we use it for a sharper
summary. The output schema is identical either way.
"""

from __future__ import annotations

import os
import re

import numpy as np

from videomemory.embed import embed_text
from videomemory.ingest import deep_link, fmt_time, ingest, transcribe_full
from videomemory.library import get_windows
from videomemory.types import Hit, Summary


def _bullet_indices(window_texts: list[str], n: int = 6) -> list[int]:
    """Pick n windows that best diversify the transcript using a tiny MMR-like loop."""
    if not window_texts:
        return []
    vecs = [np.asarray(embed_text(t), dtype=np.float32) for t in window_texts]
    centroid = np.mean(vecs, axis=0)
    # Score = similarity to centroid (representativeness) minus max-sim-to-picked (diversity).
    picked: list[int] = []
    avail = set(range(len(vecs)))
    while avail and len(picked) < n:
        best = None
        best_score = -1e9
        for i in avail:
            rep = float(vecs[i] @ centroid)
            if picked:
                div = max(float(vecs[i] @ vecs[j]) for j in picked)
            else:
                div = 0.0
            s = rep - 0.6 * div
            if s > best_score:
                best_score = s
                best = i
        if best is None:
            break
        picked.append(best)
        avail.discard(best)
    return sorted(picked)


def _heuristic_bullets(window_texts: list[str], n: int = 6) -> list[str]:
    idxs = _bullet_indices(window_texts, n=n)
    bullets = []
    for i in idxs:
        text = window_texts[i]
        # Take the first sentence-ish snippet
        snip = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
        if len(snip) > 200:
            snip = snip[:197].rstrip() + "…"
        bullets.append(snip.strip())
    return bullets


def _llm_bullets(transcript: str, max_bullets: int = 6) -> list[str] | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    prompt = (
        "You are summarising a video transcript. Produce exactly "
        f"{max_bullets} concise, factual bullets capturing the most useful "
        "non-obvious takeaways. No preamble, no numbering, just bullets prefixed with '- '.\n\n"
        f"TRANSCRIPT:\n{transcript[:18000]}\n\nBULLETS:"
    )
    try:
        if os.environ.get("ANTHROPIC_API_KEY"):
            import httpx

            r = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 400,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            text = data["content"][0]["text"]
        else:
            import httpx

            r = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "max_tokens": 400,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30,
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
    except Exception:
        return None
    bullets = []
    for line in text.splitlines():
        line = line.strip().lstrip("-•*").strip()
        if line:
            bullets.append(line)
    return bullets[:max_bullets] or None


async def understand(url: str) -> Summary:
    v = await ingest(url)
    windows = get_windows(v.video_id)
    if not windows:
        return Summary(
            video_id=v.video_id, title=v.title, duration=v.duration, source=v.source,
            bullets=[], chapters=[], full_transcript_chars=0, full_transcript="",
        )
    texts = [w.text for w in windows]
    full = transcribe_full(v.video_id)
    bullets = _llm_bullets(full) or _heuristic_bullets(texts)

    # Chapters = the same MMR picks, but as Hits with deep links
    idxs = _bullet_indices(texts, n=min(6, len(texts)))
    chapters: list[Hit] = []
    for i in idxs:
        w = windows[i]
        t = (w.start + w.end) / 2
        chapters.append(
            Hit(
                video_id=v.video_id,
                title=v.title,
                source=v.source,
                start=w.start,
                end=w.end,
                timestamp_human=fmt_time(t),
                deep_link=deep_link(v.source, t),
                transcript_excerpt=w.text[:200],
                score=1.0,
                frame_uri=None,
            )
        )

    truncated = full if len(full) <= 8000 else full[:8000] + "\n…[truncated; use search() to query the rest]"
    return Summary(
        video_id=v.video_id,
        title=v.title,
        duration=v.duration,
        source=v.source,
        bullets=bullets,
        chapters=chapters,
        full_transcript_chars=len(full),
        full_transcript=truncated,
    )


__all__ = ["understand"]
