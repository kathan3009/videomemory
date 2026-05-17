# Contributing

Thanks for considering a contribution! VideoMemory is an early-stage OSS project and we welcome issues, PRs, and ideas.

## Dev setup

```bash
git clone https://github.com/kathan3009/videomemory.git
cd videomemory
uv sync --extra ml --extra dev
uv run python scripts/download_models.py
uv run python tests/fixtures/make_videos.py
uv run pytest -q
```

Python 3.12 is required (pinned via `uv` — `pyproject.toml` excludes 3.13+).

## Layout

See `docs/architecture.md` for the module map and design decisions.

## Adding a tool to the MCP server

1. Define the tool schema in `videomemory/mcp/server.py` (in `TOOL_DEFS`).
2. Write the handler in `videomemory/mcp/tools.py`.
3. Wire it in `_TOOL_HANDLERS`.
4. Add a parallel HTTP route in `videomemory/api/app.py` if you want it usable from the frontend.
5. Add an integration test under `tests/mcp/`.

## Adding a retrieval modality

The router lives in `videomemory/retrieval/router.py`. Add a new ranker function, then plug it into `retrieve_chunks`'s fusion list with an appropriate weight. The fusion uses Reciprocal Rank Fusion in `retrieval/fuse.py`.

## Adding a model backend

- **Embeddings**: implement a wrapper alongside `videomemory/embeddings/bge.py` and update `PipelineConfig.embedding_model`.
- **Vector DB**: implement the `VectorStore` interface in `videomemory/vector/base.py`.
- **LLM provider**: subclass `LLMProvider` in `videomemory/query/providers/base.py`.

## Tests

```bash
uv run pytest -m "not network" -q       # offline
uv run pytest -m network -q             # YouTube smoke
uv run pytest --cov=videomemory -q      # with coverage
```

## Code style

`ruff` for lint, `mypy` for types. CI runs both.

```bash
uv run ruff check .
uv run mypy src/videomemory
```

## License

MIT — by submitting a PR you agree your contribution is offered under the same license.
