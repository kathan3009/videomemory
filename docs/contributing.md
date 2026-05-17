# contributing

PRs welcome. Codebase is intentionally tiny: ~12 source files, ~1k lines.

## dev loop

```bash
git clone https://github.com/kathan3009/videomemory.git
cd videomemory
./setup.sh              # full install + MCP register
uv run pytest -q        # 27 tests, ~25s
uv run ruff check .     # lint
```

## file map

```
src/videomemory/
├── cli.py               # typer surface
├── config.py            # data_dir + env knobs
├── deps.py              # `videomemory setup` wizard
├── embed.py             # bge-small wrapper
├── frames.py            # extract one or many keyframes
├── ingest.py            # yt-dlp → ffmpeg → whisper → windows → SQLite
├── library.py           # SQLite schema + CRUD + bundle export/import
├── mcp_server.py        # stdio MCP with 6 tools
├── search.py            # skip() + search() via cosine
├── understand.py        # summary + chapters
├── types.py             # Pydantic schemas
└── youtube_history.py   # Google Takeout parser
```

## adding a feature

1. Land the logic in a small new module (or extend an existing one).
2. Expose via MCP: add an entry to `TOOL_DEFS` in `mcp_server.py` + a handler in `_handle`.
3. Add a matching CLI command in `cli.py`.
4. Add a test under `tests/`. Reuse the `tutorial_ingested` / `science_ingested` / `silent_path` session fixtures.

## design principles

- **Simple beats clever.** If a feature needs more than 50 lines, redesign first.
- **The agent is smarter than us.** Don't pre-process; expose tools and let Claude/Codex think.
- **Frames as URIs, never blobs.** Keep agent context tight.
- **Idempotent everything.** Re-running a command must be safe.
- **No cloud, no API keys.** This is the whole product.

## license

MIT — by submitting a PR you agree your contribution is offered under the same license.
