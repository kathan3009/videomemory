# Using VideoMemory with MCP clients

VideoMemory exposes 7 tools and a `videomemory://frames/...` resource scheme over MCP stdio. Any MCP client that supports stdio can use it.

## Tools

| Tool | Args | Returns |
|---|---|---|
| `ingest_video` | `source` (path or URL) | `{ job_id, video_id, status, stages_done }` |
| `list_videos` | – | `{ videos: [...] }` |
| `query_video` | `video_id, query, max_chunks?, max_frames?, include_frames?` | `{ answer?, chunks, frames (URIs), events, token_estimate }` |
| `get_timeline` | `video_id, granularity?: scene\|chunk\|event` | `{ granularity, entries }` |
| `get_frames` | `video_id, query?, at_time?, range?, limit?` | `{ frames: [{ uri, timestamp, scene_id, why, score }] }` |
| `semantic_search` | `video_id, query, modalities?, top_k?` | `{ results: [{ chunk_id, start, end, score, summary }] }` |
| `get_transcript` | `video_id, speaker?, start?, end?` | `{ segments: [{ start, end, text, speaker }] }` |

## Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` and add:

```json
{
  "mcpServers": {
    "videomemory": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/absolute/path/to/videomemory",
        "videomemory",
        "mcp",
        "serve",
        "--data-dir",
        "/absolute/path/to/videomemory/data"
      ]
    }
  }
}
```

Restart Claude Desktop. You'll see the tools appear in the tool tray. Try:

> Ingest https://youtu.be/BM70fDqUo3c, then tell me what was discussed after the first 30 seconds.

Claude calls `ingest_video` → polls `list_videos` until it's done → calls `query_video` with your phrasing → the response includes chunks, events, and frame URIs (Claude fetches them as it sees fit).

## Cursor

Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "videomemory": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/videomemory", "videomemory", "mcp", "serve"]
    }
  }
}
```

## Windsurf / VSCode

Same shape — see `examples/cursor_mcp.json`, `examples/windsurf_mcp.json`, `examples/vscode_mcp.json`.

## Programmatic client (Python)

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(
        command="uv",
        args=["run", "videomemory", "mcp", "serve"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print([t.name for t in tools.tools])
            res = await session.call_tool("query_video", {
                "video_id": "yt_BM70fDqUo3c",
                "query": "summarize the main topic",
            })
            print(res.content[0].text)

asyncio.run(main())
```

## Token budget

Every tool response includes a `token_estimate` field (where applicable). Frames are returned as URIs, never blobs, so a `query_video` with `max_chunks=5, max_frames=8` typically fits inside ~2k tokens — safe for any modern context window.

## Manual verification checklist

(Tests 7 and 12 in the acceptance suite.)

1. Add the config snippet above to Claude Desktop.
2. Restart Claude Desktop. Confirm the videomemory tools appear in the tray.
3. In a new chat: *"Watch this video: https://youtu.be/BM70fDqUo3c. What is it about?"*
4. Confirm Claude calls `ingest_video`, waits, then `query_video`.
5. Ask a follow-up: *"Show me the relevant frames."* — Claude calls `get_frames`, receives URIs, and fetches them.
6. Ask: *"What happened after the first 30 seconds?"* — Claude calls `query_video`; the response uses the temporal anchor resolver under the hood.
