"""Small fail-closed HTTP CONNECT proxy for hosted downloader egress.

Each requested hostname is resolved by the proxy and the chosen socket is
opened directly to a verified public IP. This closes the DNS-rebinding gap
between URL validation and yt-dlp/HTTP client connections.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import ssl
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

from videomemory.url_safety import DEFAULT_PORTS, UnsafeURLError, resolve_public_addresses

MAX_HEADER_BYTES = 64 * 1024


@dataclass(frozen=True)
class UpstreamProxy:
    scheme: str
    host: str
    port: int
    authorization: str | None = field(repr=False)


def _upstream_proxy() -> UpstreamProxy | None:
    """Parse the optional dedicated egress proxy without retaining its URL."""
    raw = os.environ.get("VIDEOMEMORY_UPSTREAM_PROXY", "").strip()
    if not raw:
        return None
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("VIDEOMEMORY_UPSTREAM_PROXY must be an http(s) proxy URL")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("VIDEOMEMORY_UPSTREAM_PROXY must not contain a path, query, or fragment")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("VIDEOMEMORY_UPSTREAM_PROXY has an invalid port") from exc
    authorization = None
    if parsed.username is not None:
        credentials = f"{unquote(parsed.username)}:{unquote(parsed.password or '')}".encode()
        authorization = "Basic " + base64.b64encode(credentials).decode("ascii")
    return UpstreamProxy(parsed.scheme, parsed.hostname, port, authorization)


def _allowed_port(port: int) -> bool:
    extras = {
        int(value)
        for value in os.environ.get("VIDEOMEMORY_ALLOWED_URL_PORTS", "").split(",")
        if value.strip().isdigit()
    }
    return port in DEFAULT_PORTS | extras


def _host_port(target: str, default_port: int) -> tuple[str, int]:
    parsed = urlsplit(f"//{target}")
    if not parsed.hostname:
        raise UnsafeURLError("proxy destination has no hostname")
    try:
        port = parsed.port or default_port
    except ValueError as exc:
        raise UnsafeURLError("proxy destination has an invalid port") from exc
    if not _allowed_port(port):
        raise UnsafeURLError("proxy destination port is not allowed")
    return parsed.hostname, port


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while chunk := await reader.read(64 * 1024):
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        with contextlib.suppress(Exception):
            writer.close()


async def _open_public_socket(
    host: str, port: int, *, tls: bool = False
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    addresses = _ordered_addresses(await resolve_public_addresses(host, port))
    last_error: Exception | None = None
    for address in addresses:
        try:
            return await asyncio.wait_for(
                asyncio.open_connection(
                    address,
                    port,
                    ssl=ssl.create_default_context() if tls else None,
                    server_hostname=host if tls else None,
                ),
                timeout=15,
            )
        except (OSError, TimeoutError) as exc:
            last_error = exc
    raise ConnectionError(f"could not connect to public destination: {host}") from last_error


def _authority(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def _ordered_addresses(addresses: list[str]) -> list[str]:
    prefer_ipv6 = os.environ.get("VIDEOMEMORY_PREFER_IPV6", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return sorted(addresses, key=lambda address: (":" not in address, address)) if prefer_ipv6 else addresses


async def _proxy_connect(
    proxy: UpstreamProxy, destination: str, port: int
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await _open_public_socket(proxy.host, proxy.port, tls=proxy.scheme == "https")
    authority = _authority(destination, port)
    request = [
        f"CONNECT {authority} HTTP/1.1\r\n",
        f"Host: {authority}\r\n",
        "Proxy-Connection: Keep-Alive\r\n",
    ]
    if proxy.authorization:
        request.append(f"Proxy-Authorization: {proxy.authorization}\r\n")
    request.append("\r\n")
    writer.write("".join(request).encode("latin-1"))
    await writer.drain()
    try:
        status_line = await asyncio.wait_for(reader.readline(), timeout=15)
        total = len(status_line)
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=15)
            total += len(line)
            if total > MAX_HEADER_BYTES:
                raise ConnectionError("upstream proxy response headers are too large")
            if line in {b"\r\n", b"\n", b""}:
                break
        parts = status_line.decode("latin-1", errors="replace").split(" ", 2)
        if len(parts) < 2 or parts[1] != "200":
            raise ConnectionError("upstream proxy refused the destination")
        return reader, writer
    except Exception:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        raise


async def _connect_public(host: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    addresses = _ordered_addresses(await resolve_public_addresses(host, port))
    proxy = _upstream_proxy()
    if proxy is None:
        return await _open_public_socket(host, port)
    last_error: Exception | None = None
    # CONNECT to the validated address, not a hostname the upstream proxy can
    # re-resolve. TLS still carries the original SNI inside the tunnel.
    for address in addresses:
        try:
            return await _proxy_connect(proxy, address, port)
        except (ConnectionError, OSError, TimeoutError) as exc:
            last_error = exc
    raise ConnectionError(f"upstream proxy could not connect to public destination: {host}") from last_error


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=10)
        if not request_line or len(request_line) > 8192:
            raise ValueError("invalid proxy request")
        method, target, version = request_line.decode("latin-1").rstrip("\r\n").split(" ", 2)
        headers: list[bytes] = []
        total = len(request_line)
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            total += len(line)
            if total > MAX_HEADER_BYTES:
                raise ValueError("proxy headers are too large")
            if line in {b"\r\n", b"\n", b""}:
                break
            if not line.lower().startswith((b"proxy-authorization:", b"proxy-connection:")):
                headers.append(line)

        if method.upper() == "CONNECT":
            host, port = _host_port(target, 443)
            upstream_reader, upstream_writer = await _connect_public(host, port)
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
        else:
            parsed = urlsplit(target)
            if parsed.scheme.lower() != "http" or not parsed.hostname:
                raise UnsafeURLError("plain proxy requests must use a public HTTP URL")
            port = parsed.port or 80
            if not _allowed_port(port):
                raise UnsafeURLError("proxy destination port is not allowed")
            upstream_reader, upstream_writer = await _connect_public(parsed.hostname, port)
            path = parsed.path or "/"
            if parsed.query:
                path += f"?{parsed.query}"
            upstream_writer.write(f"{method} {path} {version}\r\n".encode("latin-1"))
            for line in headers:
                upstream_writer.write(line)
            upstream_writer.write(b"\r\n")
            await upstream_writer.drain()

        await asyncio.gather(
            _pipe(reader, upstream_writer),
            _pipe(upstream_reader, writer),
            return_exceptions=True,
        )
    except Exception:
        with contextlib.suppress(Exception):
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
    finally:
        with contextlib.suppress(Exception):
            writer.close()
            await writer.wait_closed()


@contextlib.asynccontextmanager
async def guarded_egress_proxy() -> AsyncIterator[str]:
    _upstream_proxy()  # Fail at startup instead of after a user queues a job.
    server = await asyncio.start_server(_handle, "127.0.0.1", 0, limit=MAX_HEADER_BYTES)
    socket = server.sockets[0]
    host, port = socket.getsockname()[:2]
    try:
        async with server:
            yield f"http://{host}:{port}"
    finally:
        server.close()
        await server.wait_closed()


__all__ = ["guarded_egress_proxy"]
