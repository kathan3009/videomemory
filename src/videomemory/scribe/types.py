"""Scribe schemas — Pydantic, shared across modules."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CaptureContext(BaseModel):
    """The user's foreground state at the moment of capture."""

    app: str = "unknown"          # bundle id or process name
    title: str = ""               # frontmost window title
    url: str | None = None        # active browser URL when app is Safari/Chrome/Arc/Firefox
    locked: bool = False          # screen lock state
    on_battery: bool = False
    battery_percent: int | None = None


class Frame(BaseModel):
    """A single captured frame + its OCR + context."""

    frame_id: str                  # f"{ts_ms}"
    captured_at: datetime
    frame_path: str                # JPG/PNG on disk
    ocr_text: str = ""             # full OCR text (newline-joined)
    context: CaptureContext


class Session(BaseModel):
    """A consecutive run of frames the user spent in the same app/window."""

    session_id: str
    started_at: datetime
    ended_at: datetime
    app: str
    title_summary: str
    url: str | None = None
    frame_ids: list[str] = Field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return (self.ended_at - self.started_at).total_seconds()


class Note(BaseModel):
    """An atomic note Claude wrote for a session."""

    note_id: str
    session_id: str
    kind: str                      # "did" | "decided" | "learned" | "todo" | "error" | "saw"
    text: str
    t_seconds: float               # offset from session start
    timestamp_human: str            # "09:33"
    created_at: datetime
