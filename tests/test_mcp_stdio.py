"""MCP stdio server smoke test."""

from __future__ import annotations

import json
import os

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.asyncio
async def test_stdio_lists_tools_and_calls_each(tutorial_ingested):
    data_dir = os.environ["VIDEOMEMORY_DATA_DIR"]
    env = os.environ.copy()
    env["VIDEOMEMORY_DATA_DIR"] = data_dir

    params = StdioServerParameters(
        command="uv",
        args=["run", "videomemory", "mcp", "serve"],
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert names == {"understand", "skip", "search", "add", "list"}

            lv = await session.call_tool("list", {})
            payload = json.loads(lv.content[0].text)
            assert any(v["video_id"] == tutorial_ingested.video_id for v in payload["videos"])

            search_res = await session.call_tool("search", {"query": "Docker", "top_k": 3})
            sp = json.loads(search_res.content[0].text)
            assert sp["hits"], "search should return hits"
