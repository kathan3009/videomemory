"""Razorpay subscription integration with signature-verified state changes."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

import httpx

from videomemory.control import (
    apply_subscription,
    get_setting,
    get_subscription,
    remember_webhook,
    set_setting,
    webhook_seen,
)

RAZORPAY_API = "https://api.razorpay.com/v1"
PAID_PLANS: dict[str, dict[str, Any]] = {
    "creator": {"name": "Videomemory Creator", "amount": 1200, "currency": "USD"},
    "studio": {"name": "Videomemory Studio", "amount": 2900, "currency": "USD"},
}


class BillingUnavailable(RuntimeError):
    pass


def public_billing_config() -> dict[str, Any]:
    required = (
        os.environ.get("RAZORPAY_KEY_ID"),
        os.environ.get("RAZORPAY_KEY_SECRET"),
        os.environ.get("RAZORPAY_WEBHOOK_SECRET"),
    )
    return {
        "provider": "razorpay",
        "key_id": os.environ.get("RAZORPAY_KEY_ID", ""),
        "enabled": all(required),
        "plans": PAID_PLANS,
    }


def _credentials() -> tuple[str, str]:
    key_id = os.environ.get("RAZORPAY_KEY_ID")
    secret = os.environ.get("RAZORPAY_KEY_SECRET")
    if not key_id or not secret:
        raise BillingUnavailable("billing is not configured yet")
    return key_id, secret


async def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    key_id, secret = _credentials()
    async with httpx.AsyncClient(timeout=20, auth=(key_id, secret)) as client:
        response = await client.request(method, f"{RAZORPAY_API}{path}", json=payload)
    if response.status_code >= 400:
        detail = response.json().get("error", {}).get("description", "Razorpay request failed")
        raise BillingUnavailable(detail)
    return response.json()


async def ensure_provider_plan(plan: str) -> str:
    if plan not in PAID_PLANS:
        raise ValueError("unknown paid plan")
    env_id = os.environ.get(f"RAZORPAY_PLAN_{plan.upper()}")
    if env_id:
        return env_id
    setting_key = f"razorpay_plan_{plan}"
    stored = get_setting(setting_key)
    if stored:
        return stored
    spec = PAID_PLANS[plan]
    created = await _request(
        "POST",
        "/plans",
        {
            "period": "monthly",
            "interval": 1,
            "item": {
                "name": spec["name"],
                "description": f"Monthly {spec['name']} subscription",
                "amount": spec["amount"],
                "currency": spec["currency"],
            },
            "notes": {"product": "videomemory", "plan": plan},
        },
    )
    set_setting(setting_key, created["id"])
    return created["id"]


async def create_checkout_subscription(user: dict[str, Any], plan: str) -> dict[str, Any]:
    provider_plan_id = await ensure_provider_plan(plan)
    subscription = await _request(
        "POST",
        "/subscriptions",
        {
            "plan_id": provider_plan_id,
            "total_count": 120,
            "quantity": 1,
            "customer_notify": 1,
            "notes": {"user_id": user["user_id"], "plan": plan, "email": user["email"]},
        },
    )
    apply_subscription(
        user["user_id"],
        provider_subscription_id=subscription["id"],
        plan=plan,
        status=subscription.get("status", "created"),
    )
    return {
        "subscription_id": subscription["id"],
        "plan": plan,
        "amount": PAID_PLANS[plan]["amount"],
        "currency": PAID_PLANS[plan]["currency"],
        "key_id": _credentials()[0],
        "customer": {"name": user["name"], "email": user["email"]},
    }


async def cancel_subscription(user_id: str) -> dict[str, Any]:
    subscription = get_subscription(user_id)
    if not subscription or not subscription.get("provider_subscription_id"):
        raise ValueError("no paid subscription was found")
    result = await _request(
        "POST",
        f"/subscriptions/{subscription['provider_subscription_id']}/cancel",
        {"cancel_at_cycle_end": 1},
    )
    return {
        "subscription_id": result.get("id", subscription["provider_subscription_id"]),
        "status": result.get("status", subscription["status"]),
        "cancel_at_cycle_end": bool(result.get("cancel_at_cycle_end", True)),
    }


def verify_checkout_signature(payment_id: str, subscription_id: str, signature: str) -> bool:
    _, secret = _credentials()
    expected = hmac.new(secret.encode(), f"{payment_id}|{subscription_id}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_webhook(body: bytes, signature: str | None) -> bool:
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET")
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def process_webhook(body: bytes, event_id: str | None = None) -> bool:
    fingerprint = event_id or hashlib.sha256(body).hexdigest()
    if webhook_seen(fingerprint):
        return False
    payload = json.loads(body)
    event = payload.get("event", "")
    entity = payload.get("payload", {}).get("subscription", {}).get("entity", {})
    notes = entity.get("notes") or {}
    user_id = notes.get("user_id")
    plan = notes.get("plan")
    if not user_id or plan not in PAID_PLANS:
        remember_webhook(fingerprint)
        return True
    status = entity.get("status") or event.removeprefix("subscription.")
    period_end = entity.get("current_end")
    created_at = payload.get("created_at")
    try:
        provider_event_created_at = int(created_at) if created_at is not None else None
    except (TypeError, ValueError):
        provider_event_created_at = None
    apply_subscription(
        user_id,
        provider_subscription_id=entity.get("id", "unknown"),
        plan=plan,
        status=status,
        current_period_end=str(period_end) if period_end else None,
        provider_event_created_at=provider_event_created_at,
    )
    remember_webhook(fingerprint)
    return True


__all__ = [
    "BillingUnavailable",
    "PAID_PLANS",
    "cancel_subscription",
    "create_checkout_subscription",
    "process_webhook",
    "public_billing_config",
    "verify_checkout_signature",
    "verify_webhook",
]
