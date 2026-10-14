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

Open `http://localhost:8080` and stop with `Ctrl+C`. This uses synthetic data, a separate local data directory and no SDEX credentials. The `stable`, `partial`, `missing_modules` and `offline` scenarios exercise different expected states and failure modes. Mock Mode uses demo-specific status text rather than reporting that a real SDEX server is online.

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

Real-mode status wording is exercised with synthetic browser API responses while the test backend remains in Mock Mode. Those assertions do not contact or qualify a real SDEX server.

The editor suite waits for stable SVG geometry and viewport animation before selecting cable paths. It tests that selecting an existing cable reveals the saved waypoint **without creating or writing a new route**, and retains the Rack/Switch, bend, reload and other layout assertions. Avoid replacing the synchronization with a fixed timeout or weakening the waypoint checks.

Rack resize tests match the intended element ID and request payload, verify the returned dimensions, and wait for the save to complete and the rendered/persisted capacity to agree before closing properties. The consecutive resize regression checks `2×2 → 1×3 → 1×2 → 1×3`, membership, empty slots, source node identities and state after reload. Unit regressions separately cover retained drafts during unrelated refreshes and rejection of older topology responses.

To repeat the complete editor suite ten times with a fresh test-server lifecycle on each run, use this PowerShell loop from `frontend/`:

```powershell
for ($editorRun = 1; $editorRun -le 10; $editorRun++) {
    npm run test:e2e:editor
    if ($LASTEXITCODE -ne 0) { throw "Editor acceptance failed on run $editorRun" }
}
```

On Linux, the equivalent shell loop is:

```sh
for editor_run in $(seq 1 10); do
    npm run test:e2e:editor || exit 1
done
```

These commands are reproducible stress checks, not claims that they have passed on both platforms. Record the OS, toolchain, exact source revision and individual run results. A single successful rerun does not establish that an intermittent failure has been eliminated. Browser failure traces and screenshots are development artifacts excluded from the source archive. CI retains Playwright failure evidence, when generated, for 14 days; image-review artifacts are retained separately.

## Standalone startup and container acceptance

From the project root after installing the backend dependencies and building the frontend:

```powershell
.\.venv\Scripts\python.exe scripts/source_acceptance.py
.\.venv\Scripts\python.exe scripts/verify_release.py
.\.venv\Scripts\python.exe scripts/build_release.py
```

`source_acceptance.py` starts isolated Mock Mode processes and checks HTTP UI, SSE, settings persistence and retained encryption keys across restart.

### Upgrade acceptance

Use an actual 1.0.0 source checkout as the baseline. Replace the example path with that source root; it must contain `backend/app/` and report version 1.0.0:

```powershell
.\.venv\Scripts\python.exe scripts/upgrade_acceptance.py --baseline 'C:\path\to\sdex-connectmap-1.0.0'
```

The script imports the baseline and current code in separate processes. It creates temporary synthetic SQLite/key state, verifies profile decryption, schema, source identities, settings, interfaces, layout, viewport and visual relationships after upgrade, then checks that current-source writes survive another process restart. It does not use existing data or contact SDEX. This is source/database compatibility evidence, separate from Docker volume or target-hardware acceptance.

### Container acceptance

On a Docker-capable host:

```powershell
docker compose config --quiet
docker compose -f portainer-stack.yml config --quiet
docker build --tag sdex-connectmap:1.0.1 .
python scripts/container_acceptance.py --image sdex-connectmap:1.0.1
```

Container acceptance creates a disposable loopback-published container and volume. It checks health, the served frontend, synthetic topology, UID `10001`, settings and key persistence after restart. It re-reads Docker's published ephemeral host port after restart because Docker may assign a different port. Do not attach it to operational SDEX data or volumes.

## Dependency updates

Direct Python requirements live in `backend/requirements.in` and `backend/requirements-dev.in`. The respective `.txt` lockfiles contain resolved versions and hashes. The recorded lock generator is pip-tools 7.6.2.

```powershell
python -m piptools compile --generate-hashes --strip-extras --output-file backend/requirements.txt backend/requirements.in
python -m piptools compile --generate-hashes --strip-extras --output-file backend/requirements-dev.txt backend/requirements-dev.in
.\.venv\Scripts\python.exe -m pip install --require-hashes -r backend/requirements-dev.txt
```

Install pip-tools in a dedicated tooling environment if needed. Review changed lockfiles and re-run compatibility/security checks. npm dependencies use `frontend/package-lock.json`; update it with `package.json`. Review third-party licenses and update [Third-party notices](../THIRD_PARTY_NOTICES.md) whenever the resolved runtime graph changes.

After updating the runtime lock and retained upstream license inventory, regenerate the frontend SBOM from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts/build_frontend_sbom.py
.\.venv\Scripts\python.exe scripts/verify_release.py
```

The generator includes every non-development npm lock entry, its upstream license and dependency/peer references. See [Runtime inventories](sbom/README.md) for scope and exclusions; an application SBOM is not a container OS inventory.

## Packaging and security review

```powershell
.\.venv\Scripts\python.exe scripts/verify_release.py
.\.venv\Scripts\python.exe scripts/build_release.py
```

The verifier checks public source boundaries, inputs, local documentation links and SVG safety constraints. The builder produces the source ZIP and Docker context TAR under `dist/`. Those generated archives are not intended for Git commits.

The CI security job runs a pinned version of pip-audit, npm audit, Bandit and Gitleaks against its configured scope. See [Security](../SECURITY.md) and the [Release audit](../RELEASE_AUDIT.md) for the explicit trust boundaries. Scanner success is not evidence of an OS-image advisory scan or independent penetration test.

### Built-image inventory

After building the local image, use checksum-verified Trivy 0.75.0 and a **new** output directory:

```powershell
.\.venv\Scripts\python.exe scripts/image_security_report.py --image sdex-connectmap:1.0.1 --output artifacts/review/image-scan --cache-dir artifacts/review/trivy-cache --trivy trivy
```

The helper records the immutable local image ID, scanner/database metadata, full unsuppressed vulnerability/license inventory and a separate HIGH/CRITICAL gate. It preserves earlier reports by refusing to overwrite stored scan files. Do not commit the reports or include them in source archives.

By default, completed scans return zero even when the recorded vulnerability gate is **FAIL**; operational or evidence-consistency errors return nonzero. Add `--enforce-high-critical` when intentionally using that threshold as a local policy: findings return exit code `42`. This option changes enforcement, not the inventory, severities or retained findings.

## CI and revision-specific evidence

The [GitHub Actions workflow](../.github/workflows/ci.yml) runs source checks on Ubuntu 24.04 and Windows 2022, a security job on Ubuntu and native Docker jobs on `ubuntu-24.04` (AMD64) and `ubuntu-24.04-arm` (ARM64). Docker jobs depend on the source and security jobs. The workflow does not publish images, tags or releases automatically.

The 1.0.0 baseline commit `90f89c0d91c57475dd9a893530b167481a07b1f0` passed [run #38412311674, attempt 2](https://github.com/pablonietopareja/sdex-connectmap/actions/runs/38412311674/attempts/2). Attempt 1 failed the Linux editor test after a Rack dimension change; the rerun passed without a source change. Preserve that failure when assessing test reliability.

The changed 1.0.1 candidate has not yet run in remote CI. Local results, repeated editor acceptance and unexecuted checks belong in the [release audit](../RELEASE_AUDIT.md) with their exact revision and environment. Do not transfer historical counts or successful job conclusions to a new commit.

Native architecture tests in CI are distinct from maintainer field experience with Raspberry Pi/edgeNode and a real SDEX API. Site-specific networking, firmware, permissions and certificates still require deployment testing. The native container jobs now run Trivy 0.75.0 through the same report helper and upload the complete evidence from runner temporary storage for 14 days. Image findings are informational; execution errors fail the job. No additional CI job is added, and a successful job is not a passing vulnerability gate or release-risk acceptance.
