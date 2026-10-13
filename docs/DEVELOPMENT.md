# Development and testing

Use Python 3.12 and Node.js 22. Work from the repository root. Production serves the compiled UI through FastAPI; Vite is only needed for frontend development and builds.

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

On Linux, use `python3.12 -m venv .venv` and `.venv/bin/python` in place of the Windows interpreter path. Keep both installations local to the checkout. `node_modules`, the virtual environment and frontend build output are ignored by Git.

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

Open `http://localhost:8080`; stop with `Ctrl+C`. This uses synthetic discovery and a data directory outside the source checkout. It does not need SDEX credentials. Use `stable`, `partial`, `missing_modules` or `offline` to exercise predictable state and failure scenarios.

For hot frontend development, leave the backend running and run `npm run dev -- --host 127.0.0.1` from `frontend/` in a second shell. The Vite `/api` proxy defaults to `http://127.0.0.1:8080`. `VITE_API_PROXY` can change that target; use a local test backend.

## Backend checks

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m ruff check app tests
..\.venv\Scripts\python.exe -m pytest
Pop-Location
```

The suite uses synthetic responses and temporary storage. It covers authentication/client failures, normalization, interface assignment, collection scheduling, persistence, encryption, API validation and local visual topology. Tests must not require an operational SDEX server.

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

On Linux, point `CONNECTMAP_TEST_PYTHON` to `.venv/bin/python` and use `npx playwright install --with-deps chromium` on a suitable test host. When the override is absent, Playwright uses `python` from `PATH`.

Browser tests launch `scripts/e2e_server.py` with temporary data directories and synthetic visual/editor scenarios. That launcher clears inherited SDEX/application settings and forces Mock Mode. Test servers use loopback ports `8765` and `8766`; those ports must be free. A built frontend is required. Failure traces and generated screenshots may contain test data and are excluded from the source archive.

With the compiled frontend available, run `python scripts/source_acceptance.py` using the installed backend environment. It starts disposable Mock Mode processes on a free loopback port and checks HTTP UI, SSE, settings and encryption-key persistence across a process restart. It never uses a saved deployment profile.

## Dependency updates

Python direct dependencies are in `backend/requirements.in` and `backend/requirements-dev.in`. The lockfiles contain resolved versions and hashes. Using the lock generator recorded in the audit:

```powershell
python -m piptools compile --generate-hashes --strip-extras --output-file backend/requirements.txt backend/requirements.in
python -m piptools compile --generate-hashes --strip-extras --output-file backend/requirements-dev.txt backend/requirements-dev.in
.\.venv\Scripts\python.exe -m pip install --require-hashes -r backend/requirements-dev.txt
```

Install `pip-tools` in a separate tooling environment if needed. Review the full lock diff and test on supported platforms. npm updates must change `package.json` and `package-lock.json` together. Update [third-party notices](../THIRD_PARTY_NOTICES.md) whenever the resolved runtime set changes.

## Packaging and security review

```powershell
.\.venv\Scripts\python.exe scripts/verify_release.py
.\.venv\Scripts\python.exe scripts/build_release.py
```

The verifier checks the source package; the builder creates source ZIP and Docker build-context TAR artifacts under `dist/`. Generated archives are local outputs and are not source files to commit.

Dependency advisory, static-security and secret-scanner tools are separate review tools. The [release audit](../RELEASE_AUDIT.md) identifies the exact commands/tools executed and their scope. Run them against a clean source copy and review findings rather than treating a scanner's silence as a comprehensive security guarantee.

For Docker changes, also run the isolated checks described in [Deployment](DEPLOYMENT.md). Native ARM64 runtime acceptance, a real SDEX integration test and an image OS vulnerability scan are separate checks from source builds and synthetic browser tests.

## CI

The [workflow](../.github/workflows/ci.yml) installs locked dependencies, checks backend/frontend behavior and builds the source. Docker jobs verify the container separately. It grants read-only repository permissions and has no image publication, release, tag or deployment job. Inspect the actual job results after upload; local execution and a valid workflow file are not remote CI results.
