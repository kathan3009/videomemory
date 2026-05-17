"""OCR — rapidocr (ONNX, ARM-clean) for now. Native macOS Vision is a v1.1 swap-in."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _engine():
    try:
        from rapidocr_onnxruntime import RapidOCR

        return RapidOCR()
    except Exception as exc:
        log.warning("rapidocr not available: %s", exc)
        return None


def ocr_image(path: Path, min_score: float = 0.5) -> str:
    """Return joined text from an image, newline-separated per line."""
    eng = _engine()
    if eng is None:
        return ""
    try:
        result, _elapsed = eng(str(path))
    except Exception as exc:
        log.warning("ocr failed on %s: %s", path, exc)
        return ""
    if not result:
        return ""
    lines: list[str] = []
    for entry in result:
        if len(entry) >= 3:
            text, score = entry[1], entry[2]
            if isinstance(score, (int, float)) and score < min_score:
                continue
            text = (text or "").strip()
            if text:
                lines.append(text)
    return "\n".join(lines)
