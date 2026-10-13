# Deployment

The SDEX ConnectMap image contains a Python backend and compiled React frontend. Node.js, the Docker socket, a running Portainer API session and privileged container access are not required at runtime. The Docker environment must be able to reach the configured SDEX origin for real discovery.

## Docker Compose

From a clean checkout:

```powershell
Copy-Item .env.example .env
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail 100 connectmap
```

Open `http://localhost:8080`. The supplied Compose definition defaults to offline Mock Mode. Set `CONNECTMAP_MOCK_MODE=false` in the private `.env` file and recreate the service using `docker compose up -d` before connecting to a real SDEX installation. The Portainer stack defaults to real mode.

The host port is published to `127.0.0.1:8080` by default. To connect from another trusted device, deliberately configure `CONNECTMAP_BIND_ADDRESS` and provide an authenticated ingress or other network-level controls. Setting it to `0.0.0.0` exposes the HTTP endpoint through every host interface. **ConnectMap does not have built-in user accounts or access roles.**

The runtime uses UID/GID `10001`, a read-only root filesystem, dropped capabilities, `no-new-privileges`, a writable `/data` volume and an ephemeral `/tmp` mount. When using a bind mount instead of the named volume, grant the runtime UID access without making the data directory world-writable.

## Portainer and edgeNode

Choose the target Docker environment in Portainer. Build the container for that environment's architecture: an image built on a Windows AMD64 workstation is not automatically an ARM64 image suitable for an edge gateway.

### Build from source

From the repository root on the workstation:

```powershell
python scripts/verify_release.py
python scripts/build_release.py
```

The packaging script creates:

- `dist/sdex-connectmap-1.0.0-source.zip` — complete redistributable source tree and documentation.
- `dist/sdex-connectmap-1.0.0-build-context.tar` — input source context for a Docker build.

In Portainer:

1. Open **Images > Build a new image > Upload** for the target Docker environment.
2. Upload the **build-context TAR**, tag it `sdex-connectmap:1.0.0` and set the Dockerfile path to `Dockerfile`.
3. Build the image. Access to base-image/package registries is required during the build.
4. Open **Stacks > Add stack** and use [portainer-stack.yml](../portainer-stack.yml).
5. Configure relevant variables, network access and host publication. When using a locally built image, avoid forcing a registry pull.
6. Deploy the stack and verify container health, logs, onboarding and topology freshness.

The TAR is **not an exported Docker image**. It belongs under **Images > Build**, not **Images > Import**. The supplied Portainer stack references an image that must already exist in the target environment; it does not build or publish that image.

### SDEX connectivity

Use an SDEX origin that resolves and is reachable **from inside the ConnectMap container**. `localhost` there refers to ConnectMap itself, not the host, SDEX container or edgeNode gateway. Container service DNS names require an appropriate shared Docker network. Do not change an operating SDEX network or scan the plant without administrative authorization.

ConnectMap reads supported SDEX modules and system/network data. Its authentication POST requests are limited to login, session refresh and logout. Rack, Switch and cable changes are local visual edits and do not configure industrial devices.

## Verified container acceptance

The [GitHub Actions run #38408177090](https://github.com/pablonietopareja/sdex-connectmap/actions/runs/38408177090), for commit `2ce9fac20c9adb36087a779f636bc62f72cee8d0`, passed **native AMD64 and ARM64** container jobs. Each job:

- Validated `compose.yaml` and `portainer-stack.yml` with Docker Compose.
- Built the exact packaged Docker context on its Linux architecture.
- Started a disposable, non-privileged container in **synthetic Mock Mode**.
- Verified the HTTP UI/API, `/api/health`, non-root UID `10001` and persisted settings/credential key after restart.
- Confirmed the random published test port stayed bound to loopback, including after restart.

This verifies the image build and its core runtime behavior on the two tested runner architectures. It **does not** verify real SDEX connectivity, a particular Raspberry Pi OS or edgeNode firmware release, production network routes or a full OS vulnerability/license scan.

I have also operated ConnectMap on Raspberry Pi and edgeNode with a real SDEX API. Those are **maintainer-reported field tests**, separate from the automated synthetic CI results. The exact public build still requires site-specific acceptance before production deployment.

For a local repetition on a Docker-capable host:

```powershell
docker compose config --quiet
docker compose -f portainer-stack.yml config --quiet
docker build --tag sdex-connectmap:1.0.0 .
python scripts/container_acceptance.py --image sdex-connectmap:1.0.0
```

The acceptance script uses a disposable container/volume. Do not point it at operational SDEX data.

## Reverse proxy and access control

For access outside the Docker host, protect the application behind an authenticated HTTPS reverse proxy or VPN. Apply protection to **all application paths**, including REST endpoints, settings and the SSE stream at `/api/events`. Keep SSE proxy buffering disabled and allow long-lived connections with reasonable connection limits.

Browser mutation guards compare the request's effective Origin with its scheme/Host. A misconfigured proxy may allow reads but reject writes with `403 cross_origin_request`. Uvicorn trusts forwarded headers from loopback by default; when an HTTPS proxy is in another container, set `FORWARDED_ALLOW_IPS` to that proxy's **specific trusted address**. Preserve `Host` and `X-Forwarded-Proto`. Avoid `*` when clients can contact the backend directly.

ConnectMap has no destination allowlist for user-configured SDEX origins. Limit ingress to trusted administrators and outbound connectivity to approved SDEX hosts. Do not disable TLS verification merely to bypass an unknown certificate problem.

## Persistence, backup and upgrade

Keep the `/data` volume across container recreation. It stores the database, saved topology, layout and connection profile. The generated `.connectmap-key` must be backed up with the database; if using `CONNECTMAP_SECRET_KEY`, preserve that external key separately. Other infrastructure inventory in SQLite is not encrypted.

To obtain a consistent backup, stop **only the ConnectMap service** during planned maintenance, back up the complete volume securely, and restart it. Do not copy only `connectmap.db` while SQLite writes are active: WAL files may contain recent transactions. Restore to an isolated volume first and check that credentials can be decrypted and visual state survives.

Upgrade steps:

1. Read the target release notes and audit.
2. Back up the current data volume and encryption key.
3. Build the intended version on the target architecture.
4. Recreate only ConnectMap with the retained volume and key.
5. Verify health, SDEX access, snapshot freshness, and persisted layout/editor state.

Supported database migrations run on startup. Downgrades are not guaranteed. Recover the pre-upgrade backup and matching image rather than deleting operational state.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Port is not reachable remotely | Default loopback binding, firewall, ingress authentication and intended host address |
| Portainer cannot find the image | Build/tag it in the same target environment; avoid forced registry re-pull |
| SDEX cannot be reached | Network route and DNS from the container; the configured SDEX origin |
| TLS verification fails | CA trust, certificate hostname/IP SAN and configured origin |
| Saved password cannot be decrypted | Restore the matching generated/external encryption key or re-enter the password |
| Discovery is partial | Module availability, licensing, read permissions and reported SDEX diagnostics |
| A gateway cable cannot be resolved | Known `eth1`/`eth2` addressing and explicit manual interface overrides |
| Proxy causes `403 cross_origin_request` | Correct Host and scheme forwarding; exact trusted proxy address |
| Container healthy but map stale | `/api/health` covers the local service; inspect upstream freshness and alarms separately |

See [Configuration](CONFIGURATION.md), [Architecture](ARCHITECTURE.md) and [Security](../SECURITY.md) for the corresponding trust and persistence boundaries.
