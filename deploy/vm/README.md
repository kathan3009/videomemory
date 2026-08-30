# Videomemory VM deployment

This profile runs the API/MCP process and its media worker on one persistent VM, with Caddy handling HTTPS. Keep the Vercel frontend unchanged.

## Capacity

- Stable beta baseline: 2 CPU cores, 8–12 GB RAM, and 50 GB persistent disk.
- Preferred credit-backed shape: 4 vCPU, 8–16 GB RAM.
- Keep `VIDEOMEMORY_JOB_CONCURRENCY=1`. More CPU makes one transcription faster; increasing ingestion concurrency multiplies model memory.
- The default VM profile caps the container at 2 CPUs and 10 GB RAM, leaving the host headroom. On a 4 vCPU / 8 GB host, set `VIDEOMEMORY_CONTAINER_CPUS=4.0`, `VIDEOMEMORY_CONTAINER_MEMORY=7g`, and `VIDEOMEMORY_OMP_THREADS=4`.

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
VIDEOMEMORY_CONTAINER_MEMORY=10g
VIDEOMEMORY_OMP_THREADS=2
VIDEOMEMORY_PREFER_IPV6=1
```

Point the Cloudflare `api.videomemory.kathandesai.com` A/AAAA records at the VM only after both checks succeed on the VM:

```bash
sudo docker compose -f docker-compose.vm.yml exec api \
  python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8080/health').read().decode())"
curl --resolve "api.videomemory.kathandesai.com:443:127.0.0.1" \
  https://api.videomemory.kathandesai.com/health
```

The API container port is deliberately not published on the host; Caddy is the only public entry point. Leave Railway running during validation so DNS can be rolled back immediately.

## Migration and verification

1. Stop new ingestion briefly so SQLite and media files are consistent.
2. Copy the complete Railway `/data/videomemory` directory into `/opt/videomemory/data` on the VM.
3. Start the VM service and confirm `/health` reports database and storage true.
4. Run login, upload, YouTube ingestion, memory graph, artifact memory, and MCP connection smoke tests.
5. Lower DNS TTL, switch the API A/AAAA records, and watch logs for one hour.
6. Keep Railway intact for at least 24 hours; remove it only after the VM backup has been restored successfully once.

Back up `/opt/videomemory/data` daily. A provider snapshot is useful, but retain an encrypted copy outside the VM as well.
