# VideoMemory deployment runbook

This is the shortest safe path from a clean checkout to a private beta. Budget 20–30 minutes once the two public hostnames and secrets are ready.

## API and MCP on Railway

1. Create a Railway project from the repository root; Railway detects the root `Dockerfile`.
2. Keep exactly one replica. Attach a persistent volume at `/data/videomemory` and schedule a daily backup.
3. Set `VIDEOMEMORY_HOSTED=1`, `VIDEOMEMORY_DATA_ROOT=/data/videomemory`, `VIDEOMEMORY_ALLOWED_HOSTS=<api-domain>`, and `VIDEOMEMORY_WEB_ORIGINS=<sites-origin>`.
4. For the credit-backed beta, set `VIDEOMEMORY_WHISPER_MODEL=tiny`, `VIDEOMEMORY_MAX_UPLOAD_BYTES=104857600`, `VIDEOMEMORY_MAX_TENANT_BYTES=367001600`, `VIDEOMEMORY_MAX_GLOBAL_BYTES=471859200`, and `VIDEOMEMORY_MAX_ACTIVE_JOBS=4`.
5. Enable public networking and configure `/health` as the healthcheck. Confirm it reports `status: ok` with database and storage true.

Railway deprecated new opt-ins to legacy `railway.toml` config-as-code. Use the project UI or run `railway config init`, review with `railway config plan`, and apply with `railway config apply`.

## Web app on Vercel

Import the same GitHub repository in Vercel and set the Root Directory to `src/videomemory/web`. Set:

- `NEXT_PUBLIC_API_URL=https://<api-domain>`
- `NEXT_PUBLIC_MCP_URL=https://<api-domain>/mcp`
- `NEXT_PUBLIC_SITE_URL=https://<vercel-domain>`

Deploy the production branch, then replace the API's `VIDEOMEMORY_WEB_ORIGINS` value with the final Vercel origin and restart the API. The frontend uses standard Next.js and no OpenAI-hosted or OpenAI Sites infrastructure.

## Production smoke test

1. Create one synthetic account and save the one-time MCP key.
2. Upload `tests/fixtures/data/silent.mp4`; confirm completion and that no local path appears in the API.
3. Add a short public MP4, open its library detail, and search the transcript.
4. Run the dashboard connection test.
5. Connect Codex or Claude to `/mcp`, then call `list`, `memory`, `remember_artifact`, and `artifact_memory`.
6. Restart the service and verify the account, video, graph, artifact, and key remain available.
7. Perform one test restore before describing backups as complete.

## Beta constraints

- Start invite-only. The container is non-root and media work is bounded, but a separate secret-free media worker plus object storage is the production-scale architecture.
- Keep billing disabled until checkout, webhook replay/order, cancellation, renewal, and entitlement expiry are verified with real provider credentials.
- Do not raise disk, queue, upload, or duration limits without object storage and atomic quota reservations.
