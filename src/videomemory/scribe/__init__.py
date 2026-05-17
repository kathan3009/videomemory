"""scribe — full-screen capture + Claude-curated notes.

Captures your active screen every 2 s, OCRs each frame, clusters consecutive
frames by app/window into sessions, and uses an LLM (Claude Haiku by default,
local Ollama fallback) to take notes per session. Everything stays local;
the LLM only ever sees OCR text, never image bytes.

Surface:
    daemon  — `videomemory scribe start` runs the capture/cluster/notes loop
    search  — `videomemory scribe search "<q>"` and matching MCP tool
    forget  — privacy-first deletion (`--since 10m`, `--app Safari`, etc.)
"""

from videomemory.scribe.types import Frame, Note, Session

__all__ = ["Frame", "Session", "Note"]
