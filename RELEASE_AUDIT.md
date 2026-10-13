# Release audit

Candidate: **1.0.0 remediation working tree**, based on commit **`da58b2d9a6c30ba5f78ccc2f6dda25be51dfd0ac`**, reviewed on **13 October 2026**. The fixes are local and have not been committed or pushed.

**Local remediation: PASS. CI acceptance: INCOMPLETE.** The Linux editor failure is reproduced and corrected; source checks pass locally on Windows and Ubuntu, and the exact packaged image passes native AMD64 acceptance. No fully successful remote workflow exists yet. A remote run of the fixes and native ARM64 acceptance remain pending.

**Deployment qualification: INCOMPLETE.** Native AMD64 synthetic container acceptance passes; native ARM64 acceptance and real SDEX integration of this snapshot remain separate. Maintainer field testing of the original ARM edgeNode deployment predates these changes and is not relabeled as candidate or CI acceptance.

## Published CI evidence

Latest observed run: [38391343317](https://github.com/pablonietopareja/sdex-connectmap/actions/runs/38391343317), commit [da58b2d9a6c30ba5f78ccc2f6dda25be51dfd0ac](https://github.com/pablonietopareja/sdex-connectmap/commit/da58b2d9a6c30ba5f78ccc2f6dda25be51dfd0ac), overall **FAIL**. The complete Linux job log and the run's job/step results were reviewed.

| Published job | Recorded conclusion | Scope |
| --- | --- | --- |
| `source (windows-2022)` | PASS | All source/browser/package steps completed |
| `source (ubuntu-24.04)` | FAIL | Editor test expected one visible saved waypoint after a cable click; received zero. Backend, frontend and both visual tests passed. |
| `security` | PASS | Declared dependency, Bandit and public-source Gitleaks checks |
| `container` | SKIPPED | Source matrix failure prevented native AMD64/ARM64 jobs from running |

**Last fully successful workflow run: none.** The repository's observed run history contains only the failed initial run. No newer successful run URL or SHA is claimed. The workflow retains `needs: [source, security]` for native container acceptance; it does not turn skipped jobs into success.

## Remediation and regression evidence

The unchanged revision reproduces the editor failure in clean Ubuntu Chromium. The test waited 400 ms after a 450 ms Fit topology animation, calculated a screen-space SVG point and then used a raw mouse click. The original failure trace shows the viewport moving approximately 1.4 pixels vertically between measurement and input. A diagnostic reproduction confirms the pointer events reach the adjacent device card, while the saved manual route still contains its `rack-bend` waypoint and the edge path remains unchanged. The failure is in test synchronization, not waypoint persistence or the selection behavior.

The editor test now waits for stable viewport/SVG geometry across animation frames, retries replaced or temporarily untargetable paths, and verifies edge selection before counting controls. Existing waypoint and reload-persistence assertions remain. A focused regression starts an animated fit, selects the persisted cable and confirms that the saved waypoint appears without a route write or connection-identity change. No application runtime or security behavior was changed.

Native Docker checks exposed a second harness issue: Docker 29 changed the random loopback host port across restart. The previous script continued querying the old port even though the restarted application was healthy. `scripts/container_acceptance.py` now reads the actual binding again and asserts that it remains `127.0.0.1`; random ports, disposable volumes, UID 10001 and all hardening flags are retained.

Visual/editor traces use separate result directories. Failed source jobs now retain only Playwright results for 14 days using a commit-pinned upload action. Baseline failure traces, pointer/route diagnostics, successful browser traces and exact Docker build/acceptance logs were retained outside the public source tree.

Tested file SHA-256 values:

- `frontend/e2e/editor.e2e.ts`: `62927927c9df21b94c4a82d74c4206978087309f88cf6bd55c40d0106afb98e6`.
- `scripts/container_acceptance.py`: `87c9d180365af2ba30c9ccadd7a401790380f5f4202e01c5c61866484a0b4178`.

These identify the tested local changes; they are not a new commit SHA.

## Source and distribution changes

The release uses the current FastAPI backend, React/TypeScript frontend, canonical SVG assets and synthetic test fixtures. All 36 Python runtime modules in the original ARM64 image matched the working source before the changes. The public repository starts without an existing database or saved SDEX profile.

- Added upstream response limits, authentication expiry validation and browser Origin checks for local mutations.
- Preserved the browser Host through Vite's development proxy so same-origin local configuration changes pass the new Origin guard.
- Removed embedded URI credentials and query parameters from displayed topology fields, including restored snapshots.
- Updated vulnerable Python dependencies and frontend development tools; retained the application architecture and frontend runtime libraries.
- Locked Python dependencies with hashes, retained the npm lockfile and pinned Docker base image digests.
- Defaulted direct source listening and host port publication to loopback; retained non-root containers, a writable data volume and a read-only root filesystem.
- Restored compact-screen access to the existing status details, including the Mock Mode indicator, without changing the desktop layout.
- Replaced machine-specific preview launchers with portable browser test setup and deterministic packaging scripts.
- Included MIT application licensing, actual upstream dependency notices and complete deployment/development documentation.

Deployment state, keys, certificates, logs, operational exports, installed packages and prebuilt images are excluded. Documentation images show the application using synthetic Mock Mode.

## Verification record

Clean local environments: Windows AMD64 with Python 3.12.7, Node.js 24.18.0 and npm 11.16.0; disposable Ubuntu 24.04.5 AMD64 under WSL2 with Python 3.12.3, Node.js 22.23.3 and npm 10.9.9. Playwright 1.61.1 uses Chromium 149.0.7827.55, matching the failed Linux CI browser. Tests use disposable data directories and synthetic SDEX responses. No live SDEX server is contacted.

| Check | Artifact and method | Result | Evidence and scope |
| --- | --- | --- | --- |
| Rights and licensing | Maintainer authorization; source/asset and dependency review | PASS | Application redistribution under MIT is authorized. Dependencies retain their own licenses; no private SDK or API manual is bundled. |
| Backend clean install | Fresh Python environment; `pip install --require-hashes -r backend/requirements-dev.txt` | PASS | Public dependencies resolved and installed without the development environment. |
| Backend tests | `cd backend; python -m pytest -q` | PASS | 271 tests passed on Windows and 271 on Ubuntu. One upstream Starlette test-client deprecation warning remains on each platform. |
| Python lint and format | Ruff 0.11.13; backend and release scripts | PASS | Narrow suppressions identify fixed local tooling and container-only paths. |
| Frontend install, lint, unit tests and build | `npm ci --ignore-scripts --no-audit --no-fund`, `npm run lint`, `npm test`, `npm run build` | PASS | 138 unit/component tests and production builds passed on Windows and Ubuntu. |
| Browser acceptance | Chromium; `npm run test:e2e` and `npm run test:e2e:editor` | PASS | Both platforms pass 2 visual and 2 editor tests, including the new persisted-waypoint selection regression. Original Rack/Switch/link editing, routes, themes, responsive views and reload assertions remain. |
| Repeated Linux selection regression | `npx playwright test --config playwright.editor.config.ts --grep 'selecting a persisted cable' --repeat-each=3 --trace on` | PASS | Three consecutive runs pass without a fixed delay, route write or relaxed assertion. |
| Development proxy integration | Actual Vite server, `VITE_API_PROXY` and disposable `scripts/e2e_server.py`; browser-Origin `PUT /api/settings` | PASS | Separate free loopback ports; proxied configuration mutation returns HTTP 200 and saves the requested interval. No real SDEX profile is used. |
| Python dependency audit | pip-audit 2.10.1; full hash-locked runtime requirements | PASS | No known advisories reported after upgrading affected dependencies. This is a dependency advisory check, not a vulnerability-free guarantee. |
| npm dependency audit | `npm audit`; entire frontend lockfile | PASS | No known advisories reported after refreshing development dependencies. |
| Static security review | Bandit 1.9.4; `bandit -r backend/app -ll` and full JSON review | PASS | Zero medium/high findings. Three low B105 findings are field-name/redaction strings and an intentional synthetic password fixture. |
| Public source secret scan | Gitleaks 8.30.0; `gitleaks dir <extracted-source> --redact --no-banner` | PASS | No findings in the public source/archive contents; compiled frontend assets also scanned with no findings. Generated installation state is not part of the public source. |
| Package boundaries and links | `python scripts/verify_release.py` | PASS | All 240 public files, required inputs, local links and SVG safety checks passed. No external symlinks or machine-specific home paths. |
| Archive integrity and reproducibility | `python scripts/build_release.py`; ZIP/TAR member hashes and repeated SHA-256 comparison | PASS | Source ZIP and build-context TAR contain the expected files at their root; extracted bytes match source. Repeated builds produce identical checksums. |
| Separate-copy install/startup | Extracted source outside the development tree; `python scripts/source_acceptance.py` | PASS | Fresh locked Python/npm installs, frontend lint/unit tests/build, HTTP compiled UI, Mock Mode, health, initial SSE, settings persistence and generated-key retention across process restart. No original tree dependency. |
| Staged source and Git whitespace | Disposable checkout; `git diff --cached --check` and staged file inventory | PASS | 240 source files staged at repository root on `main`; no credentials, installed packages or nested release folder. Two upstream license texts retain their original whitespace using narrow attributes. No commit or push was performed. |
| Deployment YAML structure | PyYAML 6.0.3 with duplicate-key rejection and security-setting assertions | PASS | Both definitions have loopback publication, a dedicated volume, read-only root, dropped capabilities and no-new-privileges. This is not Docker Compose CLI acceptance. |
| Linux ARM64 dependency availability | `pip download --require-hashes --only-binary=:all:` with Python 3.12 and compatible aarch64 manylinux tags | PASS | All 21 locked runtime distributions downloaded successfully. This checks wheel availability, not ARM execution. |
| Workflow lint | actionlint 1.7.12; `.github/workflows/ci.yml` | PASS | Syntax/action references checked locally; remote workflow execution remains separate. |
| GitHub Actions execution of local fixes | Updated workflow source and security/container jobs | NOT RUN | Changes are unpushed. The historical initial failure and skipped container job remain recorded above; no new remote conclusion exists. |
| Compose CLI validation | `docker compose config --quiet`; `docker compose -f portainer-stack.yml config --quiet` | PASS | Docker Compose 2.40.3 on disposable Ubuntu AMD64. |
| Native AMD64 packaged build/runtime | `DOCKER_BUILDKIT=1 docker build --progress=plain -t sdex-connectmap:ci-remediated - < candidate-build-context.tar`; `python scripts/container_acceptance.py --image sdex-connectmap:ci-remediated` | PASS | Docker 29.1.3, Buildx 0.30.1; exact delivered context built natively and passed Mock Mode, HTTP UI, healthcheck, UID 10001, settings/key persistence and cleanup. |
| Native ARM64 candidate runtime | Native Linux ARM64 container job | NOT RUN | No native ARM64 host was used; the original remote container matrix was skipped. Emulation or image manifests do not establish native acceptance. |
| Real SDEX candidate integration | Authorized, read-only field environment | NOT RUN | Local verification deliberately uses synthetic fixtures. |
| Original ARM edgeNode deployment | Maintainer field testing of 1.0.0 | PASS | Original application and features tested successfully; does not replace candidate container acceptance. |
| Built-image OS advisory/license scan | Trivy/Grype or equivalent on rebuilt image | NOT RUN | No built-image scanner was executed. Dependency/SAST checks and retained application notices do not cover every OS package or embedded native library. |

Exact native AMD64 artifact record:

- Docker build-context SHA-256: `8edc3a6eea306e00d5704cd1399bdb883b62dc7de88c7fb26e26d86486204669`.
- Local image ID: `sha256:85ea7b852d23cdbc777e01dfa668c7f82cf5df2c91fc4af3d5444ea587323383` (`amd64`); this is not a published registry digest.
- Final acceptance completed at `2026-10-13T12:33:45Z`.

Application runtime files, dependencies, MIT license, upstream notices and Docker deployment permissions are unchanged by this remediation. No repository push, image publication, tag or release was performed.

The lockfiles were generated with pip-tools 7.6.2. [Runtime CycloneDX inventories](docs/sbom/README.md) cover the locked Python distributions and npm's non-development graph; they exclude OS packages, embedded native libraries and browser binaries. License inventories match all 21 Python runtime entries and all 28 non-development npm lock entries, with retained upstream notices for every entry.

The original source and deployment-state file hashes were checked again after preparation and remained unchanged. All acceptance processes and storage were disposable; no existing service, production volume or SDEX configuration was modified.

## Security and compatibility boundaries

The UI/API has no built-in sign-in. Anyone with access can view the inventory and change ConnectMap settings; deploy behind controlled ingress, authentication and HTTPS as appropriate. Origin checks help with browser requests but do not authorize callers. The configured SDEX origin is an administrator-controlled network target; there is no destination allowlist. Restrict outbound reachability at the deployment boundary.

TLS verification defaults to enabled. Only the saved SDEX password is encrypted. Protect the database, generated encryption key and backups together. Addresses, usernames, topology and visual settings remain plaintext infrastructure inventory. SSE queues are bounded per subscriber; the total subscriber count is not capped. Use one application worker and limit connections at ingress.

Discovery depends on the configured SDEX modules, permissions and field availability. The graph visualizes API configuration and local edits rather than proving physical cabling. Missing status remains unknown; partial or cached discovery is identified. This release stores the latest snapshot rather than a telemetry history. Product names describe integrations and do not imply vendor certification.

See [Security](SECURITY.md), [Licensing](docs/LICENSING.md) and [Deployment](docs/DEPLOYMENT.md) for operating instructions.
