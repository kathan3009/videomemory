from __future__ import annotations

import importlib
from pathlib import Path

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
            "remember_artifact",
            "artifact_memory",
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


def test_upload_is_content_addressed_tenant_scoped_and_path_is_private(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDEOMEMORY_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("VIDEOMEMORY_ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("VIDEOMEMORY_WEB_ORIGINS", "http://localhost:3000")
    import videomemory.saas_api as saas_api

    saas_api = importlib.reload(saas_api)
    captured: dict[str, str] = {"calls": "0"}

    def queued(user_id: str, source: str):
        captured.update(user_id=user_id, source=source, calls=str(int(captured["calls"]) + 1))
        return {
            "job_id": "job_upload",
            "kind": "upload",
            "source": source,
            "status": "queued",
            "progress": 0,
            "created_at": "2026-08-29T00:00:00+00:00",
        }

    monkeypatch.setattr(saas_api, "enqueue_upload", queued)
    fixture = Path(__file__).parents[3] / "tests" / "fixtures" / "data" / "silent.mp4"
    with TestClient(saas_api.app) as client:
        signup = client.post(
            "/api/auth/signup",
            json={"name": "Uploader", "email": "upload@example.com", "password": "a-secure-password"},
        )
        response = client.post(
            "/api/uploads",
            content=fixture.read_bytes(),
            headers={"Content-Type": "video/mp4", "X-Videomemory-Filename": "My private clip.mp4"},
        )
        duplicate = client.post(
            "/api/uploads",
            content=fixture.read_bytes(),
            headers={"Content-Type": "video/mp4", "X-Videomemory-Filename": "same bytes new name.mp4"},
        )

    assert signup.status_code == 201
    assert response.status_code == 202
    assert duplicate.status_code == 202
    assert response.json()["job"]["source"] == "upload://My-private-clip.mp4"
    stored = Path(captured["source"])
    assert stored.is_file()
    assert stored.parent.name == "uploads"
    assert stored.name.endswith(".mp4") and len(stored.stem) == 64
    assert stored.with_suffix(".name").read_text() == "My-private-clip.mp4"
    assert len([item for item in stored.parent.glob("*.*") if item.suffix != ".name"]) == 1
    assert str(tmp_path) not in str(response.json())


def test_upload_memory_never_records_internal_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDEOMEMORY_DATA_ROOT", str(tmp_path))
    from videomemory.library import upsert_video
    from videomemory.memory_graph import graph_snapshot, record_tool_memory
    from videomemory.tenant import tenant_scope
    from videomemory.types import Video

    tenant = "usr_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    internal = tmp_path / "tenants" / tenant / "uploads" / "hash--private.mp4"
    with tenant_scope(tenant):
        video = Video(video_id="f_deadbeefdeadbeef", source=str(internal), title="private")
        upsert_video(video)
        record_tool_memory(
            "add",
            {"display_source": "upload://private.mp4", "source_type": "upload"},
            video.model_dump(mode="json"),
        )
        graph = graph_snapshot()

    video_nodes = [node for node in graph["nodes"] if node["node_type"] == "video"]
    assert len(video_nodes) == 1
    assert video_nodes[0]["node_id"] == video.video_id
    assert video_nodes[0]["properties"]["source"] == "upload://private.mp4"
    assert str(tmp_path) not in str(graph)


def test_artifact_memory_versions_searches_and_stays_tenant_private(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDEOMEMORY_DATA_ROOT", str(tmp_path))
    from videomemory.artifact_memory import artifact_memory, remember_artifact
    from videomemory.memory_graph import graph_snapshot
    from videomemory.tenant import tenant_scope

    tenant = "usr_ffffffffffffffffffffffffffffffff"
    with tenant_scope(tenant):
        first = remember_artifact(
            title="Launch runbook",
            locator="/workspace/DEPLOYMENT.md",
            kind="document",
            summary="First deployment checklist",
            content="deploy the API and verify health",
            project="VideoMemory",
            agent="Codex",
        )
        second = remember_artifact(
            title="Launch runbook",
            locator="/workspace/DEPLOYMENT.md",
            kind="document",
            summary="Reviewed launch checklist",
            content="deploy the API, verify health, and test MCP",
            project="VideoMemory",
            agent="Claude",
        )
        recalled = artifact_memory("MCP")
        history = artifact_memory(artifact_id=second["artifact_id"], include_content=True)
        graph = graph_snapshot()

        assert first["artifact_id"] == second["artifact_id"]
        assert first["version"] == 1 and second["version"] == 2
        assert recalled["artifacts"][0]["title"] == "Launch runbook"
        assert [item["version"] for item in history["versions"]] == [2, 1]
        assert any(node["node_type"] == "artifact" for node in graph["nodes"])
        assert any(edge["relation"] == "CONTAINS_ARTIFACT" for edge in graph["edges"])

    with tenant_scope("usr_00000000000000000000000000000000"):
        assert artifact_memory()["artifacts"] == []


def test_artifact_api_is_authenticated_and_tenant_isolated(monkeypatch, tmp_path):
    with TestClient(_app(monkeypatch, tmp_path)) as first:
        signup = first.post(
            "/api/auth/signup",
            json={"name": "Artifacts", "email": "artifacts@example.com", "password": "a-secure-password"},
        )
        session = signup.json()["session_token"]
        created = first.post(
            "/api/artifacts",
            headers={"X-Videomemory-Session": session},
            json={
                "title": "Release notes",
                "locator": "https://example.com/releases/1",
                "kind": "document",
                "summary": "Launch artifact",
                "project": "VideoMemory",
            },
        )
        listed = first.get("/api/artifacts", headers={"X-Videomemory-Session": session})

        assert created.status_code == 201
        assert listed.json()["artifacts"][0]["title"] == "Release notes"

    with TestClient(_app(monkeypatch, tmp_path)) as second:
        signup = second.post(
            "/api/auth/signup",
            json={"name": "Other", "email": "other@example.com", "password": "a-secure-password"},
        )
        isolated = second.get(
            "/api/artifacts", headers={"X-Videomemory-Session": signup.json()["session_token"]}
        )
        assert isolated.json()["artifacts"] == []


def test_billing_signatures_and_out_of_order_webhooks_preserve_entitlements(monkeypatch, tmp_path):
    import hashlib
    import hmac
    import json

    webhook_secret = "whsec_test_videomemory"
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_key")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "checkout_secret")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", webhook_secret)

    with TestClient(_app(monkeypatch, tmp_path)) as client:
        signup = client.post(
            "/api/auth/signup",
            json={"name": "Subscriber", "email": "subscriber@example.com", "password": "a-secure-password"},
        )
        assert signup.status_code == 201
        user_id = signup.json()["user"]["user_id"]

        def send_event(event_id: str, status: str, created_at: int, signature_secret: str = webhook_secret):
            body = json.dumps(
                {
                    "event": f"subscription.{status}",
                    "created_at": created_at,
                    "payload": {
                        "subscription": {
                            "entity": {
                                "id": "sub_creator",
                                "status": status,
                                "current_end": 1_800_000_000,
                                "notes": {"user_id": user_id, "plan": "creator"},
                            }
                        }
                    },
                },
                separators=(",", ":"),
            ).encode()
            signature = hmac.new(signature_secret.encode(), body, hashlib.sha256).hexdigest()
            return client.post(
                "/api/webhooks/razorpay",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Razorpay-Signature": signature,
                    "X-Razorpay-Event-Id": event_id,
                },
            )

        assert send_event("evt_active", "active", 200).status_code == 200
        active = client.get("/api/account").json()
        assert active["user"]["plan"] == "creator"
        assert active["billing"]["subscription"]["status"] == "active"

        # Razorpay documents that webhook delivery can be out of order. An older
        # terminal event must not revoke a newer active entitlement.
        assert send_event("evt_stale_cancel", "cancelled", 100).status_code == 200
        still_active = client.get("/api/account").json()
        assert still_active["user"]["plan"] == "creator"
        assert still_active["billing"]["subscription"]["status"] == "active"

        invalid = send_event("evt_bad_signature", "cancelled", 300, "wrong-secret")
        assert invalid.status_code == 401
        assert client.get("/api/account").json()["user"]["plan"] == "creator"

        assert send_event("evt_current_cancel", "cancelled", 300).status_code == 200
        cancelled = client.get("/api/account").json()
        assert cancelled["user"]["plan"] == "free"
        assert cancelled["billing"]["subscription"]["status"] == "cancelled"


def test_pending_checkout_does_not_remove_an_existing_paid_entitlement(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDEOMEMORY_DATA_ROOT", str(tmp_path))
    from videomemory.control import apply_subscription, create_user, get_user

    user = create_user("paid@example.com", "Paid User", "a-secure-password")
    assert apply_subscription(
        user["user_id"],
        provider_subscription_id="sub_active",
        plan="creator",
        status="active",
        provider_event_created_at=200,
    )
    assert get_user(user["user_id"])["plan"] == "creator"

    # A replacement checkout is only pending until the provider signs a state
    # change, so it must not revoke access to the customer's current plan.
    assert apply_subscription(
        user["user_id"],
        provider_subscription_id="sub_pending",
        plan="studio",
        status="created",
    )
    assert get_user(user["user_id"])["plan"] == "creator"
