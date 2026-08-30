# VideoMemory deployment runbook

This is the shortest safe path from a clean checkout to a private beta. Budget 20–30 minutes once the two public hostnames and secrets are ready.

## API and MCP on a persistent VM (recommended)

For the ML-backed API, use at least 8 GB RAM. Railway's trial/free limits are suitable for the web frontend but not for faster-whisper, sentence-transformers, and visual embeddings in one process. The ready-to-run VM profile, Oracle cloud-init, HTTPS proxy, resource caps, migration steps, and rollback procedure are in `deploy/vm/README.md`.

Keep one worker with `VIDEOMEMORY_JOB_CONCURRENCY=1`. A 2-core/12-GB VM is the stable free baseline; a 4-vCPU/8–16-GB credit-backed VM improves transcription latency. Keep the Vercel frontend and point `api.videomemory.kathandesai.com` to the VM after the production smoke test succeeds.

## API and MCP on Railway (temporary fallback)

1. Create a Railway project from the repository root; Railway detects the root `Dockerfile`.
2. Keep exactly one replica. Attach a persistent volume at `/data/videomemory` and schedule a daily backup.
3. Set `VIDEOMEMORY_HOSTED=1`, `VIDEOMEMORY_DATA_ROOT=/data/videomemory`, `VIDEOMEMORY_ALLOWED_HOSTS=<api-domain>`, and `VIDEOMEMORY_WEB_ORIGINS=<vercel-origin>`.
4. Enable Railway Outbound IPv6 and set `VIDEOMEMORY_PREFER_IPV6=1`; this avoids a rate-limited shared IPv4 path when the destination publishes IPv6. For reliable YouTube ingestion when that route is also blocked, set `VIDEOMEMORY_UPSTREAM_PROXY` to a dedicated HTTP(S) proxy URL. Every destination is validated before the connection is chained, and proxy credentials never appear in yt-dlp arguments or job errors. Upload ingestion remains available without these settings.
5. Set `VIDEOMEMORY_WEB_URL=<vercel-origin>`, `VIDEOMEMORY_REQUIRE_EMAIL_VERIFICATION=1`, `VIDEOMEMORY_EMAIL_FROM=<verified-sender>`, `RESEND_API_KEY=<secret>`, and `TURNSTILE_SECRET_KEY=<secret>`.
6. For the credit-backed beta, set `VIDEOMEMORY_WHISPER_MODEL=tiny`, `VIDEOMEMORY_MAX_UPLOAD_BYTES=104857600`, `VIDEOMEMORY_MAX_TENANT_BYTES=367001600`, `VIDEOMEMORY_MAX_GLOBAL_BYTES=471859200`, and `VIDEOMEMORY_MAX_ACTIVE_JOBS=4`.
7. Enable public networking and configure `/health` as the healthcheck. Confirm it reports `status: ok` with database and storage true.

Railway deprecated new opt-ins to legacy `railway.toml` config-as-code. Use the project UI or run `railway config init`, review with `railway config plan`, and apply with `railway config apply`.

## Web app on Vercel

Import the same GitHub repository in Vercel and set the Root Directory to `src/videomemory/web`. Set:

- `NEXT_PUBLIC_API_URL=https://<api-domain>`
- `NEXT_PUBLIC_MCP_URL=https://<api-domain>/mcp`
- `NEXT_PUBLIC_SITE_URL=https://<vercel-domain>`
- `NEXT_PUBLIC_TURNSTILE_SITE_KEY=<site-key-paired-with-the-Railway-secret>`

Deploy the production branch, then replace the API's `VIDEOMEMORY_WEB_ORIGINS` value with the final Vercel origin and restart the API. The frontend uses standard Next.js and no OpenAI-hosted or OpenAI Sites infrastructure.

## Production smoke test

1. Complete the Turnstile challenge, create one synthetic account, follow the verification email, and save the one-time MCP key.
2. Upload `tests/fixtures/data/silent.mp4`; confirm completion and that no local path appears in the API.
3. Add a short public MP4, open its library detail, and search the transcript.
4. Run the dashboard connection test.
5. Connect Codex or Claude to `/mcp`, then call `list`, `memory`, `remember_artifact`, and `artifact_memory`.
6. Restart the service and verify the account, video, graph, artifact, and key remain available.
7. Perform one test restore before describing backups as complete.
8. Request a password reset, confirm that the URL loses its token after load, and verify the old browser sessions and MCP keys are rejected.

## Beta constraints

- Start invite-only. The container is non-root and media work is bounded, but a separate secret-free media worker plus object storage is the production-scale architecture.
- Keep billing disabled until checkout, webhook replay/order, cancellation, renewal, and entitlement expiry are verified with real provider credentials.
- Do not raise disk, queue, upload, or duration limits without object storage and atomic quota reservations.
