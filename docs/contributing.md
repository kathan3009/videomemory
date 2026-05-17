# contributing

PRs welcome. The codebase is intentionally tiny: ~10 files, ~1k lines.

## dev loop

```bash
git clone https://github.com/kathan3009/videomemory.git
cd videomemory
uv sync --extra dev
uv run videomemory setup        # checks deps + pre-pulls models

uv run pytest -q                # 28 tests, ~40s
uv run ruff check .             # lint
```

## file map

```
src/videomemory/
├── __init__.py
├── cli.py             # typer surface
├── config.py          # data_dir + env knobs
├── deps.py            # `videomemory setup` wizard
├── embed.py           # bge-small wrapper
├── frames.py          # single-frame extraction
├── ingest.py          # yt-dlp → ffmpeg → whisper → windows → SQLite
├── library.py         # SQLite schema + CRUD + bundle export/import
├── mcp_server.py      # stdio MCP with 5 tools
├── search.py          # skip() + search() via cosine
├── server.py          # FastAPI: demo page + REST + HTTP MCP
├── understand.py      # summary + chapters
├── types.py           # Pydantic schemas
└── youtube_history.py # Google Takeout parser
```

## adding a feature

1. Land the logic in a small new module (or extend `search.py` / `understand.py`).
2. Expose via MCP: add an entry to `TOOL_DEFS` in `mcp_server.py` + a handler in `_handle`.
3. Mirror it as a REST route in `server.py` (one-liner most of the time).
4. Add a CLI command in `cli.py`.
5. Add a test under `tests/`. Reuse the `tutorial_ingested` / `science_ingested` session fixtures.

## design principles

- Simple beats clever. If a feature needs more than 50 lines, push back on the design first.
- The agent is smarter than us. Don't pre-process; expose tools.
- Frames as URIs, never blobs.
- Idempotent everything. Re-running a command must be safe.
- Tests live next to features, not in a separate "integration" folder.

## license

MIT — by submitting a PR you agree your contribution is offered under the same license.
