# Release audit

- **Project:** SDEX ConnectMap
- **Version:** 1.0.0 source release
- **Reviewed:** 13 October 2026
- **Validated repository commit:** [`2ce9fac20c9adb36087a779f636bc62f72cee8d0`](https://github.com/pablonietopareja/sdex-connectmap/commit/2ce9fac20c9adb36087a779f636bc62f72cee8d0)
**GitHub Actions:** [Run #38408177090](https://github.com/pablonietopareja/sdex-connectmap/actions/runs/38408177090) — **SUCCESS**, five successful jobs.

**Release assessment: READY FOR SOURCE RELEASE.** The public source builds, passes its configured automated checks on Linux and Windows, and passes isolated native Linux AMD64 and ARM64 container acceptance. This assessment is bounded by the checks below; it is not an independent industrial certification, penetration test, image OS vulnerability assessment or guarantee of operation in every SDEX installation.

The validated commit contains the tested application and test-harness remediation. The subsequent visual change to the README's lead screenshot is included in the validated commit; it does not alter the runtime. A documentation-only update after this review will create a new commit and its own CI run. Do not confuse that future run with the completed evidence above.

## Published verification

The following results are taken from the [completed GitHub Actions run #38408177090](https://github.com/pablonietopareja/sdex-connectmap/actions/runs/38408177090), executed against the exact validated commit on 13 October 2026.

| GitHub Actions job | Result | Confirmed scope |
| --- | --- | --- |
| `source (ubuntu-24.04)` | **PASS** | Locked Python/npm installation, Ruff checks, 271 backend tests, 138 frontend tests, production frontend build, source startup/persistence, four Chromium tests across visual/editor suites, release verification and packaging. |
| `source (windows-2022)` | **PASS** | Equivalent source checks: 271 backend tests, 138 frontend tests, four Chromium tests and verified source packaging. |
| `security` | **PASS** | `pip-audit` for pinned runtime requirements, `npm audit`, Bandit medium/high checks, and Gitleaks scan of the extracted public source archive. |
| `container (ubuntu-24.04)` | **PASS** | Compose definition validation, native AMD64 Docker build from packaged source context, disposable container acceptance and persistence checks. |
| `container (ubuntu-24.04-arm)` | **PASS** | Compose definition validation, native ARM64 Docker build from packaged source context, disposable container acceptance and persistence checks. |

The container acceptance script checks a running HTTP UI and API, application health, synthetic topology in Mock Mode, the non-root UID `10001`, saved settings and the encryption key across container restart. Both container jobs completed with the acceptance script's explicit `PASS` message. A successful healthcheck shows the local service is operational; it does not prove that a real SDEX server is reachable or all devices are connected.

In the successful security job, pip-audit reported no known advisories for the tested Python dependency set, `npm audit` reported zero vulnerabilities, and Gitleaks reported no leaks in the extracted source. Bandit completed its configured review. These checks are useful but do not establish that the entire container, industrial integration or runtime environment is free of vulnerabilities.

## Earlier failure and remediation

The [initial run #38391343317](https://github.com/pablonietopareja/sdex-connectmap/actions/runs/38391343317), on commit [`da58b2d9a6c30ba5f78ccc2f6dda25be51dfd0ac`](https://github.com/pablonietopareja/sdex-connectmap/commit/da58b2d9a6c30ba5f78ccc2f6dda25be51dfd0ac), failed a Linux Chromium editor test; the dependent container jobs were skipped. Windows source and security checks passed.

Investigation showed an interaction-timing race: the test waited 400 ms during a 450 ms animated *Fit topology* transition, measured a moving SVG path and clicked a position that was no longer targetable. The saved route and waypoint remained intact. The corrected editor test waits for stable viewport and SVG geometry, validates selection and retains the waypoint/persistence assertions. A regression covers selecting the persisted cable after an animated fit without creating a new route or changing source connections.

A separate Docker acceptance harness issue was also corrected. Docker may assign a different random loopback host port when a disposable test container restarts. The test script now reads the current binding after restart and verifies that exposure remains limited to `127.0.0.1`. The test continues to use a disposable volume, dropped capabilities, a read-only root filesystem, UID `10001` and a persistent credential key.

Both corrections were published in commit [`8d8be32655e903716b080cf4d579cdf648f1a9a9`](https://github.com/pablonietopareja/sdex-connectmap/commit/8d8be32655e903716b080cf4d579cdf648f1a9a9). The [subsequent successful run #38401937560](https://github.com/pablonietopareja/sdex-connectmap/actions/runs/38401937560) passed all five jobs. The more recent run #38408177090 again passed all five jobs after a documentation-image change.

## Release and local verification record

The original public-source preparation and subsequent local remediation recorded these additional checks. They are retained as historical **local verification evidence**, not re-described as tasks executed by the latest documentation review.

| Check | Status | Evidence or scope |
| --- | --- | --- |
| Rights and original-code distribution review | **Maintainer-declared** | Application released under MIT with upstream dependency notices retained. This is not a third-party legal opinion or confirmation of any employer's ownership rights. |
| Clean locked backend installation | **PASS (local)** | Fresh Python installation with `pip install --require-hashes -r backend/requirements-dev.txt`. |
| Python lint/format and backend tests | **PASS (CI and local)** | Ruff validation; 271 tests on each CI source platform. Local remediation used Python 3.12 on Windows and Ubuntu. |
| Frontend lint, unit tests and build | **PASS (CI and local)** | 138 frontend tests per CI source platform, with successful production builds. |
| Browser acceptance | **PASS (CI and local)** | Two visual and two editor Chromium tests per CI source platform, including waypoint-selection regression. |
| Repeated Linux waypoint regression | **PASS (local)** | Three consecutive focused runs recorded by local remediation. Not a claim that CI ran `--repeat-each=3`. |
| Vite development proxy / Origin guard | **PASS (local)** | Isolated backend and Vite proxy acceptance with a successful same-origin settings mutation. |
| Python dependency advisory check | **PASS (CI and local)** | pip-audit of hash-locked runtime requirements; no known advisories in the tested set. |
| npm dependency advisory check | **PASS (CI and local)** | `npm audit`; zero known advisories reported in CI. |
| Bandit static security scan | **PASS (CI and local)** | Configured medium/high severity checks completed; earlier full local review noted three low-level string/fixture findings. |
| Gitleaks public-source scan | **PASS (CI and local)** | No leaks found in the extracted source archive. Scanner results are not a proof that every possible secret is absent. |
| Source boundaries and links | **PASS (CI)** | `scripts/verify_release.py` confirmed 240 public files, required build inputs, local links and SVG safety rules. |
| Deterministic archive packaging | **PASS (local)** | Prior verification compared repeat source ZIP / build-context TAR output and member hashes. CI builds a source ZIP and build context. |
| Separate-copy source installation/startup | **PASS (CI and local)** | `scripts/source_acceptance.py`: synthetic UI, health/SSE, settings and encryption-key persistence. |
| Compose CLI validation | **PASS (CI)** | Both `compose.yaml` and `portainer-stack.yml` validated in native Linux container jobs. |
| Native AMD64 Docker build and acceptance | **PASS (CI)** | Packaged-context build and disposable container runtime acceptance. |
| Native ARM64 Docker build and acceptance | **PASS (CI)** | Packaged-context build and disposable container runtime acceptance on `ubuntu-24.04-arm`. |
| Real SDEX integration by CI | **NOT RUN** | CI deliberately uses synthetic fixtures and does not connect to an industrial SDEX endpoint. |
| Raspberry Pi / edgeNode field operation | **PASS — maintainer reported** | Maintainer confirms operational container deployment and successful communication with a real SDEX API. No independent field-test log or exact-commit requalification is claimed. |
| Built-image OS / native-component vulnerability and licensing scan | **NOT RUN** | No evidenced Trivy, Grype or equivalent OS-level scan of the built candidate image. Application dependency reviews and runtime notices are not a substitute. |
| External penetration test / industrial certification | **NOT RUN** | Not commissioned or claimed. |

The local review also recorded successful hash-locked ARM64 runtime wheel availability, Windows and Ubuntu source checks, a clean public source archive, upstream license inventories and CycloneDX runtime dependency records. See [dependency inventories](docs/sbom/README.md) and [licensing](docs/LICENSING.md). The inventory does not enumerate all OS packages, browser binaries or native libraries in the final image.

## Source distribution and security boundaries

The release contains the FastAPI backend, React/TypeScript frontend, synthetic test fixtures, Docker/Portainer deployment definitions, canonical SVG assets, application tests, packaging scripts and public documentation. Operational databases, passwords, encryption keys, certificates, logs, deployment state and prebuilt private images are excluded. Public interface screenshots use synthetic Mock Mode.

The application performs SDEX discovery via supported read APIs. Authentication uses the necessary login, refresh and logout POST operations; ConnectMap does not issue commands that create SDEX connections or change industrial device values. Missing or failed module reads are represented as partial, unknown or stale information rather than fabricated topology.

The supplied container is non-root and requires neither `privileged` mode nor a Docker socket. The published host bind defaults to loopback. **The web application has no built-in user authentication**: clients able to reach the service can view the topology and modify ConnectMap configuration. Use controlled network access and an authenticated HTTPS reverse proxy or VPN when appropriate. Restrict outbound access to authorized SDEX destinations.

TLS verification defaults to enabled. Saved SDEX passwords are Fernet-encrypted, with the key preserved in `/data` or provided externally. Other stored information—including addresses, usernames, device inventory and visual settings—is not encrypted. Protect the data volume and backup material. The configured SDEX origin does not have an application-enforced destination allowlist; network segmentation remains important.

SQLite, the scheduler, refresh coordinator and SSE subscribers are process-local. Run one application process per data volume. SSE queues are bounded per subscriber but there is no total subscriber quota. Snapshot freshness, alarms and animated cables must not be interpreted as measurements of physical topology or live network traffic.

The software is published under the [MIT license](LICENSE), with the existing [third-party notices](THIRD_PARTY_NOTICES.md) and [licensing guidance](docs/LICENSING.md). The license declaration assumes the maintainer is authorized to distribute the original source and project assets. Vendor trademarks, source-code ownership and other third-party rights remain governed by their respective terms.

## Release conclusion

**Automated source and container acceptance: COMPLETE — PASS** for validated commit `2ce9fac20c9adb36087a779f636bc62f72cee8d0`.

**Maintainer field experience: REPORTED PASS** on Raspberry Pi and edgeNode with a real SDEX API, separately from the CI evidence.

**Residual verification:** built-image OS/native-component scanning, third-party penetration testing, industrial certification and exact-commit live-SDEX qualification have not been independently established.

The source release is suitable for public distribution within these boundaries. A GitHub tag or GitHub Release is a separate manual publishing decision and must not be assumed to exist.
