"""SSRF-resistant validation for user-supplied remote video URLs."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

ALLOWED_SCHEMES = {"http", "https"}
DEFAULT_PORTS = {80, 443}


class UnsafeURLError(ValueError):
    pass


def _allowed_hosts() -> set[str]:
    raw = os.environ.get("VIDEOMEMORY_ALLOWED_URL_HOSTS", "")
    return {host.strip().lower().rstrip(".") for host in raw.split(",") if host.strip()}


def _ip_is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def resolve_public_addresses(hostname: str, port: int) -> list[str]:
    try:
        literal = ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if not _ip_is_public(str(literal)):
            raise UnsafeURLError("private and local network addresses are not allowed")
        return [str(literal)]

    loop = asyncio.get_running_loop()
    try:
        results = await loop.run_in_executor(
            None, lambda: socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        )
    except socket.gaierror as exc:
        raise UnsafeURLError("the URL hostname could not be resolved") from exc
    addresses = {item[4][0] for item in results}
    if not addresses or any(not _ip_is_public(address) for address in addresses):
        raise UnsafeURLError("the URL resolves to a private or unsafe network address")
    return sorted(addresses)


async def validate_public_url(url: str) -> str:
    """Validate and normalize a public URL, following only validated redirects.

    The application-level checks are paired with strict container/network policy
    in production. Revalidation happens immediately before the downloader starts.
    """

    if len(url) > 4096:
        raise UnsafeURLError("URL is too long")
    current = url.strip()
    for _ in range(6):
        parsed = urlsplit(current)
        if parsed.scheme.lower() not in ALLOWED_SCHEMES:
            raise UnsafeURLError("only public HTTP and HTTPS URLs are supported")
        if not parsed.hostname or parsed.username or parsed.password:
            raise UnsafeURLError("URL must contain a public hostname and no embedded credentials")
        host = parsed.hostname.lower().rstrip(".")
        allowlist = _allowed_hosts()
        if allowlist and host not in allowlist and not any(host.endswith(f".{item}") for item in allowlist):
            raise UnsafeURLError("this URL host is not enabled for the hosted service")
        try:
            port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        except ValueError as exc:
            raise UnsafeURLError("URL contains an invalid port") from exc
        extra_ports = {
            int(value)
            for value in os.environ.get("VIDEOMEMORY_ALLOWED_URL_PORTS", "").split(",")
            if value.strip().isdigit()
        }
        if port not in DEFAULT_PORTS | extra_ports:
            raise UnsafeURLError("non-standard network ports are not allowed")
        await resolve_public_addresses(host, port)

        normalized = urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, ""))
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=10,
                proxy=os.environ.get("VIDEOMEMORY_EGRESS_PROXY") or None,
            ) as client:
                response = await client.head(normalized, headers={"User-Agent": "videomemory/1.0"})
        except httpx.HTTPError:
            return normalized
        if response.status_code not in {301, 302, 303, 307, 308}:
            return normalized
        location = response.headers.get("location")
        if not location:
            raise UnsafeURLError("redirect response did not include a destination")
        current = urljoin(normalized, location)
    raise UnsafeURLError("URL redirected too many times")


__all__ = ["UnsafeURLError", "resolve_public_addresses", "validate_public_url"]
