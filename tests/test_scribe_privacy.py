"""scribe privacy: blocklist matching is deterministic and case-insensitive."""

from __future__ import annotations

from videomemory.scribe.privacy import should_skip


def test_default_app_blocklist_catches_password_managers():
    skip, reason = should_skip("1Password", "Vault — work")
    assert skip and "1Password" in reason


def test_default_url_blocklist_catches_login_pages():
    skip, reason = should_skip("Safari", "Sign in", url="https://accounts.google.com/signin")
    assert skip and "url" in reason.lower()


def test_normal_app_is_not_blocked():
    skip, _ = should_skip("VSCode", "videomemory — scribe.py")
    assert not skip


def test_safari_to_bank_is_blocked_by_url():
    skip, reason = should_skip("Safari", "Welcome to Chase", url="https://chase.bank/login")
    assert skip


def test_signal_messaging_app_is_blocked():
    skip, reason = should_skip("Signal", "Chat with friend")
    assert skip and "Signal" in reason


def test_blocking_is_case_insensitive():
    skip, _ = should_skip("1PASSWORD", "")
    assert skip
