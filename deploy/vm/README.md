# Videomemory VM deployment

This profile runs the API/MCP process and its media worker on one persistent VM, with Caddy handling HTTPS. Keep the Vercel frontend unchanged.

## Capacity

- Stable beta baseline: 2 CPU cores, 8–12 GB RAM, and 50 GB persistent disk.
- Preferred credit-backed shape: 4 vCPU, 8–16 GB RAM.
- Keep `VIDEOMEMORY_JOB_CONCURRENCY=1`. More CPU makes one transcription faster; increasing ingestion concurrency multiplies model memory.
- The default VM profile caps the API container at 2 CPUs and 7 GB RAM, leaving the host and PO-token sidecar headroom. On a 4 vCPU / 8 GB host, keep the 7 GB memory cap and set `VIDEOMEMORY_CONTAINER_CPUS=4.0` plus `VIDEOMEMORY_OMP_THREADS=4`.

## Azure student deployment

The current production baseline is Ubuntu 24.04 on `Standard_B2as_v2` (2 vCPU / 8 GiB), a 64 GB managed disk, 4 GB swap, and inbound ports limited to 22, 80, and 443. Keep autoscaling disabled and use a fixed VM shape so background video jobs cannot create surprise instances.

## Oracle Cloud Free Tier

1. Create an Ubuntu 24.04 ARM instance using `VM.Standard.A1.Flex`.
2. Use the Always Free allowance (currently 2 OCPU / 12 GB RAM) for the durable free host. During trial/startup credits, 4 OCPU / 24 GB gives faster ingestion.
3. Allocate a 75–100 GB boot volume, public IPv4, and public IPv6 when available.
4. Paste `deploy/oci/cloud-init.yaml` into the instance cloud-init/user-data field.
5. Allow inbound TCP 22, 80, and 443 plus UDP 443 in the OCI network security list. UFW applies the same restriction on the VM.

Cloud-init installs Docker, checks out the public repository, adds a 4 GB low-swappiness safety swap, and stops before starting the app so secrets never enter instance metadata.

## Start the service

SSH to the VM, then:

```bash
cd /opt/videomemory/app
sudo cp .env.production.pending .env.production
sudo chmod 600 .env.production
sudo editor .env.production
sudo docker compose -f docker-compose.vm.yml up -d --build
sudo docker compose -f docker-compose.vm.yml ps
```

Set these VM-specific values in `.env.production` in addition to the existing production secrets:

```dotenv
VIDEOMEMORY_API_HOST=api.videomemory.kathandesai.com
VIDEOMEMORY_ALLOWED_HOSTS=api.videomemory.kathandesai.com
VIDEOMEMORY_WEB_ORIGINS=https://videomemory.kathandesai.com
VIDEOMEMORY_WEB_URL=https://videomemory.kathandesai.com
VIDEOMEMORY_COOKIE_DOMAIN=.kathandesai.com
VIDEOMEMORY_HOST_DATA=/opt/videomemory/data
VIDEOMEMORY_CONTAINER_CPUS=2.0
VIDEOMEMORY_CONTAINER_MEMORY=7g
VIDEOMEMORY_OMP_THREADS=2
VIDEOMEMORY_PREFER_IPV6=0
VIDEOMEMORY_YTDLP_CONFIG_DIR=/opt/videomemory/ytdlp
```

YouTube can require account verification for datacenter IPs even when PO tokens are present. If that happens, place a Netscape-format `cookies.txt` from a dedicated low-privilege YouTube account at `/opt/videomemory/ytdlp/cookies.txt`, owned by root with mode `600`, then restart the API. Do not use a founder's primary Google account; YouTube warns that automated use can suspend the account. A dedicated egress proxy remains supported through `VIDEOMEMORY_UPSTREAM_PROXY`.

Point the Cloudflare `api.videomemory.kathandesai.com` A/AAAA records at the VM only after both checks succeed on the VM:

```bash
sudo docker compose -f docker-compose.vm.yml exec api \
  python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8080/health').read().decode())"
curl --resolve "api.videomemory.kathandesai.com:443:127.0.0.1" \
  https://api.videomemory.kathandesai.com/health
```

The API container port and the YouTube proof-of-origin token provider are deliberately not published on the host; Caddy is the only public entry point. Leave Railway running during validation so DNS can be rolled back immediately.

## Migration and verification

1. Stop new ingestion briefly so SQLite and media files are consistent.
2. Copy the complete Railway `/data/videomemory` directory into `/opt/videomemory/data` on the VM.
3. Start the VM service and confirm `/health` reports database and storage true.
4. Run login, upload, YouTube ingestion, memory graph, artifact memory, and MCP connection smoke tests.
5. Lower DNS TTL, switch the API A/AAAA records, and watch logs for one hour.
6. Keep Railway intact for at least 24 hours; remove it only after the VM backup has been restored successfully once.

## Encrypted off-host backups

`deploy/vm/backup.py` copies media into a private staging tree, uses SQLite's online backup API for every database, verifies each snapshot with `PRAGMA integrity_check`, and sends the result to an encrypted restic repository. The timer keeps 7 daily, 4 weekly, and 6 monthly snapshots.

Install `restic`, place its repository credentials in root-only `/opt/videomemory/backup.env`, initialize the repository once, and enable the timer:

```bash
sudo apt-get update && sudo apt-get install -y restic
sudo chmod 600 /opt/videomemory/backup.env
sudo cp deploy/vm/videomemory-backup.service /etc/systemd/system/
sudo cp deploy/vm/videomemory-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now videomemory-backup.timer
sudo systemctl start videomemory-backup.service
sudo journalctl -u videomemory-backup.service --no-pager
```

Keep a second, offline copy of `RESTIC_PASSWORD`; without it, the remote snapshots cannot be restored.
