# Development and testing

Use Python 3.12 and Node.js 22. Work from the repository root. Production serves the compiled React UI through FastAPI; Vite is a development/build tool and is not required in the runtime image.

## Clean setup

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r backend/requirements-dev.txt
Push-Location frontend
npm ci
npm run build
Pop-Location
```

On Linux, create the environment with `python3.12 -m venv .venv` and use `.venv/bin/python` instead of the Windows executable path. Keep `node_modules`, `.venv`, generated frontend output, SQLite data and secrets outside version control.

## Local synthetic demo

After building the frontend:

```powershell
$env:CONNECTMAP_HOST = '127.0.0.1'
$env:CONNECTMAP_PORT = '8080'
$env:CONNECTMAP_MOCK_MODE = 'true'
$env:CONNECTMAP_MOCK_SCENARIO = 'dynamic'
$env:CONNECTMAP_DATA_DIR = Join-Path $env:TEMP 'sdex-connectmap-demo'
$env:CONNECTMAP_STATIC_DIR = Join-Path (Get-Location).Path 'frontend/dist'
Push-Location backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080
Pop-Location
```

Open `http://localhost:8080` and stop with `Ctrl+C`. This uses synthetic data, a disposable local directory and no SDEX credentials. The `stable`, `partial`, `missing_modules` and `offline` scenarios exercise different expected states and failure modes.

For frontend hot reload, leave the backend running and start `npm run dev -- --host 127.0.0.1` from `frontend/` in another shell. Vite's `/api` proxy targets `http://127.0.0.1:8080` by default; use `VITE_API_PROXY` when a different local test backend is required. Do not aim development tools at a live industrial gateway.

## Backend checks

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m ruff check app tests
..\.venv\Scripts\python.exe -m ruff format --check app tests
..\.venv\Scripts\python.exe -m pytest -q
Pop-Location
```

These tests use temporary SQLite data and synthetic SDEX responses. Coverage includes authentication and HTTP failures, adapter normalization, interface assignment, discovery, scheduling, encryption, API validation and persistent visual topology. The suite must not depend on a production SDEX instance.

## Frontend and browser checks

```powershell
$env:CONNECTMAP_TEST_PYTHON = (Resolve-Path .venv/Scripts/python.exe).Path
Push-Location frontend
npm run lint
npm test
npm run build
npx playwright install chromium
npm run test:e2e
npm run test:e2e:editor
Pop-Location
```

On Linux, point `CONNECTMAP_TEST_PYTHON` to `.venv/bin/python` and install Chromium dependencies with `npx playwright install --with-deps chromium`.

The Playwright suites start the disposable backend through `scripts/e2e_server.py`, explicitly remove inherited application/SDEX settings, and force Mock Mode. Their test ports are `8765` and `8766` on loopback. A compiled frontend must exist first.

The editor suite waits for stable SVG geometry and viewport animation before selecting cable paths. It tests that selecting an existing cable reveals the saved waypoint **without creating or writing a new route**, and retains the Rack/Switch, bend, reload and other layout assertions. Avoid replacing the synchronization with a fixed timeout or weakening the waypoint checks.

To repeat the focused Linux regression from `frontend/`:

```powershell
npx playwright test --config playwright.editor.config.ts --grep "selecting a persisted cable" --repeat-each=3
```

Browser failure traces and screenshots are development artifacts excluded from the source archive. The CI workflow retains only Playwright failure evidence, when generated, for 14 days.

## Standalone startup and container acceptance

From the project root after installing the backend dependencies and building the frontend:

```powershell
.\.venv\Scripts\python.exe scripts/source_acceptance.py
.\.venv\Scripts\python.exe scripts/verify_release.py
.\.venv\Scripts\python.exe scripts/build_release.py
```

`source_acceptance.py` starts isolated Mock Mode processes and checks HTTP UI, SSE, settings persistence and retained encryption keys across restart.

On a Docker-capable host:

```powershell
docker compose config --quiet
docker compose -f portainer-stack.yml config --quiet
docker build --tag sdex-connectmap:1.0.0 .
python scripts/container_acceptance.py --image sdex-connectmap:1.0.0
```

Container acceptance creates a disposable loopback-published container and volume. It checks health, the served frontend, synthetic topology, UID `10001`, settings and key persistence after restart. It re-reads Docker's published ephemeral host port after restart because Docker may assign a different port. Do not attach it to operational SDEX data or volumes.

## Dependency updates

Direct Python requirements live in `backend/requirements.in` and `backend/requirements-dev.in`. The respective `.txt` lockfiles contain resolved versions and hashes. The release preparation recorded pip-tools 7.6.2 as the lock generator.

```powershell
python -m piptools compile --generate-hashes --strip-extras --output-file backend/requirements.txt backend/requirements.in
python -m piptools compile --generate-hashes --strip-extras --output-file backend/requirements-dev.txt backend/requirements-dev.in
.\.venv\Scripts\python.exe -m pip install --require-hashes -r backend/requirements-dev.txt
```

Install pip-tools in a dedicated tooling environment if needed. Review changed lockfiles and re-run compatibility/security checks. npm dependencies use `frontend/package-lock.json`; update it with `package.json`. Review third-party licenses and update [Third-party notices](../THIRD_PARTY_NOTICES.md) whenever the resolved runtime graph changes.

## Packaging and security review

```powershell
.\.venv\Scripts\python.exe scripts/verify_release.py
.\.venv\Scripts\python.exe scripts/build_release.py
```

The verifier checks public source boundaries, inputs, local documentation links and SVG safety constraints. The builder produces the source ZIP and Docker context TAR under `dist/`. Those generated archives are not intended for Git commits.

The CI security job runs a pinned version of pip-audit, npm audit, Bandit and Gitleaks against its configured scope. See [Security](../SECURITY.md) and the [Release audit](../RELEASE_AUDIT.md) for the explicit trust boundaries. Scanner success is not evidence of an OS-image advisory scan or independent penetration test.

## Published CI results

The [GitHub Actions workflow](../.github/workflows/ci.yml) runs source checks on Ubuntu 24.04 and Windows 2022, a security job on Ubuntu and native Docker jobs on `ubuntu-24.04` (AMD64) and `ubuntu-24.04-arm` (ARM64). Docker jobs depend on the source and security jobs. The workflow does not publish images, tags or releases automatically.

**Latest verified run:** [#38408177090](https://github.com/pablonietopareja/sdex-connectmap/actions/runs/38408177090), commit `2ce9fac20c9adb36087a779f636bc62f72cee8d0`, **SUCCESS — five out of five jobs**.

The jobs recorded 271 passing backend tests, 138 frontend tests and four passing Chromium E2E tests on each source platform, plus native builds and isolated Mock Mode container acceptance on AMD64 and ARM64. The original Linux editor-test timing failure in [run #38391343317](https://github.com/pablonietopareja/sdex-connectmap/actions/runs/38391343317) was corrected and verified in subsequent successful runs.

Native architecture tests in CI are distinct from maintainer field experience with Raspberry Pi/edgeNode and a real SDEX API. Site-specific networking, firmware, permissions and certificates still require deployment testing. An OS-level vulnerability/license scan of the built image has not been established; it remains outside the current CI scope.
