"""Test 7 — MCP server: spawn it as a subprocess, drive it with the MCP client SDK."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.asyncio
async def test_mcp_lists_tools_and_runs_query(tech_talk_ingest, session_data_dir: Path) -> None:
    vid = tech_talk_ingest.video_id

    env = os.environ.copy()
    env["VIDEOMEMORY_DATA_DIR"] = str(session_data_dir)

    server_params = StdioServerParameters(
        command="uv",
        args=["run", "videomemory", "mcp", "serve", "--data-dir", str(session_data_dir)],
        env=env,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            expected = {
                "ingest_video",
                "list_videos",
                "query_video",
                "get_timeline",
                "get_frames",
                "semantic_search",
                "get_transcript",
            }
            assert expected.issubset(names), f"missing tools: {expected - names}"

            # list_videos should include our ingested fixture
            lv = await session.call_tool("list_videos", {})
            text = lv.content[0].text  # type: ignore[union-attr]
            payload = json.loads(text)
            assert any(v["video_id"] == vid for v in payload["videos"])

            # query_video returns chunks
            q = await session.call_tool(
                "query_video", {"video_id": vid, "query": "When was OAuth discussed?", "max_chunks": 3}
            )
            qp = json.loads(q.content[0].text)  # type: ignore[union-attr]
            assert qp["chunks"], "no chunks returned"
            assert any("oauth" in c["summary"].lower() for c in qp["chunks"])

            # get_frames is selective (<= 8 by default)
            f = await session.call_tool(
                "get_frames", {"video_id": vid, "query": "Docker", "limit": 5}
            )
            fp = json.loads(f.content[0].text)  # type: ignore[union-attr]
            assert len(fp["frames"]) <= 5
            for fr in fp["frames"]:
                assert fr["uri"].startswith("videomemory://frames/")
