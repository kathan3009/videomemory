"""Control-plane database for accounts, sessions, API keys, usage and jobs.

This database never stores raw passwords, session tokens or MCP API keys. User
video content remains in a separate tenant directory selected only after an
authenticated identity has been resolved.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from videomemory.config import data_root

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    plan TEXT NOT NULL DEFAULT 'free',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    session_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    user_agent_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS api_keys (
    key_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    prefix TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);

CREATE TABLE IF NOT EXISTS usage_events (
    event_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 1,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_events_user_time ON usage_events(user_id, created_at);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_user_created ON jobs(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS subscriptions (
    user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    provider_subscription_id TEXT UNIQUE,
    provider_customer_id TEXT,
    plan TEXT NOT NULL,
    status TEXT NOT NULL,
    current_period_end TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_events (
    provider_event_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    received_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

PLAN_LIMITS: dict[str, dict[str, int]] = {
    "free": {"videos": 5, "minutes": 60, "mcp_calls": 200, "api_keys": 1},
    "creator": {"videos": 100, "minutes": 1200, "mcp_calls": 5000, "api_keys": 5},
    "studio": {"videos": 1000, "minutes": 10000, "mcp_calls": 50000, "api_keys": 20},
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _control_path() -> Path:
    override = os.environ.get("VIDEOMEMORY_CONTROL_DB")
    path = Path(override) if override else data_root() / "control.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(_control_path(), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    try:
        con.executescript(SCHEMA)
        yield con
    finally:
        con.close()


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _password_hash(password: str) -> str:
    if len(password) < 10 or len(password) > 256:
        raise ValueError("password must be between 10 and 256 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def _password_matches(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, digest_hex = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p), dklen=32
        )
        return hmac.compare_digest(actual, bytes.fromhex(digest_hex))
    except (TypeError, ValueError):
        return False


def _public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": row["user_id"],
        "email": row["email"],
        "name": row["name"],
        "plan": row["plan"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def create_user(email: str, name: str, password: str) -> dict[str, Any]:
    email = email.strip().lower()
    name = " ".join(name.strip().split())
    if "@" not in email or len(email) > 254:
        raise ValueError("enter a valid email address")
    if not name or len(name) > 100:
        raise ValueError("enter your name")
    user_id = f"usr_{uuid.uuid4().hex}"
    now = _now()
    try:
        with connect() as con:
            con.execute(
                "INSERT INTO users (user_id,email,name,password_hash,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (user_id, email, name, _password_hash(password), now, now),
            )
            con.commit()
            row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    except sqlite3.IntegrityError as exc:
        raise ValueError("an account with this email already exists") from exc
    assert row is not None
    return _public_user(row)


def authenticate_user(email: str, password: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT * FROM users WHERE email=? COLLATE NOCASE", (email.strip(),)).fetchone()
    if row is None or row["status"] != "active" or not _password_matches(password, row["password_hash"]):
        return None
    return _public_user(row)


def get_user(user_id: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    return _public_user(row) if row else None


def create_session(user_id: str, user_agent: str = "", days: int = 30) -> str:
    token = secrets.token_urlsafe(48)
    now = datetime.now(UTC)
    expires = now + timedelta(days=days)
    ua_hash = _hash_secret(user_agent) if user_agent else None
    with connect() as con:
        con.execute(
            "INSERT INTO sessions (session_hash,user_id,expires_at,created_at,user_agent_hash) VALUES (?,?,?,?,?)",
            (_hash_secret(token), user_id, expires.isoformat(), now.isoformat(), ua_hash),
        )
        con.commit()
    return token


def user_for_session(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    with connect() as con:
        row = con.execute(
            """SELECT u.* FROM sessions s JOIN users u ON u.user_id=s.user_id
               WHERE s.session_hash=? AND s.expires_at>? AND u.status='active'""",
            (_hash_secret(token), _now()),
        ).fetchone()
    return _public_user(row) if row else None


def revoke_session(token: str | None) -> None:
    if not token:
        return
    with connect() as con:
        con.execute("DELETE FROM sessions WHERE session_hash=?", (_hash_secret(token),))
        con.commit()


def create_api_key(user_id: str, name: str = "Default") -> tuple[str, dict[str, Any]]:
    user = get_user(user_id)
    if user is None:
        raise ValueError("unknown user")
    limits = PLAN_LIMITS.get(user["plan"], PLAN_LIMITS["free"])
    with connect() as con:
        count = con.execute(
            "SELECT COUNT(*) FROM api_keys WHERE user_id=? AND revoked_at IS NULL", (user_id,)
        ).fetchone()[0]
        if count >= limits["api_keys"]:
            raise ValueError("API key limit reached for this plan")
        token = f"vm_live_{secrets.token_urlsafe(32)}"
        now = _now()
        prefix = token[:16]
        con.execute(
            "INSERT INTO api_keys (key_hash,user_id,name,prefix,created_at) VALUES (?,?,?,?,?)",
            (_hash_secret(token), user_id, name[:80] or "Default", prefix, now),
        )
        con.commit()
    return token, {"name": name[:80] or "Default", "prefix": prefix, "created_at": now}


def list_api_keys(user_id: str) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            "SELECT name,prefix,created_at,last_used_at FROM api_keys WHERE user_id=? AND revoked_at IS NULL ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def revoke_api_key(user_id: str, prefix: str) -> bool:
    with connect() as con:
        cur = con.execute(
            "UPDATE api_keys SET revoked_at=? WHERE user_id=? AND prefix=? AND revoked_at IS NULL",
            (_now(), user_id, prefix),
        )
        con.commit()
    return cur.rowcount > 0


def user_for_api_key(token: str | None) -> dict[str, Any] | None:
    if not token or not token.startswith("vm_live_"):
        return None
    key_hash = _hash_secret(token)
    now = _now()
    with connect() as con:
        row = con.execute(
            """SELECT u.* FROM api_keys k JOIN users u ON u.user_id=k.user_id
               WHERE k.key_hash=? AND k.revoked_at IS NULL AND u.status='active'""",
            (key_hash,),
        ).fetchone()
        if row:
            con.execute("UPDATE api_keys SET last_used_at=? WHERE key_hash=?", (now, key_hash))
            con.commit()
    return _public_user(row) if row else None


def record_usage(user_id: str, kind: str, quantity: float = 1, metadata: dict[str, Any] | None = None) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO usage_events (event_id,user_id,kind,quantity,metadata_json,created_at) VALUES (?,?,?,?,?,?)",
            (f"evt_{uuid.uuid4().hex}", user_id, kind, quantity, json.dumps(metadata or {}), _now()),
        )
        con.commit()


def usage_summary(user_id: str) -> dict[str, Any]:
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    with connect() as con:
        rows = con.execute(
            "SELECT kind, SUM(quantity) AS total FROM usage_events WHERE user_id=? AND created_at>=? GROUP BY kind",
            (user_id, start),
        ).fetchall()
    totals = {row["kind"]: row["total"] for row in rows}
    user = get_user(user_id)
    plan = user["plan"] if user else "free"
    return {"period_start": start, "plan": plan, "limits": PLAN_LIMITS[plan], "totals": totals}


def create_job(user_id: str, kind: str, source: str) -> dict[str, Any]:
    job_id = f"job_{uuid.uuid4().hex}"
    now = _now()
    with connect() as con:
        con.execute(
            "INSERT INTO jobs (job_id,user_id,kind,source,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (job_id, user_id, kind, source, "queued", now, now),
        )
        con.commit()
    return {"job_id": job_id, "kind": kind, "source": source, "status": "queued", "progress": 0, "created_at": now}


def update_job(job_id: str, user_id: str, **updates: Any) -> None:
    allowed = {"status", "progress", "result_json", "error"}
    fields = [(key, value) for key, value in updates.items() if key in allowed]
    if not fields:
        return
    fields.append(("updated_at", _now()))
    sql = ", ".join(f"{key}=?" for key, _ in fields)
    args = [value for _, value in fields] + [job_id, user_id]
    with connect() as con:
        con.execute(f"UPDATE jobs SET {sql} WHERE job_id=? AND user_id=?", args)
        con.commit()


def get_job(user_id: str, job_id: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT * FROM jobs WHERE user_id=? AND job_id=?", (user_id, job_id)).fetchone()
    if not row:
        return None
    result = dict(row)
    if result.get("result_json"):
        result["result"] = json.loads(result.pop("result_json"))
    return result


def list_jobs(user_id: str, limit: int = 25) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, min(limit, 100))
        ).fetchall()
    return [dict(row) for row in rows]


def find_active_job(user_id: str, source: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute(
            """SELECT * FROM jobs WHERE user_id=? AND source=? AND status IN ('queued','processing')
               ORDER BY created_at DESC LIMIT 1""",
            (user_id, source),
        ).fetchone()
    return dict(row) if row else None


def pending_jobs() -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM jobs WHERE status IN ('queued','processing') ORDER BY created_at"
        ).fetchall()
        con.execute("UPDATE jobs SET status='queued',progress=0,updated_at=? WHERE status='processing'", (_now(),))
        con.commit()
    return [{**dict(row), "status": "queued", "progress": 0} for row in rows]


def apply_subscription(
    user_id: str,
    *,
    provider_subscription_id: str,
    plan: str,
    status: str,
    current_period_end: str | None = None,
) -> None:
    if plan not in PLAN_LIMITS:
        raise ValueError("unknown plan")
    now = _now()
    with connect() as con:
        con.execute(
            """INSERT INTO subscriptions
               (user_id,provider,provider_subscription_id,plan,status,current_period_end,updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 provider_subscription_id=excluded.provider_subscription_id,
                 plan=excluded.plan,status=excluded.status,
                 current_period_end=excluded.current_period_end,updated_at=excluded.updated_at""",
            (user_id, "razorpay", provider_subscription_id, plan, status, current_period_end, now),
        )
        active_plan = plan if status in {"active", "authenticated"} else "free"
        con.execute("UPDATE users SET plan=?,updated_at=? WHERE user_id=?", (active_plan, now, user_id))
        con.commit()


def get_subscription(user_id: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT * FROM subscriptions WHERE user_id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def remember_webhook(provider_event_id: str) -> bool:
    try:
        with connect() as con:
            con.execute(
                "INSERT INTO webhook_events (provider_event_id,provider,received_at) VALUES (?,?,?)",
                (provider_event_id, "razorpay", _now()),
            )
            con.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_setting(key: str) -> str | None:
    with connect() as con:
        row = con.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with connect() as con:
        con.execute(
            """INSERT INTO app_settings (key,value,updated_at) VALUES (?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
            (key, value, _now()),
        )
        con.commit()


__all__ = [
    "PLAN_LIMITS",
    "apply_subscription",
    "authenticate_user",
    "connect",
    "create_api_key",
    "create_job",
    "create_session",
    "create_user",
    "get_job",
    "get_setting",
    "get_subscription",
    "get_user",
    "find_active_job",
    "list_api_keys",
    "list_jobs",
    "pending_jobs",
    "record_usage",
    "remember_webhook",
    "revoke_api_key",
    "revoke_session",
    "set_setting",
    "update_job",
    "usage_summary",
    "user_for_api_key",
    "user_for_session",
]
