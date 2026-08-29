from __future__ import annotations

import importlib

from starlette.testclient import TestClient


def _app(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDEOMEMORY_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("VIDEOMEMORY_ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("VIDEOMEMORY_WEB_ORIGINS", "http://localhost:3000")
    import videomemory.saas_api as saas_api

    return importlib.reload(saas_api).app


def test_signup_session_and_api_key(monkeypatch, tmp_path):
    with TestClient(_app(monkeypatch, tmp_path)) as client:
        response = client.post(
            "/api/auth/signup",
            json={"name": "Kathan", "email": "kathan@example.com", "password": "a-secure-password"},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["api_key"].startswith("vm_live_")
        assert "vm_session" in response.cookies

        account = client.get("/api/account")
        assert account.status_code == 200
        assert account.json()["user"]["email"] == "kathan@example.com"
        assert account.json()["usage"]["plan"] == "free"


def test_tenant_libraries_are_isolated(monkeypatch, tmp_path):
    from videomemory.library import list_videos, upsert_video
    from videomemory.tenant import tenant_scope
    from videomemory.types import Video

    with TestClient(_app(monkeypatch, tmp_path)):
        with tenant_scope("usr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"):
            upsert_video(Video(video_id="yt_private_a", source="https://example.com/a"))
            assert [item.video_id for item in list_videos()] == ["yt_private_a"]
        with tenant_scope("usr_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"):
            assert list_videos() == []
            upsert_video(Video(video_id="yt_private_b", source="https://example.com/b"))
            assert [item.video_id for item in list_videos()] == ["yt_private_b"]
        with tenant_scope("usr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"):
            assert [item.video_id for item in list_videos()] == ["yt_private_a"]


def test_mcp_rejects_missing_token(monkeypatch, tmp_path):
    with TestClient(_app(monkeypatch, tmp_path)) as client:
        response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert response.status_code == 401


def test_authenticated_mcp_initializes_without_redirect_and_lists_all_tools(monkeypatch, tmp_path):
    with TestClient(_app(monkeypatch, tmp_path)) as client:
        signup = client.post(
            "/api/auth/signup",
            json={"name": "Agent", "email": "agent@example.com", "password": "a-secure-password"},
        )
        headers = {
            "Authorization": f"Bearer {signup.json()['api_key']}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        }
        initialized = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
            follow_redirects=False,
        )
        assert initialized.status_code == 200
        assert initialized.json()["result"]["serverInfo"]["name"] == "videomemory"

        listed = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert listed.status_code == 200
        names = {tool["name"] for tool in listed.json()["result"]["tools"]}
        assert names == {
            "understand",
            "skip",
            "search",
            "frames",
            "look",
            "shots",
            "cutpoints",
            "add",
            "list",
            "memory",
            "note",
        }


def test_cross_origin_session_header_authenticates_dashboard(monkeypatch, tmp_path):
    with TestClient(_app(monkeypatch, tmp_path)) as client:
        signup = client.post(
            "/api/auth/signup",
            json={"name": "Browser", "email": "browser@example.com", "password": "a-secure-password"},
        ).json()
        client.cookies.clear()
        account = client.get("/api/account", headers={"X-Videomemory-Session": signup["session_token"]})
        assert account.status_code == 200
        assert account.json()["user"]["email"] == "browser@example.com"


def test_private_network_urls_are_rejected(monkeypatch, tmp_path):
    import asyncio

    from videomemory.url_safety import UnsafeURLError, validate_public_url

    for url in ("http://127.0.0.1/video", "http://169.254.169.254/latest/meta-data", "file:///etc/passwd"):
        try:
            asyncio.run(validate_public_url(url))
        except UnsafeURLError:
            pass
        else:
            raise AssertionError(f"unsafe URL was accepted: {url}")


def test_context_graph_records_queries_and_versioned_note_branches(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDEOMEMORY_DATA_ROOT", str(tmp_path))
    from videomemory.library import upsert_video
    from videomemory.memory_graph import add_note, graph_snapshot, record_tool_memory
    from videomemory.tenant import tenant_scope
    from videomemory.types import Video

    tenant = "usr_cccccccccccccccccccccccccccccccc"
    with tenant_scope(tenant):
        video = Video(video_id="u_graphvideo123456", source="https://example.com/video", title="Graph video")
        upsert_video(video)
        result = {
            "video_id": video.video_id,
            "start": 42.0,
            "title": video.title,
            "source": video.source,
        }
        record_tool_memory("skip", {"url": video.source, "question": "Where is the graph explained?"}, result)
        record_tool_memory("skip", {"url": video.source, "question": "Where is the graph explained?"}, result)
        root = add_note(video.video_id, "First interpretation", "The graph starts from a search.")
        branch = add_note(video.video_id, "Revised interpretation", "The graph compounds over time.", root["note_id"])
        graph = graph_snapshot()

        assert {node["node_type"] for node in graph["nodes"]} >= {"video", "query", "moment", "note"}
        assert any(edge["relation"] == "REFERENCES" and edge["weight"] == 2 for edge in graph["edges"])
        assert branch["version"] == 2
        assert branch["parent_note_id"] == root["note_id"]

    with tenant_scope("usr_dddddddddddddddddddddddddddddddd"):
        assert graph_snapshot()["nodes"] == []
