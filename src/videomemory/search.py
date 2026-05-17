"""Search: cosine over SQLite-stored bge-small vectors.

skip(url, question)   → one unified answer for ANY video (auto-falls-back to
                        visual frames when the audio is sparse or no transcript
                        match is confident enough)
search(query)         → top hits across every video in the library
"""

from __future__ import annotations

import numpy as np

from videomemory.embed import embed_text
from videomemory.ingest import deep_link, fmt_time, ingest, video_id_for
from videomemory.library import (
    get_video,
    has_windows,
    iter_all_windows,
    iter_windows_for_video,
)
from videomemory.types import Frame, Hit, SkipResult

# Tunables — picked so a typical YouTube video with a real transcript and a
# good question has score ≥ 0.40. Silent / mismatched videos fall to visual.
MIN_TRANSCRIPT_CHARS = 100
MIN_HIT_CONFIDENCE = 0.30
VISUAL_FALLBACK_COUNT = 8


def _frame_uri(video_id: str, t: float) -> str:
    return f"videomemory://frames/{video_id}/{int(t * 1000):010d}.jpg"


def _topk_cosine(query_vec: np.ndarray, windows: list, top_k: int) -> list[tuple[object, float]]:
    """windows = list of (Window, np.ndarray). Returns top_k pairs ranked by cosine."""
    if not windows:
        return []
    mat = np.stack([v for _, v in windows], axis=0)
    scores = mat @ query_vec  # vectors are pre-normalised
    idx = np.argsort(-scores)[:top_k]
    return [(windows[i][0], float(scores[i])) for i in idx]


def _excerpt_around(text: str, max_chars: int = 320) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


async def skip(url: str, question: str) -> SkipResult:
    """Find the moment in `url` that answers `question`.

    Auto-detects audio-rich vs audio-sparse / mismatched videos:
      - confident transcript match  → mode='transcript' (+ one frame at the hit)
      - no transcript / weak match  → mode='visual' (+ N sampled frames the agent
                                       can look at with its own vision)

    The agent never has to pick a tool. One call covers every video.
    """
    # Reuse cached video if we already ingested this URL
    pre_id = video_id_for(url)
    v = get_video(pre_id) if pre_id.startswith(("yt_", "f_", "u_")) else None
    if not v or not has_windows(pre_id):
        v = await ingest(url)

    rows = iter_windows_for_video(v.video_id)
    total_chars = sum(len(w.text) for w, _ in rows)

    # --- Try transcript mode first ---
    transcript_hit = None
    best_score = 0.0
    if rows and total_chars >= MIN_TRANSCRIPT_CHARS:
        qv = np.asarray(embed_text(question), dtype=np.float32)
        top = _topk_cosine(qv, rows, top_k=1)
        if top:
            w, s = top[0]
            best_score = s
            if s >= MIN_HIT_CONFIDENCE:
                transcript_hit = (w, s)

    if transcript_hit is not None:
        w, score = transcript_hit
        hit_time = (w.start + w.end) / 2
        from videomemory.frames import extract_frame_at

        frames: list[Frame] = []
        try:
            path = await extract_frame_at(v.video_id, v.source, hit_time)
            if path:
                frames = [
                    Frame(
                        video_id=v.video_id,
                        timestamp_seconds=hit_time,
                        timestamp_human=fmt_time(hit_time),
                        deep_link=deep_link(v.source, hit_time),
                        frame_uri=_frame_uri(v.video_id, hit_time),
                    )
                ]
        except Exception:
            pass

        return SkipResult(
            mode="transcript",
            video_id=v.video_id,
            title=v.title,
            source=v.source,
            confidence=score,
            note=f"confident transcript match (score={score:.2f})",
            timestamp_human=fmt_time(hit_time),
            deep_link=deep_link(v.source, hit_time),
            transcript_excerpt=_excerpt_around(w.text),
            frames=frames,
        )

    # --- Visual fallback: sample frames covering the whole video ---
    from videomemory.frames import get_frames

    visual = await get_frames(url, count=VISUAL_FALLBACK_COUNT)
    if total_chars < MIN_TRANSCRIPT_CHARS:
        reason = "audio is too sparse for transcript search"
    else:
        reason = f"no confident transcript match (best score={best_score:.2f})"
    note = (
        f"{reason} — returning {len(visual)} keyframes covering the video. "
        "Look at each frame with your vision to answer the question; the most "
        "relevant frame's `deep_link` is the user-facing timestamp."
    )

    # Provide whatever transcript we did capture, truncated
    transcript_blurb = ""
    if total_chars:
        transcript_blurb = " ".join(w.text for w, _ in rows)[:600]

    return SkipResult(
        mode="visual",
        video_id=v.video_id,
        title=v.title,
        source=v.source,
        confidence=best_score,
        note=note,
        timestamp_human=None,
        deep_link=None,
        transcript_excerpt=transcript_blurb,
        frames=visual,
    )


def search(query: str, *, top_k: int = 5) -> list[Hit]:
    """Cross-video search. Reads every video in the library.

    Returns hits *without* frame URIs — frames are not extracted at search time
    to keep cross-video queries fast. Call `skip(url, q)` (which auto-extracts
    frames) on a hit's video for visual context.
    """
    rows = iter_all_windows()
    if not rows:
        return []
    qv = np.asarray(embed_text(query), dtype=np.float32)
    top = _topk_cosine(qv, rows, top_k=top_k)
    hits: list[Hit] = []
    for w, score in top:
        v = get_video(w.video_id)
        if not v:
            continue
        hit_time = (w.start + w.end) / 2
        hits.append(
            Hit(
                video_id=w.video_id,
                title=v.title,
                source=v.source,
                start=w.start,
                end=w.end,
                timestamp_human=fmt_time(hit_time),
                deep_link=deep_link(v.source, hit_time),
                transcript_excerpt=_excerpt_around(w.text),
                score=score,
                frame_uri=None,
            )
        )
    return hits


__all__ = ["skip", "search"]
