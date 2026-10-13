# Deployment

The supplied image contains the Python backend and compiled frontend. It does not require a Node.js runtime, Docker socket, Portainer connection or privileged container. Docker needs ordinary outbound access to the configured SDEX origin.

## Docker Compose

From a clean checkout:

```powershell
Copy-Item .env.example .env
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail 100 connectmap
```

Open `http://localhost:8080`. Compose defaults to the offline demo. Set `CONNECTMAP_MOCK_MODE=false` in `.env` and run `docker compose up -d` for SDEX onboarding. The Portainer stack defaults to real mode.

The default host publication is `127.0.0.1:8080`. To allow another trusted device, deliberately set `CONNECTMAP_BIND_ADDRESS` to the relevant host address and configure the site's access controls. `0.0.0.0` exposes the port on all host interfaces. The application has no built-in authentication.

The container runs as UID/GID `10001`, drops capabilities, enables `no-new-privileges`, uses a read-only root filesystem and writes only to `/data` and ephemeral `/tmp`. A fresh named volume is initialized by Docker. If using a bind mount instead, grant UID `10001` access to its directory without making it world-writable.

## Portainer and edgeNode

Select the target **Docker environment** in Portainer. Build the image there so its architecture matches the host. An image built locally on a Windows AMD64 workstation is not automatically an ARM64 image for an edgeNode.

### Build from a source context

On the workstation, from the repository root:

```powershell
python scripts/verify_release.py
python scripts/build_release.py
```

The script creates:

- `dist/sdex-connectmap-1.0.0-source.zip`: complete source repository with documentation and notices.
- `dist/sdex-connectmap-1.0.0-build-context.tar`: source files needed for Docker to build the image.

In Portainer:

1. Open **Images > Build a new image > Upload** in the target environment.
2. Upload the build-context TAR. Use image name `sdex-connectmap:1.0.0` and Dockerfile path `Dockerfile`.
3. Build the image. The environment needs access to the configured base-image and package registries.
4. Open **Stacks > Add stack** and paste [portainer-stack.yml](../portainer-stack.yml).
5. Supply the deployment variables, initially retaining loopback publication. Disable forced image re-pulling when using the local build.
6. Deploy the stack, check the service logs/health, then open the UI through the intended host or authenticated proxy.

The TAR is a **build context**, not a saved image. Do not use **Images > Import** for it. The stack file does not build source itself and does not assume that an image was published to a registry.

### Connectivity

Use an SDEX origin reachable **from the ConnectMap container**. `localhost` inside that container refers to ConnectMap, not another container or the edgeNode host. A Docker DNS service name works only where containers share a network; a host or gateway name requires a valid DNS/address route.

The supplied stack does not modify an existing SDEX network or service. Any network attachment is an administrator decision. Reachability checks should target only the configured origin; no discovery scan is necessary.

## Reverse proxy

For access beyond the Docker host, put the service behind an authenticated HTTPS reverse proxy or VPN. Protect all application paths. Forward the external Host and scheme consistently, disable buffering for `/api/events`, allow long-lived event streams and apply appropriate connection limits.

Browser mutation guards compare the request origin with its effective scheme and Host. A misconfigured proxy can allow reads while rejecting writes with `403 cross_origin_request`. Uvicorn trusts forwarded headers from loopback by default. A proxy in another container therefore needs its exact trusted address in `FORWARDED_ALLOW_IPS`, supplied in ConnectMap's container environment. Preserve Host and `X-Forwarded-Proto`; do not use `*` when clients can reach the backend directly.

## Persistence, backup and upgrade

Retain the named `/data` volume. It contains credentials, topology and saved map state; generated encryption keys must remain with their database. With `CONNECTMAP_SECRET_KEY`, back up the external key through its existing secret-management process instead.

For a consistent backup, stop **only this ConnectMap service** in a planned maintenance window, back up the entire data volume with restricted access, then restart it. Do not copy only `connectmap.db` while writes are active: SQLite WAL files may contain recent changes. Restore backups to an isolated volume first and verify decryption and map state.

For an upgrade:

1. Read the changelog and audit for the target version.
2. Back up the volume and encryption-key source.
3. Build the new image in the target environment.
4. Recreate only ConnectMap with the same volume and key.
5. Check health, configuration, topology freshness and persisted editor state.

Startup migrates supported schemas. Downgrades after migration are not guaranteed; recover the pre-upgrade backup with the matching image if needed. Never remove the volume merely to clear an error unless intentionally discarding the workspace.

## Acceptance checks

The [release audit](../RELEASE_AUDIT.md) is the evidence record. To run isolated container acceptance on a Docker-capable host:

```powershell
docker build --tag sdex-connectmap:1.0.0 .
python scripts/container_acceptance.py --image sdex-connectmap:1.0.0
```

These checks use synthetic data. Real SDEX acceptance should separately confirm login, required module reads, TLS identity, manual/scheduled refresh and persisted layout on the intended host. Device connection state alone does not verify every API module or image architecture.

I have tested the application and its features on an ARM-based edgeNode. Changes to the image, dependencies or target environment should still receive their own acceptance check; that field test is not a result for every future build.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Port unavailable remotely | Loopback publication is the default; review bind address, firewall and authenticated ingress |
| Image not found in Portainer | Build/tag it in the same target Docker environment and disable forced re-pull |
| SDEX unreachable | Validate the configured origin's route/DNS from the container, not just the browser |
| TLS verification failure | Check CA trust and hostname/IP SAN; keep verification enabled |
| Password cannot be decrypted | Restore the matching generated/external encryption key or re-enter the profile password |
| Partial discovery | Check individual module availability, licensing, read permissions and response diagnostics |
| Missing gateway cable | Check known interface names/prefixes and explicit overrides; unresolved data is not inferred |
| `403 cross_origin_request` behind proxy | Preserve Host/scheme and configure Uvicorn's exact trusted proxy address |
| Container healthy but map stale | Health confirms the local service; inspect SDEX freshness and active alarms separately |
