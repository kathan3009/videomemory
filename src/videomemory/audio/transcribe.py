"""Transcription via faster-whisper (CTranslate2)."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from videomemory.types import TranscriptSegment

log = logging.getLogger(__name__)


@lru_cache(maxsize=2)
def _load_model(model_size: str = "small", device: str = "cpu", compute_type: str | None = None):
    from faster_whisper import WhisperModel

    # faster-whisper does not support MPS; fall back to CPU on Apple Silicon.
    if device == "mps":
        device = "cpu"
    ctype = compute_type or ("int8" if device == "cpu" else "float16")
    log.info("loading faster-whisper model=%s device=%s compute=%s", model_size, device, ctype)
    return WhisperModel(model_size, device=device, compute_type=ctype)


def transcribe_wav(
    wav_path: Path,
    model_size: str = "small",
    language: str | None = None,
    device: str = "cpu",
) -> list[TranscriptSegment]:
    model = _load_model(model_size, device)
    segments, _info = model.transcribe(
        str(wav_path),
        language=language,
        vad_filter=True,
        beam_size=1,
        condition_on_previous_text=False,
    )
    out: list[TranscriptSegment] = []
    for s in segments:
        text = (s.text or "").strip()
        if not text:
            continue
        out.append(
            TranscriptSegment(
                start=float(s.start or 0.0),
                end=float(s.end or 0.0),
                text=text,
                confidence=float(getattr(s, "avg_logprob", 0.0) or 0.0),
            )
        )
    return out
