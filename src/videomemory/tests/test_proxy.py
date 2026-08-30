from __future__ import annotations

import asyncio

import pytest

from videomemory import outbound_proxy
from videomemory.ingest import _download_error, _network_args
from videomemory.outbound_proxy import _authority, _ordered_addresses, _upstream_proxy


def test_upstream_proxy_parses_credentials_without_retaining_url(monkeypatch):
    monkeypatch.setenv("VIDEOMEMORY_UPSTREAM_PROXY", "https://user:p%40ss@proxy.example:8443")

    proxy = _upstream_proxy()

    assert proxy is not None
    assert (proxy.scheme, proxy.host, proxy.port) == ("https", "proxy.example", 8443)
    assert proxy.authorization == "Basic dXNlcjpwQHNz"
    assert "p@ss" not in repr(proxy)
    assert "dXNlcj" not in repr(proxy)


@pytest.mark.parametrize(
    "value",
    [
        "socks5://proxy.example:1080",
        "https://proxy.example:bad",
        "https://proxy.example/path",
        "https://proxy.example?region=us",
    ],
)
def test_upstream_proxy_rejects_unsupported_urls(monkeypatch, value):
    monkeypatch.setenv("VIDEOMEMORY_UPSTREAM_PROXY", value)

    with pytest.raises(ValueError, match="VIDEOMEMORY_UPSTREAM_PROXY"):
        _upstream_proxy()


def test_proxy_authority_brackets_ipv6():
    assert _authority("203.0.113.7", 443) == "203.0.113.7:443"
    assert _authority("2001:db8::7", 443) == "[2001:db8::7]:443"


def test_ipv6_can_be_preferred_without_disabling_ipv4(monkeypatch):
    addresses = ["203.0.113.7", "2001:db8::7", "198.51.100.2"]
    assert _ordered_addresses(addresses) == addresses

    monkeypatch.setenv("VIDEOMEMORY_PREFER_IPV6", "1")
    assert _ordered_addresses(addresses) == ["2001:db8::7", "198.51.100.2", "203.0.113.7"]


def test_guard_chains_to_validated_ip_not_original_hostname(monkeypatch):
    monkeypatch.setenv("VIDEOMEMORY_UPSTREAM_PROXY", "http://proxy.example:8080")
    captured = {}
    marker = (object(), object())

    async def resolve(host, port):
        assert (host, port) == ("youtube.example", 443)
        return ["203.0.113.7"]

    async def connect(proxy, destination, port):
        captured.update(proxy=proxy, destination=destination, port=port)
        return marker

    monkeypatch.setattr(outbound_proxy, "resolve_public_addresses", resolve)
    monkeypatch.setattr(outbound_proxy, "_proxy_connect", connect)

    result = asyncio.run(outbound_proxy._connect_public("youtube.example", 443))

    assert result == marker
    assert captured["destination"] == "203.0.113.7"
    assert captured["port"] == 443
    assert captured["proxy"].host == "proxy.example"


def test_ytdlp_network_policy_and_rate_limit_error():
    args = _network_args()
    assert args[args.index("--retries") + 1] == "3"
    assert "--sleep-requests" in args

    error = _download_error(b"ERROR: HTTP Error 429: Too Many Requests; internal details")
    assert str(error) == (
        "YouTube rate-limited hosted ingestion. Upload the media file or configure a dedicated egress proxy."
    )


def test_rate_limit_error_is_not_hidden_by_long_warnings():
    stderr = ("WARNING: optional runtime detail\n" * 40).encode()
    stderr += b"ERROR: HTTP Error 429: Too Many Requests"

    error = _download_error(stderr)

    assert str(error) == (
        "YouTube rate-limited hosted ingestion. Upload the media file or configure a dedicated egress proxy."
    )


def test_download_error_keeps_the_final_actionable_detail():
    stderr = ("WARNING: noisy detail\n" * 40).encode() + b"ERROR: final extractor failure"

    error = _download_error(stderr)

    assert "ERROR: final extractor failure" in str(error)
