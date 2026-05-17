# Deploying example.com

v0.2 ships as a single Fly.io app — no separate frontend, no Qdrant, no second service. The container hosts:

- `GET /` — single-page demo (paste URL + question → answer)
- `POST /skip`, `/search`, `/understand`, `/add` — REST
- `POST /mcp` — remote HTTP MCP transport (so users install with one `claude mcp add` line)
- `GET /frames/{video_id}/{name}` — keyframe serving

## Deploy

```bash
brew install flyctl                       # or: curl -L https://fly.io/install.sh | sh
flyctl auth login
flyctl launch --copy-config --no-deploy   # edit primary_region first
flyctl deploy
flyctl logs                               # watch model download (~600 MB, ~90 s)
curl https://videomemory.fly.dev/healthz  # → ok
```

## Subdomain

```bash
flyctl certs add example.com
flyctl certs show example.com   # prints A + AAAA records
```

At your registrar (example.com DNS), add:

```
videomemory   A      <fly-ipv4>
videomemory   AAAA   <fly-ipv6>
```

Wait 2 min, then:

```bash
curl https://example.com/healthz
```

## Cost

`performance-2x` (2 vCPU / 4 GB) + 20 GB volume. With `auto_stop_machines = "stop"`:
- Idle: ~$0/mo (machine sleeps)
- Each cold start: ~30 s (model warm-up)
- Each warm request: same speed as local

If traffic grows past ~100 daily users, bump `min_machines_running = 1` (eliminates cold starts, ~$30/mo).

## Safety

The container respects `VIDEOMEMORY_MAX_VIDEO_SECONDS` (default 30 min — public ingests can't pin your CPU for hours). To lock down ingestion to invited users only:

```bash
flyctl secrets set VIDEOMEMORY_INGEST_TOKEN=$(openssl rand -hex 32)
flyctl deploy
```

(Authenticated routes are a v1.1 feature — pull the token check in `api/safety.py` from history if you need it now.)

## Storage

`/data` lives on a Fly volume. The library is one SQLite file with embeddings inline. To back up:

```bash
flyctl ssh console -C "cat /data/library.sqlite" > backup.sqlite
```

To restore on another machine:

```bash
flyctl ssh console -C "cat > /data/library.sqlite" < backup.sqlite
flyctl restart -a videomemory
```

## When to use hosted vs. local

| | hosted | local |
|---|---|---|
| Install | 1 line | `git clone` + setup |
| Privacy | shared cache (your queries leave your machine) | private |
| Cost | free (today) | your CPU |
| Models | pre-warmed | first-run download (~600 MB) |
| Watch Club | server-side library = community-shared (eventually) | per-user, you control sharing |

The hosted version is the viral default; local is the privacy / power-user mode.
