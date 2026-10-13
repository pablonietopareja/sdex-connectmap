# Release audit

Candidate: **1.0.0 source release**, reviewed on **13 October 2026**.

**Decision: READY TO PUBLISH (SOURCE RELEASE).** Rights, source independence, clean installation, core synthetic behavior, security fixes, package integrity and documentation checks passed. No source-publication blocker remains. Optional container and field qualification below remains separate.

**Deployment qualification: INCOMPLETE for this source candidate.** The application and its features have been tested on an ARM-based edgeNode, including the original 1.0.0 container. That field deployment predates the distribution changes below. Container acceptance of the rebuilt candidate is recorded separately.

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

Local environment: Windows AMD64, Python 3.12.7, Node.js 24.18.0, npm 11.16.0. Tests use disposable data directories and synthetic SDEX responses. No live SDEX server is contacted by these tests.

| Check | Artifact and method | Result | Evidence and scope |
| --- | --- | --- | --- |
| Rights and licensing | Maintainer authorization; source/asset and dependency review | PASS | Application redistribution under MIT is authorized. Dependencies retain their own licenses; no private SDK or API manual is bundled. |
| Backend clean install | Fresh Python environment; `pip install --require-hashes -r backend/requirements-dev.txt` | PASS | Public dependencies resolved and installed without the development environment. |
| Backend tests | `cd backend; python -m pytest -q` | PASS | 271 tests passed, including a repeat from the separately extracted source with a fresh environment. One upstream Starlette test-client deprecation warning remains; runtime tests pass. |
| Python lint and format | Ruff 0.11.13; backend and release scripts | PASS | Narrow suppressions identify fixed local tooling and container-only paths. |
| Frontend install, lint, unit tests and build | `npm ci`, `npm run lint`, `npm test`, `npm run build` | PASS | 138 synthetic unit/component tests passed; production assets built locally. |
| Browser acceptance | Chromium; `npm run test:e2e` and `npm run test:e2e:editor` | PASS | 3 tests passed against the actual backend: topology/themes/details/cable styles, Rack/Switch/link editing and reload persistence, plus status/settings/no-overflow checks at 1280, 768 and 390 pixels. |
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
| GitHub Actions execution | Workflow source and security/container jobs | NOT RUN | The repository has not been uploaded. No remote publishing job is configured. |
| Compose CLI validation | `docker compose config --quiet`; Portainer stack equivalent | NOT RUN | Docker CLI is unavailable on the local host. |
| Docker candidate build and runtime | Packaged context; `python scripts/container_acceptance.py --image sdex-connectmap:1.0.0` | NOT RUN | Docker CLI/daemon unavailable. CI defines native AMD64 and ARM64 build/startup/persistence checks. |
| Native AMD64/ARM64 candidate runtime | Native Linux container jobs | NOT RUN | No suitable container host was used during this review. Registry manifests list both architectures; that is not runtime acceptance. |
| Real SDEX candidate integration | Authorized, read-only field environment | NOT RUN | Local verification deliberately uses synthetic fixtures. |
| Original ARM edgeNode deployment | Maintainer field testing of 1.0.0 | PASS | Original application and features tested successfully; does not replace candidate container acceptance. |
| Container OS vulnerability scan | Trivy/Grype or equivalent on rebuilt image | NOT RUN | No rebuilt candidate image available locally. |

The lockfiles were generated with pip-tools 7.6.2. [Runtime CycloneDX inventories](docs/sbom/README.md) cover the locked Python distributions and npm's non-development graph; they exclude OS packages, embedded native libraries and browser binaries. License inventories match all 21 Python runtime entries and all 28 non-development npm lock entries, with retained upstream notices for every entry.

The original source and deployment-state file hashes were checked again after preparation and remained unchanged. All acceptance processes and storage were disposable; no existing service, production volume or SDEX configuration was modified.

## Security and compatibility boundaries

The UI/API has no built-in sign-in. Anyone with access can view the inventory and change ConnectMap settings; deploy behind controlled ingress, authentication and HTTPS as appropriate. Origin checks help with browser requests but do not authorize callers. The configured SDEX origin is an administrator-controlled network target; there is no destination allowlist. Restrict outbound reachability at the deployment boundary.

TLS verification defaults to enabled. Only the saved SDEX password is encrypted. Protect the database, generated encryption key and backups together. Addresses, usernames, topology and visual settings remain plaintext infrastructure inventory. SSE queues are bounded per subscriber; the total subscriber count is not capped. Use one application worker and limit connections at ingress.

Discovery depends on the configured SDEX modules, permissions and field availability. The graph visualizes API configuration and local edits rather than proving physical cabling. Missing status remains unknown; partial or cached discovery is identified. This release stores the latest snapshot rather than a telemetry history. Product names describe integrations and do not imply vendor certification.

See [Security](SECURITY.md), [Licensing](docs/LICENSING.md) and [Deployment](docs/DEPLOYMENT.md) for operating instructions.
