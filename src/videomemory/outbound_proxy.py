"""Small fail-closed HTTP CONNECT proxy for hosted downloader egress.

Each requested hostname is resolved by the proxy and the chosen socket is
opened directly to a verified public IP. This closes the DNS-rebinding gap
between URL validation and yt-dlp/HTTP client connections.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

from videomemory.url_safety import DEFAULT_PORTS, UnsafeURLError, resolve_public_addresses

MAX_HEADER_BYTES = 64 * 1024


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


async def _connect_public(host: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    addresses = await resolve_public_addresses(host, port)
    last_error: Exception | None = None
    for address in addresses:
        try:
            return await asyncio.wait_for(asyncio.open_connection(address, port), timeout=15)
        except (OSError, TimeoutError) as exc:
            last_error = exc
    raise ConnectionError(f"could not connect to public destination: {host}") from last_error


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
