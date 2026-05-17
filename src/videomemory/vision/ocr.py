"""OCR via rapidocr-onnxruntime (ARM-clean, ONNX)."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _engine():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def ocr_frame(path: Path, min_score: float = 0.5) -> list[str]:
    """Return list of detected text lines for one frame."""
    ocr = _engine()
    try:
        result, _ = ocr(str(path))
    except Exception as exc:  # pragma: no cover - rare ONNX errors
        log.warning("ocr failed on %s: %s", path, exc)
        return []
    if not result:
        return []
    out: list[str] = []
    for entry in result:
        # rapidocr returns [bbox, text, score]
        if len(entry) >= 3:
            text, score = entry[1], entry[2]
            if isinstance(score, (int, float)) and score < min_score:
                continue
            text = (text or "").strip()
            if text:
                out.append(text)
    return out


def ocr_frames(paths: list[Path]) -> list[list[str]]:
    return [ocr_frame(p) for p in paths]
