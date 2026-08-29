"""Tenant context for hosted Videomemory requests.

The local CLI keeps its historical single-library behaviour. Hosted requests set
an authenticated tenant id for the lifetime of the request; every filesystem and
SQLite lookup then resolves beneath that tenant's private directory.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path

_TENANT_RE = re.compile(r"^[a-zA-Z0-9_-]{8,96}$")
_tenant_id: ContextVar[str | None] = ContextVar("videomemory_tenant_id", default=None)


def current_tenant() -> str | None:
    return _tenant_id.get()


def validate_tenant_id(tenant_id: str) -> str:
    if not _TENANT_RE.fullmatch(tenant_id):
        raise ValueError("invalid tenant id")
    return tenant_id


def set_tenant(tenant_id: str) -> Token:
    return _tenant_id.set(validate_tenant_id(tenant_id))


def reset_tenant(token: Token) -> None:
    _tenant_id.reset(token)


@contextmanager
def tenant_scope(tenant_id: str):
    token = set_tenant(tenant_id)
    try:
        yield
    finally:
        reset_tenant(token)


def tenant_data_dir(root: Path, tenant_id: str | None = None) -> Path:
    tenant = validate_tenant_id(tenant_id or current_tenant() or "local-user")
    resolved_root = root.resolve()
    candidate = (resolved_root / "tenants" / tenant).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise ValueError("tenant path escaped data root")
    return candidate


__all__ = [
    "current_tenant",
    "reset_tenant",
    "set_tenant",
    "tenant_data_dir",
    "tenant_scope",
    "validate_tenant_id",
]
