"""Query engine: retrieve → (optional LLM synthesis) → QueryResult.

The retrieval results are useful on their own (they're what MCP returns).
LLM synthesis is opt-in: if no provider is available we just package the
retrieved chunks + frames and skip the `answer` text.
"""

from __future__ import annotations

import logging
from pathlib import Path

import tiktoken

from videomemory.query.providers.base import LLMProvider
from videomemory.query.providers.ollama import OllamaProvider
from videomemory.query.providers.openai import OpenAIProvider
from videomemory.retrieval.router import retrieve_chunks, retrieve_frames
from videomemory.storage import sqlite_db
from videomemory.types import QueryResult

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a careful video-memory assistant.
You will be given retrieved chunks from a long video, with timestamps and
short summaries. Answer the user's question precisely. Cite timestamps as
[mm:ss]. If the retrieved chunks do not contain the answer, say so plainly."""


def _token_estimate(text: str) -> int:
    try:
        enc = tiktoken.encoding_for_model("gpt-4o-mini")
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def _fmt_time(t: float) -> str:
    m, s = divmod(int(t), 60)
    return f"{m:02d}:{s:02d}"


def _pick_provider() -> LLMProvider | None:
    for cls in (OllamaProvider, OpenAIProvider):
        try:
            if cls.is_available():
                return cls()
        except Exception:
            continue
    return None


async def answer_question(
    video_id: str,
    query: str,
    data_dir: Path,
    max_chunks: int = 5,
    max_frames: int = 8,
    include_frames: bool = True,
    modalities: list[str] | None = None,
) -> QueryResult:
    chunks = retrieve_chunks(video_id, query, data_dir, top_k=max_chunks, modalities=modalities)
    frames = retrieve_frames(video_id, query, data_dir, limit=max_frames) if include_frames else []

    # Filter frames to those inside the time spans of the top chunks for tighter focus
    if chunks and frames:
        spans = [(c.start, c.end) for c in chunks]
        scored = []
        for f in frames:
            in_chunk = any(a - 1.5 <= f.timestamp <= b + 1.5 for a, b in spans)
            scored.append((f, in_chunk))
        frames = [f for f, in_chunk in scored if in_chunk] + [f for f, in_chunk in scored if not in_chunk]
        frames = frames[:max_frames]

    events = await sqlite_db.get_events(video_id, data_dir)
    chunk_events = [e for e in events if any(e.event_id in c.key_events for c in chunks)]

    # Compose LLM prompt
    answer = None
    provider = _pick_provider()
    if provider is not None and chunks:
        ctx_parts: list[str] = []
        for c in chunks:
            ctx_parts.append(
                f"[{_fmt_time(c.start)}–{_fmt_time(c.end)}] {c.summary}\n"
                f"transcript: {c.transcript_excerpt[:600]}\n"
                f"ocr: {' | '.join(c.ocr_excerpts[:4])}"
            )
        ctx = "\n\n".join(ctx_parts)
        user_msg = f"User question: {query}\n\nRetrieved chunks:\n{ctx}\n\nAnswer:"
        try:
            answer = await provider.complete(SYSTEM_PROMPT, user_msg, max_tokens=400)
        except Exception as exc:
            log.warning("LLM synthesis failed (%s): %s", provider.name, exc)
            answer = None

    text_for_tokens = (answer or "") + "\n" + "\n".join(c.summary for c in chunks)
    return QueryResult(
        video_id=video_id,
        query=query,
        answer=answer,
        chunks=chunks,
        frames=frames,
        events=chunk_events,
        token_estimate=_token_estimate(text_for_tokens),
        strategy="fuse",
    )
