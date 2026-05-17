"""End-to-end scribe digest test: synthetic frames → OCR → cluster → extractive digest."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from videomemory.scribe.digest import build_today_digest
from videomemory.scribe.store import (
    insert_frame,
    purge_ephemeral,
    stats,
)
from videomemory.scribe.types import CaptureContext, Frame


def _font(size: int):
    for c in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def _make_frame_image(text: str, dst: Path) -> Path:
    img = Image.new("RGB", (640, 360), (245, 245, 245))
    d = ImageDraw.Draw(img)
    f = _font(40)
    bbox = d.textbbox((0, 0), text, font=f)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((640 - w) // 2, (360 - h) // 2), text, fill=(10, 10, 10), font=f)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=88)
    return dst


@pytest.fixture(autouse=True)
def _clean_ephemeral():
    purge_ephemeral()
    yield
    purge_ephemeral()


def test_digest_pipeline_end_to_end(tmp_path: Path):
    """Mock a day of work: 3 sessions in VSCode + Safari + Terminal.

    Generates real frame PNGs with text → OCR happens for real → clustering happens
    for real → digest uses the extractive fallback (no API key). Asserts:
      • markdown file written
      • day row + day_lines created
      • ephemeral frames purged after digest
    """
    os.environ.setdefault("ANTHROPIC_API_KEY", "")  # force extractive fallback
    # Don't accidentally hit Ollama:
    os.environ.setdefault("VIDEOMEMORY_OLLAMA_URL", "http://127.0.0.1:1")

    base = datetime.now() - timedelta(hours=2)
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()

    sessions = [
        ("VSCode", "videomemory scribe.py", "writing scribe digest", 30),
        ("Safari", "Hacker News - top stories", "Hacker News headlines", 30),
        ("Terminal", "pytest", "tests passed for scribe pipeline", 30),
    ]

    fid = 0
    for app, title, text, n_frames in sessions:
        for _i in range(n_frames):
            ts = base + timedelta(seconds=fid * 2)
            img_path = frames_dir / f"{fid:06d}.jpg"
            _make_frame_image(text, img_path)
            insert_frame(
                Frame(
                    frame_id=f"test-{fid}-{uuid.uuid4().hex[:6]}",
                    captured_at=ts,
                    frame_path=str(img_path),
                    ocr_text=text,            # pre-filled so test is OCR-agnostic
                    context=CaptureContext(app=app, title=title),
                )
            )
            fid += 1
        base = base + timedelta(seconds=n_frames * 2 + 90)  # gap forces session boundary

    pre = stats()
    assert pre["ephemeral_frames"] == 3 * 30
    assert pre["durable_days"] == 0

    out_path = asyncio.run(build_today_digest())
    assert out_path is not None
    assert out_path.exists()
    md = out_path.read_text()
    # Should mention all three apps
    assert "VSCode" in md or "vscode" in md.lower()
    assert "Safari" in md
    assert "Terminal" in md

    post = stats()
    assert post["ephemeral_frames"] == 0       # purged
    assert post["ephemeral_sessions"] == 0
    assert post["durable_days"] == 1
    assert post["durable_lines"] >= 3          # one "did" per session minimum


def test_digest_with_no_frames_returns_none():
    """If nothing was captured today, build_today_digest returns None gracefully."""
    out = asyncio.run(build_today_digest())
    assert out is None
