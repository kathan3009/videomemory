"""Hosted Videomemory web API and authenticated Streamable HTTP MCP endpoint."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Match, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from videomemory.artifact_memory import artifact_memory as recall_artifacts
from videomemory.artifact_memory import remember_artifact
from videomemory.auth_services import (
    CaptchaUnavailable,
    EmailUnavailable,
    email_verification_required,
    send_password_reset_email,
    send_verification_email,
    verify_captcha,
)
from videomemory.billing import (
    BillingUnavailable,
    cancel_subscription,
    create_checkout_subscription,
    process_webhook,
    public_billing_config,
    verify_checkout_signature,
    verify_webhook,
)
from videomemory.config import (
    data_dir,
    data_root,
    frame_dir,
    hosted_mode,
    max_active_jobs,
    max_global_bytes,
    max_tenant_bytes,
    max_upload_bytes,
    media_process_timeout_seconds,
    video_dir,
)
from videomemory.control import (
    active_job_count,
    authenticate_user,
    create_api_key,
    create_auth_token,
    create_session,
    create_user,
    find_active_job,
    get_job,
    get_subscription,
    list_api_keys,
    list_jobs,
    record_usage,
    reset_password,
    revoke_api_key,
    revoke_session,
    usage_summary,
    user_for_api_key,
    user_for_email,
    user_for_session,
    verify_email,
)
from videomemory.control import (
    connect as control_connect,
)
from videomemory.ingest import video_id_for
from videomemory.jobs import enqueue_ingest, enqueue_upload, recover_pending_jobs, shutdown_jobs
from videomemory.library import delete_video, get_video, get_windows, is_index_ready, list_videos
from videomemory.mcp_server import build_server
from videomemory.memory_graph import add_note, graph_snapshot, recall_context, record_tool_memory
from videomemory.outbound_proxy import guarded_egress_proxy
from videomemory.search import search_video
from videomemory.tenant import reset_tenant, set_tenant, tenant_scope
from videomemory.url_safety import UnsafeURLError, validate_public_url

SESSION_COOKIE = "vm_session"
MAX_JSON_BYTES = 32 * 1024
UPLOAD_CONTENT_TYPES = {
    "audio/m4a": ".m4a",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
}


def _origins() -> list[str]:
    raw = os.environ.get("VIDEOMEMORY_WEB_ORIGINS", "http://localhost:3000")
    return [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]


def _allowed_hosts() -> list[str]:
    raw = os.environ.get("VIDEOMEMORY_ALLOWED_HOSTS", "")
    hosts = [item.strip() for item in raw.split(",") if item.strip()]
    railway = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if railway:
        hosts.extend([railway, f"{railway}:*"])
    if not hosts and not hosted_mode():
        hosts = ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*"]
    if not hosts:
        raise RuntimeError("VIDEOMEMORY_ALLOWED_HOSTS must name the public MCP hostname")
    return sorted(set(hosts))


async def _json(request: Request) -> dict[str, Any]:
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise ValueError("Content-Type must be application/json")
    body = await request.body()
    if len(body) > MAX_JSON_BYTES:
        raise ValueError("request body is too large")
    try:
        value = json.loads(body or b"{}")
    except json.JSONDecodeError as exc:
        raise ValueError("request body is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("request body must be a JSON object")
    return value


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _session_user(request: Request) -> dict[str, Any] | None:
    browser_token = request.headers.get("x-videomemory-session")
    return user_for_session(browser_token or request.cookies.get(SESSION_COOKIE))


def _require_user(request: Request) -> dict[str, Any]:
    user = _session_user(request)
    if not user:
        raise PermissionError("sign in to continue")
    return user


def _require_browser_origin(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin", "").rstrip("/")
    if hosted_mode() and origin not in _origins():
        raise PermissionError("request origin is not allowed")


def _set_session(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        secure=hosted_mode(),
        samesite="none" if hosted_mode() else "lax",
        path="/",
        domain=os.environ.get("VIDEOMEMORY_COOKIE_DOMAIN") or None,
    )


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                        # The browser dashboard is intentionally hosted on a separate
                        # Sites origin; CORS still restricts which origins may read it.
                        (b"cross-origin-resource-policy", b"cross-origin"),
                    ]
                )
                if hosted_mode():
                    headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RateLimitMiddleware:
    """Small per-process abuse brake; Railway remains the outer DDoS boundary."""

    def __init__(self, app: ASGIApp, limit: int = 120, window: int = 60):
        self.app = app
        self.limit = limit
        self.window = window
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        request_headers = dict(scope.get("headers", []))
        trust_proxy = os.environ.get("VIDEOMEMORY_TRUST_PROXY_HEADERS", "0").lower() in {"1", "true", "yes"}
        forwarded = (request_headers.get(b"cf-connecting-ip") or request_headers.get(b"x-forwarded-for")) if trust_proxy else None
        key = forwarded.decode(errors="ignore") if forwarded else (client[0] if client else "unknown")
        key = key.split(",", 1)[0].strip()
        request_limit = 10 if str(scope.get("path", "")).startswith("/api/auth/") else self.limit
        now = time.monotonic()
        if len(self.hits) > 10_000:
            self.hits = defaultdict(
                deque,
                {
                    address: times
                    for address, times in self.hits.items()
                    if times and times[-1] >= now - self.window
                },
            )
        bucket = self.hits[key]
        while bucket and bucket[0] < now - self.window:
            bucket.popleft()
        if len(bucket) >= request_limit:
            await JSONResponse({"error": "rate limit exceeded"}, status_code=429)(scope, receive, send)
            return
        bucket.append(now)
        await self.app(scope, receive, send)


class AuthenticatedMCP:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        auth = headers.get(b"authorization", b"").decode(errors="ignore")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
        user = user_for_api_key(token)
        if not user:
            await JSONResponse(
                {"error": "valid Videomemory bearer token required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
            return
        usage = usage_summary(user["user_id"])
        if usage["totals"].get("mcp_calls", 0) >= usage["limits"]["mcp_calls"]:
            await JSONResponse({"error": "monthly MCP call limit reached"}, status_code=429)(scope, receive, send)
            return
        tenant_token = set_tenant(user["user_id"])
        try:
            await self.app(scope, receive, send)
        finally:
            reset_tenant(tenant_token)


class ExactASGIRoute(BaseRoute):
    """Route an ASGI app without Starlette's automatic trailing-slash redirect."""

    def __init__(self, path: str, app: ASGIApp):
        self.path = path
        self.app = app

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope["type"] == "http" and scope.get("path") in {self.path, f"{self.path}/"}:
            return Match.FULL, {"endpoint": self.app}
        return Match.NONE, {}

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)


async def health(_: Request) -> JSONResponse:
    checks: dict[str, bool] = {"database": False, "storage": False}
    try:
        with control_connect() as con:
            con.execute("SELECT 1").fetchone()
        checks["database"] = True
        root = data_root()
        checks["storage"] = os.access(root, os.W_OK) and shutil.disk_usage(root).free > 20 * 1024 * 1024
    except OSError:
        pass
    ready = all(checks.values())
    return JSONResponse(
        {"status": "ok" if ready else "not_ready", "service": "videomemory", "version": "1.0.0", "checks": checks},
        status_code=200 if ready else 503,
    )


async def signup(request: Request) -> JSONResponse:
    try:
        _require_browser_origin(request)
        data = await _json(request)
        await verify_captcha(
            str(data.get("captcha_token", "")), request.client.host if request.client else None, "signup"
        )
        user = create_user(str(data.get("email", "")), str(data.get("name", "")), str(data.get("password", "")))
        if email_verification_required():
            token = create_auth_token(user["user_id"], "verify_email", 24 * 60)
            await send_verification_email(user["email"], token)
            return JSONResponse(
                {"user": user, "verification_required": True, "message": "Check your email to activate your account."},
                status_code=202,
            )
        api_key, key_info = create_api_key(user["user_id"], "Default MCP key")
        session = create_session(user["user_id"], request.headers.get("user-agent", ""))
        response = JSONResponse(
            {"user": user, "api_key": api_key, "key": key_info, "session_token": session}, status_code=201
        )
        _set_session(response, session)
        return response
    except ValueError as exc:
        return _error(str(exc))
    except (CaptchaUnavailable, EmailUnavailable) as exc:
        return _error(str(exc), 503)
    except PermissionError as exc:
        return _error(str(exc), 403)


async def login(request: Request) -> JSONResponse:
    try:
        _require_browser_origin(request)
        data = await _json(request)
        await verify_captcha(
            str(data.get("captcha_token", "")), request.client.host if request.client else None, "login"
        )
        user = authenticate_user(str(data.get("email", "")), str(data.get("password", "")))
        if not user:
            return _error("email or password is incorrect", 401)
        if email_verification_required() and not user.get("email_verified"):
            token = create_auth_token(user["user_id"], "verify_email", 24 * 60)
            await send_verification_email(user["email"], token)
            return _error("verify your email before signing in; we sent a new link", 403)
        session = create_session(user["user_id"], request.headers.get("user-agent", ""))
        response = JSONResponse({"user": user, "session_token": session})
        _set_session(response, session)
        return response
    except (ValueError, PermissionError) as exc:
        return _error(str(exc), 400 if isinstance(exc, ValueError) else 403)
    except (CaptchaUnavailable, EmailUnavailable) as exc:
        return _error(str(exc), 503)


async def confirm_email(request: Request) -> JSONResponse:
    try:
        _require_browser_origin(request)
        data = await _json(request)
        user = verify_email(str(data.get("token", "")))
        api_key, key_info = create_api_key(user["user_id"], "Default MCP key")
        session = create_session(user["user_id"], request.headers.get("user-agent", ""))
        response = JSONResponse({"user": user, "api_key": api_key, "key": key_info, "session_token": session})
        _set_session(response, session)
        return response
    except PermissionError as exc:
        return _error(str(exc), 403)
    except ValueError as exc:
        return _error(str(exc))


async def forgot_password(request: Request) -> JSONResponse:
    try:
        _require_browser_origin(request)
        data = await _json(request)
        await verify_captcha(
            str(data.get("captcha_token", "")), request.client.host if request.client else None, "recover"
        )
        user = user_for_email(str(data.get("email", "")))
        background = None
        if user:
            token = create_auth_token(user["user_id"], "reset_password", 30)
            background = BackgroundTask(_deliver_password_reset, user["email"], token)
        return JSONResponse(
            {"ok": True, "message": "If that account exists, a reset link is on its way."},
            status_code=202,
            background=background,
        )
    except (ValueError, PermissionError) as exc:
        return _error(str(exc), 400 if isinstance(exc, ValueError) else 403)
    except CaptchaUnavailable as exc:
        return _error(str(exc), 503)


async def _deliver_password_reset(email: str, token: str) -> None:
    try:
        await send_password_reset_email(email, token)
    except EmailUnavailable:
        return


async def complete_password_reset(request: Request) -> JSONResponse:
    try:
        _require_browser_origin(request)
        data = await _json(request)
        reset_password(str(data.get("token", "")), str(data.get("password", "")))
        return JSONResponse({"ok": True, "message": "Password updated. Sign in with your new password."})
    except PermissionError as exc:
        return _error(str(exc), 403)
    except ValueError as exc:
        return _error(str(exc))


async def logout(request: Request) -> JSONResponse:
    try:
        _require_browser_origin(request)
        revoke_session(request.headers.get("x-videomemory-session") or request.cookies.get(SESSION_COOKIE))
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE, path="/", domain=os.environ.get("VIDEOMEMORY_COOKIE_DOMAIN") or None)
        return response
    except PermissionError as exc:
        return _error(str(exc), 403)


def _account_payload(user: dict[str, Any]) -> dict[str, Any]:
    with tenant_scope(user["user_id"]):
        videos = []
        for video in list_videos():
            videos.append(_public_video(video.model_dump(mode="json")))
    return {
        "user": user,
        "usage": usage_summary(user["user_id"]),
        "api_keys": list_api_keys(user["user_id"]),
        "videos": videos,
        "jobs": [_public_job(job) for job in list_jobs(user["user_id"])],
        "billing": {**public_billing_config(), "subscription": get_subscription(user["user_id"])},
    }


async def account(request: Request) -> JSONResponse:
    try:
        return JSONResponse(_account_payload(_require_user(request)))
    except PermissionError as exc:
        return _error(str(exc), 401)


async def create_key(request: Request) -> JSONResponse:
    try:
        _require_browser_origin(request)
        user = _require_user(request)
        data = await _json(request)
        token, info = create_api_key(user["user_id"], str(data.get("name", "MCP key")))
        return JSONResponse({"api_key": token, "key": info}, status_code=201)
    except PermissionError as exc:
        return _error(str(exc), 401)
    except ValueError as exc:
        return _error(str(exc))


async def delete_key(request: Request) -> JSONResponse:
    try:
        _require_browser_origin(request)
        user = _require_user(request)
        if not revoke_api_key(user["user_id"], request.path_params["prefix"]):
            return _error("API key not found", 404)
        return JSONResponse({"ok": True})
    except PermissionError as exc:
        return _error(str(exc), 401)


async def add_video(request: Request) -> JSONResponse:
    try:
        _require_browser_origin(request)
        user = _require_user(request)
        if active_job_count() >= max_active_jobs():
            return _error("processing queue is full; try again shortly", 503)
        data = await _json(request)
        source = await validate_public_url(str(data.get("url", "")))
        active = find_active_job(user["user_id"], source)
        if active:
            return JSONResponse({"job": active}, status_code=202)
        with tenant_scope(user["user_id"]):
            existing = get_video(video_id_for(source))
        if existing and is_index_ready(existing.video_id):
            return JSONResponse({"video": existing.model_dump(mode="json"), "already_indexed": True})
        usage = usage_summary(user["user_id"])
        queued = active_job_count(user["user_id"])
        if usage["totals"].get("videos", 0) + queued >= usage["limits"]["videos"]:
            return _error("monthly video limit reached", 402)
        return JSONResponse({"job": enqueue_ingest(user["user_id"], source)}, status_code=202)
    except PermissionError as exc:
        return _error(str(exc), 401)
    except (ValueError, UnsafeURLError) as exc:
        return _error(str(exc))


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    public = dict(job)
    if public.get("kind") == "upload":
        path = Path(str(public["source"]))
        sidecar = path.with_suffix(".name")
        name = sidecar.read_text().strip() if sidecar.is_file() else path.name
        public["source"] = f"upload://{name}"
    return public


def _public_video(video: dict[str, Any]) -> dict[str, Any]:
    public = dict(video)
    if not str(public.get("source", "")).startswith(("http://", "https://")):
        path = Path(str(public.get("source", "upload")))
        sidecar = path.with_suffix(".name")
        name = sidecar.read_text().strip() if sidecar.is_file() else path.name
        public["source"] = f"upload://{name}"
    public.pop("file_path", None)
    return public


def _quota_allows_video(user_id: str) -> bool:
    usage = usage_summary(user_id)
    queued = active_job_count(user_id)
    return usage["totals"].get("videos", 0) + queued < usage["limits"]["videos"]


def _tree_bytes(root: Path) -> int:
    total = 0
    for item in root.rglob("*"):
        if item.is_file():
            with contextlib.suppress(OSError):
                total += item.stat().st_size
    return total


async def _validate_media(path: Path) -> None:
    """Reject mislabeled or corrupt input before admitting work to the queue."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe,crypto,data",
        "-show_entries", "format=duration", "-of", "csv=p=0", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=min(30, media_process_timeout_seconds()))
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise ValueError("uploaded media validation timed out") from exc
    if proc.returncode != 0 or not out.strip():
        raise ValueError("uploaded file is not valid playable media")


async def upload_video(request: Request) -> JSONResponse:
    """Stream one authenticated media upload into the caller's private tenant volume."""
    destination: Path | None = None
    try:
        _require_browser_origin(request)
        user = _require_user(request)
        if active_job_count() >= max_active_jobs():
            return _error("processing queue is full; try again shortly", 503)
        if not _quota_allows_video(user["user_id"]):
            return _error("monthly video limit reached", 402)
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        suffix = UPLOAD_CONTENT_TYPES.get(content_type)
        if not suffix:
            return _error("upload an MP4, MOV, WebM, MKV, MP3, M4A, or WAV file", 415)
        declared = request.headers.get("content-length")
        if declared:
            try:
                if int(declared) > max_upload_bytes():
                    return _error("uploaded file is too large", 413)
            except ValueError:
                return _error("invalid Content-Length header")
        with tenant_scope(user["user_id"]):
            uploads = data_dir() / "uploads"
            uploads.mkdir(parents=True, exist_ok=True)
            supplied_name = request.headers.get("x-videomemory-filename", "upload")
            safe_stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", Path(supplied_name).stem).strip("-._")[:60] or "upload"
            destination = (uploads / f"pending_{uuid.uuid4().hex}{suffix}").resolve()
            if not destination.is_relative_to(uploads.resolve()):
                raise ValueError("upload path is invalid")
            starting_bytes = _tree_bytes(data_dir())
            starting_global_bytes = _tree_bytes(data_root())
            total = 0
            digest = hashlib.sha256()
            with destination.open("xb") as handle:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > max_upload_bytes():
                        raise OverflowError("uploaded file is too large")
                    if starting_bytes + total > max_tenant_bytes():
                        raise OverflowError("tenant storage limit reached")
                    if starting_global_bytes + total > max_global_bytes():
                        raise OverflowError("service storage is temporarily full")
                    digest.update(chunk)
                    handle.write(chunk)
            if total == 0:
                raise ValueError("uploaded file is empty")
            await _validate_media(destination)
            digest_hex = digest.hexdigest()
            existing_match = next(
                (item for item in uploads.glob(f"{digest_hex}.*") if item.suffix != ".name" and item.is_file()),
                None,
            )
            final = existing_match or (uploads / f"{digest_hex}{suffix}").resolve()
            if existing_match:
                destination.unlink(missing_ok=True)
            else:
                destination.replace(final)
                final.with_suffix(".name").write_text(f"{safe_stem}{suffix}")
            destination = final
            active = find_active_job(user["user_id"], str(destination))
            if active:
                return JSONResponse({"job": _public_job(active)}, status_code=202)
            existing = get_video(video_id_for(str(destination), file_path=destination))
            if existing and is_index_ready(existing.video_id):
                return JSONResponse({"video": _public_video(existing.model_dump(mode="json")), "already_indexed": True})
        return JSONResponse(
            {"job": _public_job(enqueue_upload(user["user_id"], str(destination)))}, status_code=202
        )
    except PermissionError as exc:
        return _error(str(exc), 401)
    except OverflowError as exc:
        if destination:
            destination.unlink(missing_ok=True)
        return _error(str(exc), 413)
    except (OSError, ValueError) as exc:
        if destination:
            destination.unlink(missing_ok=True)
        return _error(str(exc))


async def job_detail(request: Request) -> JSONResponse:
    try:
        user = _require_user(request)
        job = get_job(user["user_id"], request.path_params["job_id"])
        return JSONResponse({"job": _public_job(job)}) if job else _error("job not found", 404)
    except PermissionError as exc:
        return _error(str(exc), 401)


async def video_detail(request: Request) -> JSONResponse:
    try:
        user = _require_user(request)
        video_id = request.path_params["video_id"]
        with tenant_scope(user["user_id"]):
            video = get_video(video_id)
            if not video:
                return _error("video not found", 404)
            windows = [window.model_dump(mode="json") for window in get_windows(video_id)]
        return JSONResponse({"video": _public_video(video.model_dump(mode="json")), "transcript": windows})
    except PermissionError as exc:
        return _error(str(exc), 401)


async def ask_video(request: Request) -> JSONResponse:
    try:
        _require_browser_origin(request)
        user = _require_user(request)
        data = await _json(request)
        question = " ".join(str(data.get("question", "")).split())
        if not question or len(question) > 500:
            raise ValueError("enter a question up to 500 characters")
        video_id = request.path_params["video_id"]
        with tenant_scope(user["user_id"]):
            if not get_video(video_id):
                return _error("video not found", 404)
            hits = await asyncio.to_thread(search_video, video_id, question, top_k=5)
            payload = [hit.model_dump(mode="json") for hit in hits]
            for item in payload:
                if not str(item.get("source", "")).startswith(("http://", "https://")):
                    item["source"] = "upload://private-media"
                    item["deep_link"] = None
            record_tool_memory("dashboard_search", {"query": question}, {"hits": payload})
        record_usage(user["user_id"], "mcp_calls", 1, {"tool": "dashboard_search"})
        return JSONResponse({"hits": payload})
    except PermissionError as exc:
        return _error(str(exc), 401)
    except ValueError as exc:
        return _error(str(exc))


async def remove_video(request: Request) -> JSONResponse:
    try:
        _require_browser_origin(request)
        user = _require_user(request)
        video_id = request.path_params["video_id"]
        with tenant_scope(user["user_id"]):
            video = get_video(video_id)
            if not video:
                return _error("video not found", 404)
            source = Path(video.source) if not str(video.source).startswith(("http://", "https://")) else None
            delete_video(video_id)
            shutil.rmtree(video_dir(video_id), ignore_errors=True)
            shutil.rmtree(frame_dir(video_id), ignore_errors=True)
            if source and source.is_relative_to((data_dir() / "uploads").resolve()):
                source.unlink(missing_ok=True)
                source.with_suffix(".name").unlink(missing_ok=True)
        return JSONResponse({"ok": True})
    except PermissionError as exc:
        return _error(str(exc), 401)


async def memory_graph(request: Request) -> JSONResponse:
    try:
        user = _require_user(request)
        query = request.query_params.get("q", "").strip()
        limit = min(int(request.query_params.get("limit", "80")), 200)
        with tenant_scope(user["user_id"]):
            payload = recall_context(query, limit) if query else graph_snapshot(limit)
        return JSONResponse(payload)
    except PermissionError as exc:
        return _error(str(exc), 401)
    except ValueError as exc:
        return _error(str(exc))


async def create_note(request: Request) -> JSONResponse:
    try:
        _require_browser_origin(request)
        user = _require_user(request)
        data = await _json(request)
        with tenant_scope(user["user_id"]):
            note = add_note(
                str(data.get("video_id", "")),
                str(data.get("title", "")),
                str(data.get("body", "")),
                str(data["parent_note_id"]) if data.get("parent_note_id") else None,
            )
        return JSONResponse({"note": note}, status_code=201)
    except PermissionError as exc:
        return _error(str(exc), 401)
    except ValueError as exc:
        return _error(str(exc))


async def artifacts(request: Request) -> JSONResponse:
    try:
        user = _require_user(request)
        with tenant_scope(user["user_id"]):
            if request.method == "GET":
                return JSONResponse(recall_artifacts(request.query_params.get("q", ""), limit=50))
            _require_browser_origin(request)
            data = await _json(request)
            item = remember_artifact(
                title=str(data.get("title", "")),
                locator=str(data.get("locator", "")),
                kind=str(data.get("kind", "other")),
                access_instructions=str(data.get("access_instructions", "")),
                summary=str(data.get("summary", "")),
                content=str(data.get("content", "")),
                project=str(data.get("project", "")),
                agent="dashboard",
                parent_artifact_id=str(data["parent_artifact_id"]) if data.get("parent_artifact_id") else None,
                metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
            )
        return JSONResponse({"artifact": item}, status_code=201)
    except PermissionError as exc:
        return _error(str(exc), 401)
    except ValueError as exc:
        return _error(str(exc))


async def billing_checkout(request: Request) -> JSONResponse:
    try:
        _require_browser_origin(request)
        user = _require_user(request)
        data = await _json(request)
        return JSONResponse(await create_checkout_subscription(user, str(data.get("plan", ""))))
    except PermissionError as exc:
        return _error(str(exc), 401)
    except (ValueError, BillingUnavailable) as exc:
        return _error(str(exc), 503 if isinstance(exc, BillingUnavailable) else 400)


async def billing_verify(request: Request) -> JSONResponse:
    try:
        _require_browser_origin(request)
        _require_user(request)
        data = await _json(request)
        valid = verify_checkout_signature(
            str(data.get("razorpay_payment_id", "")),
            str(data.get("razorpay_subscription_id", "")),
            str(data.get("razorpay_signature", "")),
        )
        return JSONResponse({"verified": valid}, status_code=200 if valid else 400)
    except PermissionError as exc:
        return _error(str(exc), 401)
    except (ValueError, BillingUnavailable) as exc:
        return _error(str(exc))


async def billing_cancel(request: Request) -> JSONResponse:
    try:
        _require_browser_origin(request)
        user = _require_user(request)
        return JSONResponse(await cancel_subscription(user["user_id"]))
    except PermissionError as exc:
        return _error(str(exc), 401)
    except (ValueError, BillingUnavailable) as exc:
        return _error(str(exc), 503 if isinstance(exc, BillingUnavailable) else 400)


async def razorpay_webhook(request: Request) -> JSONResponse:
    body = await request.body()
    if len(body) > 256 * 1024:
        return _error("webhook body is too large", 413)
    if not verify_webhook(body, request.headers.get("x-razorpay-signature")):
        return _error("invalid webhook signature", 401)
    process_webhook(body, request.headers.get("x-razorpay-event-id"))
    return JSONResponse({"ok": True})


server = build_server()
security = TransportSecuritySettings(allowed_hosts=_allowed_hosts(), allowed_origins=_origins())
session_manager = StreamableHTTPSessionManager(
    server,
    stateless=True,
    json_response=True,
    security_settings=security,
)


@contextlib.asynccontextmanager
async def lifespan(_: Starlette) -> AsyncIterator[None]:
    if not hosted_mode():
        async with session_manager.run():
            recover_pending_jobs()
            yield
        await shutdown_jobs()
        return
    async with guarded_egress_proxy() as proxy:
        os.environ["VIDEOMEMORY_EGRESS_PROXY"] = proxy
        try:
            async with session_manager.run():
                recover_pending_jobs()
                yield
        finally:
            await shutdown_jobs()
            os.environ.pop("VIDEOMEMORY_EGRESS_PROXY", None)


routes = [
    Route("/health", health, methods=["GET"]),
    Route("/api/auth/signup", signup, methods=["POST"]),
    Route("/api/auth/login", login, methods=["POST"]),
    Route("/api/auth/verify-email", confirm_email, methods=["POST"]),
    Route("/api/auth/forgot-password", forgot_password, methods=["POST"]),
    Route("/api/auth/reset-password", complete_password_reset, methods=["POST"]),
    Route("/api/auth/logout", logout, methods=["POST"]),
    Route("/api/account", account, methods=["GET"]),
    Route("/api/keys", create_key, methods=["POST"]),
    Route("/api/keys/{prefix:str}", delete_key, methods=["DELETE"]),
    Route("/api/videos", add_video, methods=["POST"]),
    Route("/api/uploads", upload_video, methods=["POST"]),
    Route("/api/videos/{video_id:str}", video_detail, methods=["GET"]),
    Route("/api/videos/{video_id:str}", remove_video, methods=["DELETE"]),
    Route("/api/videos/{video_id:str}/ask", ask_video, methods=["POST"]),
    Route("/api/jobs/{job_id:str}", job_detail, methods=["GET"]),
    Route("/api/memory", memory_graph, methods=["GET"]),
    Route("/api/memory/notes", create_note, methods=["POST"]),
    Route("/api/artifacts", artifacts, methods=["GET", "POST"]),
    Route("/api/billing/checkout", billing_checkout, methods=["POST"]),
    Route("/api/billing/verify", billing_verify, methods=["POST"]),
    Route("/api/billing/cancel", billing_cancel, methods=["POST"]),
    Route("/api/webhooks/razorpay", razorpay_webhook, methods=["POST"]),
    ExactASGIRoute("/mcp", AuthenticatedMCP(session_manager.handle_request)),
]

middleware = [
    Middleware(SecurityHeadersMiddleware),
    Middleware(RateLimitMiddleware),
    Middleware(
        CORSMiddleware,
        allow_origins=_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Mcp-Session-Id",
            "MCP-Protocol-Version",
            "X-Videomemory-Session",
            "X-Videomemory-Filename",
        ],
        expose_headers=["Mcp-Session-Id"],
    ),
]

app = Starlette(debug=not hosted_mode(), routes=routes, middleware=middleware, lifespan=lifespan)


__all__ = ["app"]
