# Release audit

- **Project:** SDEX ConnectMap
- **Version:** 1.0.1 candidate, not yet committed or published
- **Review date:** 14 October 2026
- **Baseline HEAD:** [`90f89c0d91c57475dd9a893530b167481a07b1f0`](https://github.com/pablonietopareja/sdex-connectmap/commit/90f89c0d91c57475dd9a893530b167481a07b1f0), version 1.0.0
- **Candidate remote CI:** **PENDING**. The changed working tree has no remote CI result or release tag.

**Source candidate: GO for review and commit. Formal 1.0.1 GitHub Release: HOLD.** The selected runtime improves the measured image inventory while retaining application behavior and persistence. Its HIGH/CRITICAL vulnerability gate still fails; release requires explicit residual-risk acceptance and successful CI for the final revision. Native ARM64 candidate acceptance has not run locally. The local regression and distribution checks below are complete.

## Historical GitHub evidence

[Run #38412311674, attempt 2](https://github.com/pablonietopareja/sdex-connectmap/actions/runs/38412311674/attempts/2) concluded **SUCCESS** on the exact baseline HEAD on 13 October 2026. All five jobs passed:

| Job | Verified scope |
| --- | --- |
| `source (ubuntu-24.04)` | Locked installations, Python lint/format, 271 backend tests, 138 frontend tests, production build, source startup/persistence, two visual and two editor Chromium tests, public-source verification and packaging. |
| `source (windows-2022)` | Equivalent Windows source installation, lint/test/build, browser acceptance and source packaging checks. |
| `security` | Configured runtime pip-audit, npm audit, Bandit and Gitleaks of the extracted public source archive. |
| `container (ubuntu-24.04)` | Compose/Portainer validation, native AMD64 packaged-context build and isolated Mock Mode container acceptance. |
| `container (ubuntu-24.04-arm)` | Equivalent native ARM64 build and isolated container acceptance. |

[Attempt 1](https://github.com/pablonietopareja/sdex-connectmap/actions/runs/38412311674/attempts/1) failed the Linux editor test: after requesting a 2x2 Production Rack, the test expected two empty slots but saw one. Windows source and security passed; dependent containers were skipped. Attempt 2 passed without a code change. The failed job log was available during this review; its retained artifact now returns 404, so the original trace could not establish which race caused that specific failure.

Earlier [run #38391343317](https://github.com/pablonietopareja/sdex-connectmap/actions/runs/38391343317) failed cable selection during an animated viewport transition. Commit [`8d8be32655e903716b080cf4d579cdf648f1a9a9`](https://github.com/pablonietopareja/sdex-connectmap/commit/8d8be32655e903716b080cf4d579cdf648f1a9a9) corrected stable SVG/viewport selection and ephemeral Docker host-port reassignment after restart; [run #38401937560](https://github.com/pablonietopareja/sdex-connectmap/actions/runs/38401937560) then passed all five jobs. [Run #38408177090](https://github.com/pablonietopareja/sdex-connectmap/actions/runs/38408177090) passed on the subsequent 1.0.0 revision. These results remain historical evidence, not verification of 1.0.1.

## Editor reliability changes

Deterministic tests reproduced two defects before their fixes: background aggregate/position updates reset an unsaved Rack draft from two rows to one, and an older topology GET replaced an already saved 2x2 Rack with its previous 1x3 snapshot. The form now resets only when persisted editable fields or the selected Rack change. Topology request generations discard superseded/aborted results; those results also cannot cancel newer refresh polling. The same regressions pass after correction.

Rack browser saves now match the exact Rack ID and resize request, verify request/response dimensions, and wait for save completion, rendered capacity and persisted API state before closing the panel. A focused regression resizes 2x2 -> 1x3 -> 1x2 -> 1x3, checks occupied/empty slots, member/source identities and reload persistence. Existing waypoint, history and read-only assertions remain.

The first local Windows editor run also exposed an attached but temporarily hidden Switch during React Flow measurement. Its trace showed `focus()` and Enter occurring before the node was visible. The test now waits for visible, stable actionability and asserts actual focus before Enter; the panel assertion remains unchanged. No fixed sleeps, larger timeouts, skipped tests or relaxed assertions were introduced to address these failures.

## Local candidate verification

These checks were executed against the changed 1.0.1 source on 14 October 2026. Windows used Windows 11 x64, Python 3.12.7 and Node 24.18.0. Linux used an isolated Ubuntu 24.04 AMD64 WSL2 environment, Python 3.12.3 and Node 22.23.3. Browser acceptance used Playwright 1.61.1/Chromium with disposable synthetic Mock Mode data.

| Check | Result | Scope |
| --- | --- | --- |
| Fresh hash-locked Python and npm installations | **PASS** | Fresh environment on each OS; dependency versions unchanged. |
| Python lint/format and complete backend tests | **PASS** | Ruff and 324 tests on Windows and Ubuntu, including 33 release metadata/packaging/link regressions and 20 image-report failure/evidence tests. The same 324 tests pass inside the final packaged Trixie runtime with read-only mounted development tools; pytest is not shipped in the runtime image. |
| Frontend lint, complete unit suite and production build | **PASS** | 153 tests on each OS; TypeScript and Vite build. |
| Visual browser acceptance | **PASS** | Three tests on Windows and three on Linux against the selected Trixie image: layout/themes/persistence, compact viewports and synthetic real-mode status presentation. |
| Repeated complete editor browser suite | **PASS** | Ten complete suites on Windows source and ten against the final packaged Trixie image on Linux: three tests per invocation, 30 passing cases per platform, no skipped/flaky/failed cases in these final runs. Every invocation starts fresh synthetic Mock Mode data. |
| Source HTTP UI, SSE, health and restart persistence | **PASS** | Disposable processes on both OSes retain settings and encryption key. |
| Synthetic 1.0.0 -> 1.0.1 upgrade | **PASS** | Source-process tests preserve decryption, schema, IDs, layout/viewport, routes/styles and Rack memberships. Cross-image acceptance also seeds actual 1.0.0 state on Bookworm/SQLite 3.40.1, then reads, saves and restarts with 1.0.1 on Trixie/SQLite 3.46.1 while preserving the key and stored relationships. No SDEX client is started. |
| Application dependency/static checks | **PASS** | pip-audit 2.10.1: no known runtime advisories; npm audit: zero advisories; Bandit 1.9.4 configured medium/high checks. |
| Gitleaks archive and Git history | **PASS** | Gitleaks 8.30.0 scans the final extracted public archive and all four local history commits with redacted output and no findings. |
| Compose and Portainer configuration | **PASS** | Docker Compose 2.40.3 validates both definitions. |
| Native Linux AMD64 Docker build and acceptance | **PASS** | All four comparisons and the final canonical build-context image pass isolated acceptance. Checks cover UI/API/health, UID 10001, read-only root, dropped capabilities, no privileges/socket/host networking, restricted mounts, loopback publication and a decryptable synthetic profile after restart. The final image also has neither pip nor ensurepip. |
| Native ARM64 1.0.1 build/acceptance | **NOT RUN** | No native ARM64 runner was available locally. Historical ARM64 baseline success does not qualify this candidate. |
| Source boundaries, versions, notices, links/anchors and assets | **PASS** | 244 public files with version/lock/license/SBOM and local-link/anchor agreement, external documentation links and unchanged static SVG/synthetic PNG assets. Application, Rack/E2E, dependency locks, MIT/notices and all 56 protected license paths retain their bytes from the preceding candidate. |
| Deterministic ZIP/TAR and member/hash checks | **PASS** | Rebuilt final source ZIP and Docker TAR match their source manifest, exclude development/review state, retain regular 0644 files and produce identical bytes on repeated Windows/Linux builds. The Docker TAR matches the exact context used for the final image. |
| Built-image advisory/license inventory | **FAIL — HIGH/CRITICAL gate** | Trivy 0.75.0 completes unsuppressed scans. Refreshed Bookworm reports 55 HIGH/CRITICAL pairs; the final packaged Trixie image reports 44 HIGH pairs across eight CVEs. Full inventory: 164 pairs, 71 unique CVEs, zero CRITICAL findings, no pip findings. |
| New remote GitHub Actions execution | **PENDING** | Requires the maintainer's future commit/push; no result is predicted. |
| Live-SDEX test of this exact candidate | **NOT RUN** | No deployed SDEX, edgeNode, production volume or real credentials were touched. |
| Third-party penetration test, industrial certification and independent legal review | **NOT RUN** | None commissioned or claimed. |

The backend runs retain an upstream Starlette/httpx deprecation warning. Windows additionally emitted an unresolved asynchronous-finalization warning: a discovery coroutine received `GeneratorExit`, then its ContextVar token reset ran in a different context. All 324 tests passed. The diagnostic test named by pytest also passed in isolation with that warning promoted to an error; the originating task has not been established. No warning suppression, application change or assertion change was made for this image review.

The 1.0.0 review separately recorded a successful Vite same-origin proxy mutation, deterministic packaging and three focused Linux waypoint regression runs. Those historical local checks were preserved as evidence rather than presented as new 1.0.1 executions. The current candidate's full checks above supersede historical test counts only for this working tree.

## Image scan findings

The original retained Bookworm scan used Trivy 0.75.0 and database update `2026-10-14T07:11:52Z`. Its 278 OS pairs plus six pip findings remain historical evidence. The comparison below refreshes all images with the same Trivy version and database update `2026-10-14T13:10:32.349175575Z`, retaining complete unsuppressed vulnerability and full-license reports. A separate `HIGH,CRITICAL` scan returns exit code `42` when findings exist; no ignore list, `--ignore-unfixed`, severity change or weaker threshold was used.

### Measured alternatives

Counts are package/advisory pairs, not independently exploitable application defects. `C/H/M/L/U` means critical/high/medium/low/unknown; size is Docker-reported bytes divided by 1,000,000.

| Runtime comparison | C/H/M/L/U | Total pairs / unique CVEs | HIGH/CRITICAL pairs / unique CVEs | Size MB | Gate |
| --- | --- | --- | --- | --- | --- |
| Bookworm baseline, Debian 12.15 | 2 / 53 / 120 / 108 / 1 | 284 / 127 | 55 / 15 | 56.47 | **FAIL** |
| Bookworm with available APT updates, Debian 12.15 | 2 / 53 / 120 / 108 / 1 | 284 / 127 | 55 / 15 | 56.47 | **FAIL** |
| Bookworm without runtime pip/ensurepip, Debian 12.15 | 2 / 53 / 115 / 107 / 1 | 278 / 121 | 55 / 15 | 56.47 | **FAIL** |
| Selected Trixie without runtime pip/ensurepip, Debian 13.7 | 0 / 44 / 58 / 61 / 1 | 164 / 71 | 44 / 8 | 52.35 | **FAIL** |

Refreshing the Bookworm tag resolved to the same index digest, and normal APT updates upgraded no packages. Removing unused pip eliminated its six fix-available findings but did not change the 55 OS HIGH/CRITICAL pairs. Trixie upgraded `liblzma5` through its normal package repositories, removed seven HIGH/CRITICAL CVEs from the report and introduced no new HIGH/CRITICAL CVE IDs. Its remaining 44 HIGH pairs have no `FixedVersion` in the captured report: 43 are `affected`, one is `fix_deferred`. All 164 remaining pairs lack a recorded fixed version. Deferred/no-dsa status does not mean patched or safe.

Base index identities:

- Bookworm builder and comparison base: `python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258`.
- Selected runtime: `python:3.12-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1`.

Both index manifests list Linux AMD64 and ARM64. That establishes available base-image targets, not native ARM64 application acceptance. The wheel builder remains on Bookworm with pip; the final stage alone changes to Trixie and removes pip/ensurepip after dependency installation. Application dependencies and source behavior are unchanged. Normal APT updates can change a future rebuilt filesystem despite a pinned base, so each distributed image needs its own identity and scan.

Immutable local comparison image IDs:

- Baseline: `sha256:e80ffeab742a46b4bc0ff7cd24f98220d744bcd9ee00e6775cfce9f1257ebb5a`.
- Updated Bookworm: `sha256:c45f9daa5d4a536bbf98498be26478b8a4f63f602c33299a5e304ae8d11e64fc`.
- Bookworm without pip: `sha256:c06a562ea42dbfd2a52600868b529da02ae3fb67b141c8dcf4f47d10b69d9007`.
- Trixie comparison: `sha256:98320b60ad6c9eb9ff9457c95a2e90074db2d2921b9b13426243cd339cc6ee9a`.

These identify the measured comparisons, not published registry images. The final native AMD64 build from the canonical 166-file Docker context has immutable image ID `sha256:d71fedd3c911724f9f17570d1297bd199580891fb4db1172192f5243f990cea5`. Its confirmation scan started at `2026-10-14T16:37:57.071104Z` with the database update shown above, and reproduces the selected row: 0 CRITICAL, 44 HIGH, 58 MEDIUM, 61 LOW and 1 UNKNOWN. Full license scanning reports 741 license rows. This exact image passes container acceptance, all 324 backend tests, three visual browser tests and ten complete editor suites. The fixed image ID applies to this local build, not every future build from the same source.

### Residual conditions and mitigations

The eight remaining HIGH CVEs fall into five source groups. Complete raw findings remain retained; the following source review and component probes are contextual risk assessment, not exploit tests or impossibility proofs.

| Group | Remaining HIGH pairs | Conditions and observed boundary |
| --- | --- | --- |
| util-linux: [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642), [78408](https://security-tracker.debian.org/tracker/CVE-2026-78408), [78409](https://security-tracker.debian.org/tracker/CVE-2026-78409), [78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | 36 across four CVEs | Restricted/privileged mount hooks or namespace/cgroup operations with attacker-controlled local state. Runtime probes confirm `nsenter --join-cgroup` is present in Trixie, so a Bookworm feature-range exclusion cannot be transferred to it. ConnectMap does not invoke mount/nsenter; tested deployment has UID 10001, zero effective capabilities, no-new-privileges, an unconfigured fstab and no host PID/cgroup mounts. Privileged operator execution changes those conditions. Vendor/upstream range differences remain documented rather than suppressed. |
| systemd: [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) | 2 | Advisory concerns systemd-homed processing attacker-controlled home records. The image includes libsystemd/libudev, while probes found no homed service and the application has no homed/D-Bus integration. Source-package matching is retained without claiming the libraries are fixed. |
| ACL: [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369) | 1 | Privileged pathname-based ACL operations through attacker-replaceable path components. No application ACL API/tool call was found; chmod of the key file is a different operation. Privileged tools or a changed deployment can reintroduce the prerequisite. |
| ncurses: [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) | 4 | Crafted terminal data processed by `infocmp`; the binary exists, but the application does not invoke it or accept terminal-file uploads. Non-root/read-only controls do not fix memory corruption if vulnerable code is executed. |
| Perl: [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) | 1 | Hostile tar entry allocation in Archive::Tar. Probes found no Archive::Tar module, and the application has no Perl/archive-upload path. The perl-base source match remains in the raw report. |

The two original CRITICAL findings are absent from the measured Trixie report. Debian records Trixie fixes for [SQLite CVE-2025-7458](https://security-tracker.debian.org/tracker/CVE-2025-7458) and [zlib CVE-2023-45853](https://security-tracker.debian.org/tracker/CVE-2023-45853); Bookworm's zlib note separately explains that vulnerable contributed MiniZip code was not built into its binary package. Image probes found no MiniZip paths, `zipOpen` symbol or pyminizip package. SQLite remains actively used, with fixed SQL and bound values; hostile database restoration or future arbitrary-SQL/FTS features would change exposure. No malicious parser input was executed.

CA bundles, SSL context creation, cryptography and Fernet round-trip probes pass for the compared runtime. Cross-image upgrade acceptance preserves real baseline-module synthetic state from Bookworm/SQLite 3.40.1 to Trixie/SQLite 3.46.1, including the generated key and later writes across restart. These are compatibility checks, not live SDEX or independent security qualification.

### Reporting and release policy

`scripts/image_security_report.py` binds full and HIGH/CRITICAL reports to the same immutable local image ID and unchanged database metadata. It rejects inconsistent or incomplete evidence and preserves complete findings. The container CI jobs use checksum-verified Trivy 0.75.0 on both native architectures and retain reports from runner temporary storage as 14-day workflow artifacts. Findings are informational by default; execution/evidence errors fail the job. The HIGH/CRITICAL gate remains explicitly **FAIL** even if the surrounding CI job succeeds. Optional `--enforce-high-critical` returns `42` for findings and does not filter them.

License scanning inventories OS, Python and retained loose-file notices, including unknown classifications. It is not an independent legal clearance of every binary or every embedded native library. The application inventories retain all 21 locked Python distributions and 28 non-development npm entries; upstream text and MIT terms remain unchanged. Complete machine-readable local review reports are excluded from source archives and Git.

## Distribution, field experience and boundaries

The public source includes application code, contributor tests, packaging/acceptance scripts, deployment examples, static SVG assets, refreshed synthetic screenshots and public documentation. Maintainer-specific `docs/PUBLISHING.md` was removed. Databases, secrets, environments, installed dependencies, caches, logs/traces and generated archives are excluded from Git and source packages. The build-context TAR is source input for Docker, not a `docker load` image archive.

The maintainer reports successful container operation on Raspberry Pi and edgeNode with connectivity and functionality against a real SDEX API. This is successful **maintainer-reported field validation**, separate from automated Mock Mode tests, and does not establish exact-candidate live integration, independent certification or compatibility with every firmware/network/API configuration.

ConnectMap preserves read-only SDEX discovery; its upstream POSTs are limited to authentication login/session refresh/logout. Visual changes write only local SQLite. The web application has no login/RBAC; any reachable client can read topology and change its local configuration. Default publication is loopback. Use trusted access, an authenticated HTTPS proxy/VPN and outbound segmentation. Origin guards are not authentication, and configured destinations have no application allowlist.

TLS verification remains enabled by default. Saved passwords alone are Fernet-encrypted; the database, topology, addresses, username and visual state are otherwise plaintext. Keep the volume and matching key together and protect backups. One process per volume is required. Healthchecks describe local service health; animations and topology are not physical-network measurements.

The [MIT license](LICENSE), [third-party notices](THIRD_PARTY_NOTICES.md), [upstream licenses](docs/licenses/README.md) and [licensing guidance](docs/LICENSING.md) remain part of the distribution. Original-code/assets redistribution is maintainer-declared; trademark rights and dependency terms remain with their owners. No employer-rights or independent legal certification is claimed.

## Release conclusion

**Source candidate commit: GO. Formal public 1.0.1 GitHub Release: HOLD.** The measured runtime change reduces reported exposure while retaining tested application and persistence behavior. The remaining HIGH/CRITICAL gate is **FAIL**; contextual mitigation is not a passing scan or automatic shipping approval.

Formal release requires explicit acceptance of the residual image risk and all five GitHub Actions jobs passing on the new candidate commit, including native ARM64 acceptance. The audit must then identify that exact commit/run, and CI must pass again on the finalized audit revision before an annotated `v1.0.1` tag and GitHub Release. None of those future remote results or publication steps is assumed complete. The image must not be described as vulnerability-free, independently certified or universally compatible.
