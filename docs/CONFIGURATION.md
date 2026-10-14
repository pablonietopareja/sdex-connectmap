# Configuration

Application settings are validated at startup. Compose/Portainer substitutions are deployment settings, distinct from the backend's environment. Use `.env.example` as a reference; keep the actual `.env` private.

## Application environment

| Variable | Default | Meaning |
| --- | --- | --- |
| `CONNECTMAP_HOST` | `127.0.0.1` in source; `0.0.0.0` in Docker | Application listener; Docker separately restricts host publication |
| `CONNECTMAP_PORT` | `8080` | Application HTTP port, 1–65535 |
| `CONNECTMAP_DATA_DIR` | `/data` on Linux; `.connectmap-data` in the current directory on Windows | Key and default database directory |
| `CONNECTMAP_DATABASE_URL` | Database in the data directory | Optional `sqlite:///` path override |
| `CONNECTMAP_STATIC_DIR` | Auto-detected built frontend | Directory containing `index.html`, `assets/` and `icons/` |
| `CONNECTMAP_SECRET_KEY` | Generated `.connectmap-key` | Credential-encryption key; preserve across restarts |
| `CONNECTMAP_LOG_LEVEL` | `INFO` | Operational logging level |
| `CONNECTMAP_MOCK_MODE` | `false` | Synthetic discovery; never merged with real SDEX data |
| `CONNECTMAP_MOCK_SCENARIO` | `dynamic` | `dynamic`, `stable`, `visual_preview`, `editor_preview`, `partial`, `missing_modules` or `offline` |
| `CONNECTMAP_DEFAULT_REFRESH_SECONDS` | `300` | Initial interval: `60`, `300`, `600`, `900`, `1800` or `3600` |
| `CONNECTMAP_REQUEST_TIMEOUT_SECONDS` | `15` | Default SDEX timeout, 1–120 seconds |
| `CONNECTMAP_MAX_CONCURRENCY` | `4` | Concurrent discovery reads, 1–32 |
| `CONNECTMAP_MAX_BODY_BYTES` | `262144` | Maximum incoming mutation body |
| `CONNECTMAP_DISABLE_DOCS` | `false` in code; `true` in supplied deployment | Disable `/api/docs` and `/api/openapi.json` |

Boolean values accept `true/false`, `1/0`, `yes/no` or `on/off`. Invalid supported-range values fail startup instead of silently changing behavior.

## Deployment substitutions

| Variable | Default | Meaning |
| --- | --- | --- |
| `CONNECTMAP_IMAGE` | `sdex-connectmap:1.0.1` | Local image name/tag |
| `CONNECTMAP_BIND_ADDRESS` | `127.0.0.1` | Host address receiving the published port |
| `CONNECTMAP_HOST_PORT` | `8080` | Host HTTP port mapped to container port 8080 |

`CONNECTMAP_BIND_ADDRESS` is not the container's listener. The process listens on `0.0.0.0:8080` **inside** the container while Docker restricts the default host publication to loopback. Set a specific trusted host address or `0.0.0.0` only after configuring access controls.

When placing an HTTPS proxy in another container, add `FORWARDED_ALLOW_IPS` to the application container's environment with that proxy's exact trusted address. This is a Uvicorn setting, not an AppSettings option. The supplied files do not grant blanket forwarded-header trust. See [Deployment](DEPLOYMENT.md) for the origin-check requirements.

## SDEX profile

Normal use saves the profile through onboarding or Settings. The browser receives its URL, username, TLS mode and a password-present flag; it never receives the password.

An optional bootstrap profile uses:

| Variable | Default | Meaning |
| --- | --- | --- |
| `SDEX_BASE_URL` | Unset | HTTP/HTTPS origin, for example `https://sdex.example.test:8443` |
| `SDEX_USERNAME` | Unset | Dedicated SDEX account |
| `SDEX_PASSWORD` | Unset | Account password; prefer entering through the UI |
| `SDEX_VERIFY_TLS` | `true` | Verify SDEX's certificate and identity |
| `SDEX_CA_CERT_PATH` | Unset | Existing `.pem` or `.crt` trust file for the environment profile |

All three bootstrap credentials must be set to create an environment profile. A saved database profile takes precedence. Updating environment credentials does not replace an existing saved profile. Mock Mode selects its synthetic client regardless of saved real credentials.

Origins reject embedded credentials, paths, query strings and fragments. Use the SDEX server address, not an individual device's address. Redirects are disabled, and inherited HTTP proxy variables are ignored.

### Private CA

Prefer a SDEX certificate trusted by the container's standard CA store, with a SAN matching the configured hostname/IP. For an **environment profile**, mount a public trust anchor read-only and set `SDEX_CA_CERT_PATH` to its container path. Do not mount the private CA key.

The UI does not currently configure a custom CA file, and a saved database profile does not retain `SDEX_CA_CERT_PATH`. Keep the environment profile as the effective profile when relying on that variable; saving a UI profile changes the trust source. A reverse proxy exposing SDEX with a normally trusted certificate is another option. Disabling TLS verification is limited to deliberate laboratory use and remains visibly warned.

## Saved settings and data

The selected refresh interval, theme, disabled-node visibility, manually supplied interface data, per-connection overrides, layout and visual edits persist in SQLite. `CONNECTMAP_DEFAULT_REFRESH_SECONDS` initializes a new workspace; it does not overwrite its chosen interval.

The default files are `/data/connectmap.db` and `/data/.connectmap-key`, plus SQLite WAL/journal files while running. Only the password is encrypted. The latest snapshot replaces the previous one; the application does not retain telemetry history or historical alarm acknowledgments.

If an external key is used, generate a random Fernet key and store it through the deployment's secret-management process:

```powershell
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

This command prints a secret. Do not put its output in a commit, screenshot or public report. Keep the same key across upgrades and backups; changing it requires re-entering the SDEX password.

## Health and freshness

`GET /api/health` returns database, scheduler, configuration, refresh and version status. An unconfigured workspace can be operationally healthy without SDEX data. The Docker healthcheck also allows a degraded SDEX snapshot when the database and scheduler remain functional. A healthy container therefore does not prove that all devices are connected.

Upstream GET responses are capped at 8 MiB and authentication responses at 64 KiB. Transient reads have at most two retries; authentication failures have bounded recovery. See [Architecture](ARCHITECTURE.md) and [Security](../SECURITY.md) for the collection and trust boundaries.
