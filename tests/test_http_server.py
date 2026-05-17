"""Hosted FastAPI surface (demo page + REST + HTTP MCP)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from videomemory.server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_root_serves_demo_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "videomemory" in r.text.lower()
    assert "claude mcp add" in r.text.lower()  # install snippet visible


def test_healthz(client):
    assert client.get("/healthz").text == "ok"


def test_videos_lists_library(client, tutorial_ingested):
    r = client.get("/videos")
    assert r.status_code == 200
    ids = {v["video_id"] for v in r.json()["videos"]}
    assert tutorial_ingested.video_id in ids


def test_search_rest(client, tutorial_ingested):
    r = client.post("/search", json={"query": "Docker", "top_k": 3})
    assert r.status_code == 200
    assert r.json()["hits"]


def test_mcp_initialize_and_tools_list(client, tutorial_ingested):
    # initialize
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["serverInfo"]["name"] == "videomemory"

    # tools/list
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert names == {"understand", "skip", "search", "add", "list"}


def test_mcp_tool_call(client, tutorial_ingested):
    r = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "list", "arguments": {}},
        },
    )
    body = r.json()
    text = body["result"]["content"][0]["text"]
    payload = json.loads(text)
    assert any(v["video_id"] == tutorial_ingested.video_id for v in payload["videos"])
