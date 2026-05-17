"""Active app / window / URL context — via osascript on macOS."""

from __future__ import annotations

import asyncio
import platform
import shutil

from videomemory.scribe.privacy import battery_status, screen_is_locked
from videomemory.scribe.types import CaptureContext

_FRONT_APP_OSA = """
on run
  tell application "System Events"
    set frontApp to first application process whose frontmost is true
    set appName to name of frontApp
    set winTitle to ""
    try
      set winTitle to name of front window of frontApp
    end try
    return appName & "||" & winTitle
  end tell
end run
"""

_SAFARI_URL = 'tell application "Safari" to return URL of current tab of front window'
_CHROME_URL = 'tell application "Google Chrome" to return URL of active tab of front window'
_ARC_URL    = 'tell application "Arc" to return URL of active tab of front window'
_FIREFOX_URL_FALLBACK = (
    # Firefox doesn't expose URL via AppleScript. Use the window title heuristic.
    None
)

_BROWSER_HANDLERS: dict[str, str] = {
    "Safari": _SAFARI_URL,
    "Google Chrome": _CHROME_URL,
    "Chrome": _CHROME_URL,
    "Arc": _ARC_URL,
}


async def _osascript(source: str) -> str | None:
    if not shutil.which("osascript"):
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", source,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=2)
        return out.decode(errors="replace").strip() or None
    except Exception:
        return None


async def read_context() -> CaptureContext:
    if platform.system() != "Darwin":
        on_batt, pct = battery_status()
        return CaptureContext(
            app="unknown", title="", url=None,
            locked=False, on_battery=on_batt, battery_percent=pct,
        )

    locked = screen_is_locked()
    on_batt, pct = battery_status()

    raw = await _osascript(_FRONT_APP_OSA)
    if not raw or "||" not in raw:
        return CaptureContext(app="unknown", locked=locked, on_battery=on_batt, battery_percent=pct)
    app, title = raw.split("||", 1)
    app = app.strip()
    title = title.strip()

    url: str | None = None
    handler = _BROWSER_HANDLERS.get(app)
    if handler:
        url = await _osascript(handler)

    return CaptureContext(
        app=app,
        title=title,
        url=url,
        locked=locked,
        on_battery=on_batt,
        battery_percent=pct,
    )
