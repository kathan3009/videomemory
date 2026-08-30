"""CAPTCHA validation and transactional account email delivery."""

from __future__ import annotations

import html
import os
from urllib.parse import quote, urlparse

import httpx

from videomemory.config import hosted_mode

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
RESEND_EMAIL_URL = "https://api.resend.com/emails"


class CaptchaUnavailable(RuntimeError):
    pass


class EmailUnavailable(RuntimeError):
    pass


def email_verification_required() -> bool:
    value = os.environ.get("VIDEOMEMORY_REQUIRE_EMAIL_VERIFICATION")
    if value is not None:
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return hosted_mode()


async def verify_captcha(token: str, remote_ip: str | None = None, expected_action: str | None = None) -> None:
    secret = os.environ.get("TURNSTILE_SECRET_KEY", "").strip()
    if not secret:
        if hosted_mode():
            raise CaptchaUnavailable("CAPTCHA is not configured")
        return
    if not token.strip():
        raise ValueError("complete the CAPTCHA challenge")
    payload = {"secret": secret, "response": token.strip()}
    if remote_ip:
        payload["remoteip"] = remote_ip
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(TURNSTILE_VERIFY_URL, data=payload)
    if response.status_code >= 500:
        raise CaptchaUnavailable("CAPTCHA verification is temporarily unavailable")
    try:
        result = response.json()
    except ValueError as exc:
        raise CaptchaUnavailable("CAPTCHA verification returned an invalid response") from exc
    if not result.get("success"):
        raise ValueError("CAPTCHA verification failed; try again")
    if expected_action and result.get("action") != expected_action:
        raise ValueError("CAPTCHA verification failed; try again")
    expected_hostname = urlparse(_web_url()).hostname
    if hosted_mode() and expected_hostname and result.get("hostname") != expected_hostname:
        raise ValueError("CAPTCHA verification failed; try again")


def _web_url() -> str:
    return os.environ.get("VIDEOMEMORY_WEB_URL", "http://localhost:3000").rstrip("/")


async def _send_email(recipient: str, subject: str, heading: str, body: str, action: str, url: str) -> None:
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    sender = os.environ.get("VIDEOMEMORY_EMAIL_FROM", "").strip()
    if not api_key or not sender:
        raise EmailUnavailable("account email delivery is not configured")
    safe_heading = html.escape(heading)
    safe_body = html.escape(body)
    safe_action = html.escape(action)
    safe_url = html.escape(url, quote=True)
    email_html = f"""
    <div style="background:#0b0b0d;color:#f0eee8;font-family:Arial,sans-serif;padding:40px 20px">
      <div style="max-width:560px;margin:auto;border:1px solid #29282f;padding:32px">
        <p style="color:#aaa0ff;font-size:12px;letter-spacing:.12em">VIDEOMEMORY</p>
        <h1 style="font-size:28px;line-height:1.15">{safe_heading}</h1>
        <p style="color:#aaa7a0;line-height:1.65">{safe_body}</p>
        <a href="{safe_url}" style="display:inline-block;margin-top:16px;background:#f0eee8;color:#0b0b0d;padding:14px 20px;text-decoration:none;font-weight:700">{safe_action}</a>
        <p style="color:#68666f;font-size:12px;line-height:1.5;margin-top:28px">If you did not request this, you can safely ignore this email.</p>
      </div>
    </div>"""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            RESEND_EMAIL_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": sender,
                "to": [recipient],
                "subject": subject,
                "html": email_html,
                "text": f"{heading}\n\n{body}\n\n{action}: {url}",
            },
        )
    if response.status_code >= 400:
        raise EmailUnavailable("account email could not be delivered")


async def send_verification_email(recipient: str, token: str) -> None:
    url = f"{_web_url()}/verify-email?token={quote(token, safe='')}"
    await _send_email(
        recipient,
        "Verify your Videomemory email",
        "Verify your email",
        "Confirm this address to activate your account and create your private MCP key. This link expires in 24 hours.",
        "Verify email",
        url,
    )


async def send_password_reset_email(recipient: str, token: str) -> None:
    url = f"{_web_url()}/reset-password?token={quote(token, safe='')}"
    await _send_email(
        recipient,
        "Reset your Videomemory password",
        "Reset your password",
        "Use this one-time link to choose a new password. The link expires in 30 minutes and invalidates after use.",
        "Reset password",
        url,
    )


__all__ = [
    "CaptchaUnavailable",
    "EmailUnavailable",
    "email_verification_required",
    "send_password_reset_email",
    "send_verification_email",
    "verify_captcha",
]
