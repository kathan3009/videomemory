"""Templated captioning: compose a one-line caption from objects + OCR + scene tags.

This is the lightweight default. A pluggable VLM (Ollama/llava) can override it via
`PipelineConfig.use_vlm_caption` in a future enhancement; the contract here is
deterministic and fast.
"""

from __future__ import annotations


def compose_caption(
    objects: list[str],
    ocr_text: list[str],
    clip_tags: list[tuple[str, float]],
    transcript_excerpt: str = "",
) -> str:
    parts: list[str] = []

    # Dominant scene tag (skip generic "a person" if richer alternatives exist)
    if clip_tags:
        primary = clip_tags[0][0]
        parts.append(primary)

    # Objects (deduped, top few)
    if objects:
        unique = sorted(set(o for o in objects if o), key=lambda x: x)
        if unique:
            obj_str = ", ".join(unique[:4])
            parts.append(f"featuring {obj_str}")

    # OCR snippet (clipped)
    if ocr_text:
        flat = " ".join(t for t in ocr_text if t).strip()
        if flat:
            if len(flat) > 60:
                flat = flat[:57].rstrip() + "..."
            parts.append(f"with on-screen text “{flat}”")

    # Lightweight transcript anchor
    if transcript_excerpt:
        snippet = transcript_excerpt.strip().split(".")[0]
        if snippet and len(snippet) > 8:
            if len(snippet) > 60:
                snippet = snippet[:57].rstrip() + "..."
            parts.append(f"as the audio mentions “{snippet}”")

    if not parts:
        return "an unidentified scene"
    return "; ".join(parts)
