"""Scribe daemon — capture loop + lifecycle.

Lifecycle:
    `scribe start` → spawns a detached child running `daemon.run_forever()`,
                     writes PID + log paths.
    `scribe stop`  → reads PID, sends SIGTERM, waits.
    `scribe pause` → writes a pause sentinel; the loop checks it each tick.
    `scribe status`→ inspects PID + counts in SQLite.
    `scribe end`   → triggers digest (can be called whether daemon is running or not).

Capture cadence: every CAPTURE_INTERVAL seconds (default 2.0).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from videomemory.config import data_dir
from videomemory.scribe.capture import capture_screen
from videomemory.scribe.context import read_context
from videomemory.scribe.ocr import ocr_image
from videomemory.scribe.privacy import should_skip
from videomemory.scribe.store import insert_frame, stats
from videomemory.scribe.types import Frame

log = logging.getLogger(__name__)

CAPTURE_INTERVAL = float(os.environ.get("VIDEOMEMORY_SCRIBE_INTERVAL", "2.0"))


def runtime_dir() -> Path:
    p = data_dir() / "scribe"
    p.mkdir(parents=True, exist_ok=True)
    return p


def pid_file() -> Path:
    return runtime_dir() / "daemon.pid"


def pause_file() -> Path:
    return runtime_dir() / "paused"


def log_file() -> Path:
    return runtime_dir() / "daemon.log"


def frames_dir() -> Path:
    p = runtime_dir() / "frames"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------- one tick ----------


async def _tick() -> str:
    """Single capture cycle. Returns a one-word status."""
    if pause_file().exists():
        return "paused"

    ctx = await read_context()
    if ctx.locked:
        return "locked"

    skip, reason = should_skip(ctx.app, ctx.title, ctx.url)
    if skip:
        return f"skipped({reason})"

    ts = datetime.now()
    ts_ms = int(ts.timestamp() * 1000)
    out_path = frames_dir() / f"{ts_ms}.jpg"
    saved = await capture_screen(out_path)
    if not saved:
        return "capture_failed"

    text = await asyncio.to_thread(ocr_image, saved)

    frame = Frame(
        frame_id=str(ts_ms),
        captured_at=ts,
        frame_path=str(saved),
        ocr_text=text,
        context=ctx,
    )
    insert_frame(frame)
    return "captured"


# ---------- main loop ----------


async def run_forever(interval: float = CAPTURE_INTERVAL) -> None:
    """Run until SIGTERM. Writes a heartbeat to the log every minute."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        filename=str(log_file()),
        filemode="a",
    )
    stop = asyncio.Event()

    def _term(*_):
        log.info("received SIGTERM, stopping")
        stop.set()

    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)

    log.info("scribe daemon starting (interval=%.1fs)", interval)
    last_heartbeat = datetime.now()

    while not stop.is_set():
        try:
            status = await _tick()
        except Exception as exc:
            log.exception("tick failed: %s", exc)
            status = "error"

        now = datetime.now()
        if (now - last_heartbeat).total_seconds() >= 60:
            s = stats()
            log.info("heartbeat status=%s frames=%s sessions=%s", status, s["ephemeral_frames"], s["ephemeral_sessions"])
            last_heartbeat = now

        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass

    log.info("scribe daemon stopped")


# ---------- start / stop / status ----------


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def is_running() -> int | None:
    p = pid_file()
    if not p.exists():
        return None
    try:
        pid = int(p.read_text().strip())
    except ValueError:
        return None
    if _is_running(pid):
        return pid
    p.unlink(missing_ok=True)
    return None


def start_background() -> int:
    """Spawn a detached child running this module's main(). Returns PID."""
    existing = is_running()
    if existing is not None:
        return existing
    runtime_dir()
    log_path = log_file()
    log_fh = open(log_path, "a")
    proc = subprocess.Popen(
        [sys.executable, "-m", "videomemory.scribe.daemon"],
        stdout=log_fh, stderr=log_fh, stdin=subprocess.DEVNULL,
        start_new_session=True,
        env={**os.environ},
    )
    pid_file().write_text(str(proc.pid))
    return proc.pid


def stop_background(timeout: float = 6.0) -> bool:
    pid = is_running()
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pid_file().unlink(missing_ok=True)
        return False
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _is_running(pid):
            pid_file().unlink(missing_ok=True)
            return True
        time.sleep(0.2)
    # Force
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    pid_file().unlink(missing_ok=True)
    return True


def pause() -> None:
    pause_file().touch()


def resume() -> None:
    pause_file().unlink(missing_ok=True)


def is_paused() -> bool:
    return pause_file().exists()


def main() -> int:
    asyncio.run(run_forever())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
