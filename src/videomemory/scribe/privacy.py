"""Privacy gates: app blocklist, URL blocklist, lock-screen state.

This module is the single source of truth for "should we capture this frame?"
It is intentionally simple and deterministic so it's easy to audit.
"""

from __future__ import annotations

import fnmatch
import json
import os
import platform
import subprocess
from pathlib import Path

from videomemory.config import data_dir

# Apps we never index. Use the user-visible name OR macOS bundle id.
DEFAULT_APP_BLOCKLIST: list[str] = [
    "1Password",
    "1Password 7 - Password Manager",
    "Bitwarden",
    "KeePassXC",
    "Authy Desktop",
    "Signal",
    "WhatsApp",
    "Telegram",
    "Messages",
    "Tinder",
    "Hinge",
    "Bumble",
    "Banking",
    "Finder",  # often shows file paths that may contain sensitive names
]

# URL patterns we never index (fnmatch globs).
DEFAULT_URL_BLOCKLIST: list[str] = [
    "https://*.bank/*",
    "https://*.banking.*",
    "https://accounts.google.com/*",
    "https://login.*",
    "https://*/login*",
    "https://*/oauth*",
    "https://*/auth*",
    "https://*.stripe.com/*",
    "https://*.paypal.com/*",
    "https://*.coinbase.com/*",
    "https://github.com/settings/tokens*",
    "*://*password*",
    "*://*credit-card*",
]


def _config_path() -> Path:
    return data_dir() / "scribe_blocklist.json"


def _load_user_blocklist() -> dict[str, list[str]]:
    p = _config_path()
    if not p.exists():
        return {"apps": [], "urls": []}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"apps": [], "urls": []}


def _save_user_blocklist(data: dict[str, list[str]]) -> None:
    _config_path().write_text(json.dumps(data, indent=2))


def blocklists() -> tuple[list[str], list[str]]:
    """Return effective (apps, urls) — defaults plus user additions."""
    user = _load_user_blocklist()
    apps = DEFAULT_APP_BLOCKLIST + user.get("apps", [])
    urls = DEFAULT_URL_BLOCKLIST + user.get("urls", [])
    return apps, urls


def add_app(name: str) -> None:
    user = _load_user_blocklist()
    if name not in user.get("apps", []):
        user.setdefault("apps", []).append(name)
        _save_user_blocklist(user)


def remove_app(name: str) -> bool:
    user = _load_user_blocklist()
    apps = user.get("apps", [])
    if name in apps:
        apps.remove(name)
        user["apps"] = apps
        _save_user_blocklist(user)
        return True
    return False


def add_url(pattern: str) -> None:
    user = _load_user_blocklist()
    if pattern not in user.get("urls", []):
        user.setdefault("urls", []).append(pattern)
        _save_user_blocklist(user)


def remove_url(pattern: str) -> bool:
    user = _load_user_blocklist()
    urls = user.get("urls", [])
    if pattern in urls:
        urls.remove(pattern)
        user["urls"] = urls
        _save_user_blocklist(user)
        return True
    return False


def should_skip(app: str, title: str | None = None, url: str | None = None) -> tuple[bool, str]:
    """Return (skip, reason). Frame should be captured iff skip is False."""
    apps, urls = blocklists()

    app_lower = (app or "").lower()
    title_lower = (title or "").lower()
    for blocked in apps:
        bl = blocked.lower()
        if bl == app_lower or bl in app_lower or bl in title_lower:
            return True, f"blocked app: {blocked}"

    if url:
        for pat in urls:
            if fnmatch.fnmatch(url, pat) or fnmatch.fnmatch(url, pat.lower()):
                return True, f"blocked url pattern: {pat}"

    return False, ""


# --- lock-screen detection -------------------------------------------------


def screen_is_locked() -> bool:
    """Best-effort detection. Always false off macOS for v1."""
    if platform.system() != "Darwin":
        return False
    # `ioreg -n IODisplayWrangler` returns IOPowerManagement state when display is asleep.
    # A simpler and well-known heuristic uses `pmset -g powerstate IODisplayWrangler`.
    try:
        out = subprocess.run(
            ["pmset", "-g", "powerstate", "IODisplayWrangler"],
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode == 0:
            # Last column is the current power state; 0/1 = display asleep
            last_line = (out.stdout or "").strip().splitlines()[-1]
            parts = last_line.split()
            try:
                state = int(parts[-1])
                return state <= 1
            except (ValueError, IndexError):
                return False
    except Exception:
        return False
    return False


def battery_status() -> tuple[bool, int | None]:
    """(on_battery, percent_or_none). v1: macOS only via pmset."""
    if platform.system() != "Darwin":
        return False, None
    try:
        out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=2)
        text = out.stdout
        on_battery = "Battery Power" in text
        percent: int | None = None
        for tok in text.split():
            if tok.endswith("%;"):
                try:
                    percent = int(tok.rstrip("%;"))
                except ValueError:
                    pass
                break
        return on_battery, percent
    except Exception:
        return False, None


def _testing() -> bool:
    return os.environ.get("VIDEOMEMORY_TEST_MODE") == "1"
