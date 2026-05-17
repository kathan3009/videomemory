# Production deployment — example.com

Split deployment:

| Subdomain | Host | Purpose |
|---|---|---|
| `example.com` | **Vercel** | Next.js frontend |
| `videomemory-api.example.com` | **Fly.io** | FastAPI + qdrant-local + ML models, persistent 50 GB volume |

The frontend can live on Vercel because it's pure Next.js. The backend cannot — it needs ffmpeg, persistent disk, 8 GB RAM, and minute-long jobs. Fly.io fits these natively.

---

## 1. Backend — Fly.io

### One-time setup

```bash
brew install flyctl          # or: curl -L https://fly.io/install.sh | sh
flyctl auth signup           # or: flyctl auth login
```

### Deploy

From the repo root:

```bash
# Edit fly.toml: change `primary_region` to a region near you (sjc/iad/lhr/fra/...).
flyctl launch --copy-config --no-deploy   # creates the app + 50 GB volume
flyctl deploy                              # builds Dockerfile.api, ships, runs
flyctl status                              # confirm machine is healthy
flyctl logs                                # watch first-run model downloads (~1 GB, takes a couple of minutes)
```

Smoke test:

```bash
curl https://videomemory-api.fly.dev/healthz   # → {"status":"ok"}
```

### Attach your subdomain

```bash
# Add the cert in Fly:
flyctl certs add videomemory-api.example.com

flyctl certs show videomemory-api.example.com
# Fly prints two DNS records to add — typically:
#   videomemory-api    A      <fly-ipv4>
#   videomemory-api    AAAA   <fly-ipv6>
#   (and an _acme-challenge CNAME for cert issuance)
```

Go to your registrar's DNS panel for `example.com` and add those records exactly. Wait 1–5 min, then:

```bash
flyctl certs show videomemory-api.example.com   # cert should say "Issued"
curl https://videomemory-api.example.com/healthz
```

---

## 2. Frontend — Vercel

### Push the frontend to Vercel

```bash
cd frontend
npx vercel link             # connect to your Vercel account / project
npx vercel env add NEXT_PUBLIC_API_BASE production
# value: https://videomemory-api.example.com

npx vercel --prod
```

(If you prefer the Vercel dashboard: import the `frontend/` subdirectory of the repo, set Root Directory to `frontend`, and add the same env var.)

### Attach the subdomain

In Vercel → project → Settings → Domains → add `example.com`.
Vercel will tell you the DNS record to add at your registrar — typically:

```
videomemory   CNAME   cname.vercel-dns.com.
```

After DNS propagates, https://example.com renders the frontend, and every `/api/*` call gets rewritten (see `frontend/next.config.mjs`) to the Fly backend.

---

## 3. (Optional) Lock down ingestion

You answered "fully public" — that means anyone can POST `/videos/ingest_url` and pin your machine for minutes per request. We've already added a **30-minute video-duration cap** by default. If at any point you want to switch to invite-only ingestion without redeploying the frontend:

```bash
flyctl secrets set VIDEOMEMORY_INGEST_TOKEN=<some-long-random-string>
flyctl deploy
```

Then anyone hitting `POST /videos/ingest_url` or `POST /videos/upload` must send `Authorization: Bearer <token>`. Reads stay public. To open it back up, delete the secret and redeploy.

To raise/lower the duration cap:

```bash
flyctl secrets set VIDEOMEMORY_MAX_VIDEO_SECONDS=600   # 10-min cap
flyctl deploy
```

---

## 4. Wire Claude Desktop (optional)

Claude Desktop's MCP client only speaks **stdio**, which means it runs the server locally as a subprocess — it cannot talk to a Fly backend over HTTPS. Two options:

1. **Run the MCP server locally** (recommended) and point it at the production data dir. Anyone using Claude on their machine sees the same memories you've ingested. Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

   ```json
   {
     "mcpServers": {
       "videomemory": {
         "command": "uv",
         "args": [
           "run", "--project", "/path/to/videomemory",
           "videomemory", "mcp", "serve",
           "--data-dir", "/path/to/videomemory/data"
         ]
       }
     }
   }
   ```

   The data dir is local — ingestions you run here don't share with Fly. That's fine if you're using Claude Desktop as a personal tool.

2. **Future enhancement**: add a remote MCP transport (`mcp/ws.py` is stubbed). When ready, expose `/mcp/ws` from the FastAPI app and clients can connect over WebSocket.

---

## 5. Cost & operations

| Item | Cost |
|---|---|
| Fly.io `performance-4x` (4 vCPU / 8 GB) | ~$58/mo if always-on; ~$0.04/hr otherwise |
| Fly volume 50 GB | ~$7.50/mo |
| Egress | Fly free tier covers ~100 GB/mo |
| Vercel hobby | $0 (within hobby limits) |

If cost matters, use `performance-2x` (2 vCPU / 4 GB) and accept slower ingests, or scale to zero with `auto_stop_machines = "stop"` (warmup adds ~30 s to the first request after idle).

To watch logs / debug:

```bash
flyctl logs
flyctl ssh console      # shell into the running machine
flyctl machine list
flyctl volume list
```

To redeploy after pushing to GitHub:

```bash
flyctl deploy
```

---

## 6. Common gotchas

- **First-run model downloads** are ~1 GB and run on first request, not deploy. The Dockerfile pre-pulls them in the build stage — confirm by checking `flyctl logs` for `Pre-downloading VideoMemory models...`.
- **Vercel CORS**: the FastAPI middleware allows `*` origins, so the browser fetches from example.com → videomemory-api.example.com work without extra config.
- **Frame URLs**: the frontend uses `/api/videos/{id}/frames/{name}`, which Vercel rewrites to the Fly backend. If frames don't load, open the network tab and confirm the rewrite is hitting `videomemory-api.example.com`.
- **Whisper memory spikes** on long videos. If you see OOM kills in `flyctl logs`, lower `VIDEOMEMORY_MAX_VIDEO_SECONDS` or bump to `performance-8x` (16 GB).
