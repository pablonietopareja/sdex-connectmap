# Changelog

## 1.0.1 — Unreleased

- Preserve unsaved Rack dimensions when background topology updates change only aggregate status or position.
- Ignore superseded topology GET responses so an older snapshot cannot replace a completed visual edit or clear newer refresh state.
- Match editor resize tests to the exact Rack request and response, wait for completed saves and rendered/persisted dimensions, and cover consecutive resizes with occupancy and reload checks.
- Wait for a newly measured Switch to become visible and focused before the browser test sends its keyboard action.
- Use consistent SDEX ConnectMap branding in the page title, header and onboarding while retaining legal author attribution.
- Distinguish synthetic Mock Mode status from real SDEX connectivity, including stale demo data. Status calculations and alarms are unchanged.
- Update project versions, deployment image tags and source artifact names to 1.0.1.
- Complete the frontend runtime SBOM with all 28 locked non-development entries and reproducible dependency/license references, without changing the dependency graph.
- Make source archive ordering, ZIP host metadata and generated text identical on Windows and Linux.
- Add separate-process upgrade acceptance for synthetic 1.0.0 SQLite data, encrypted profiles, saved visual state and retained encryption keys.
- Refresh the public documentation and synthetic UI screenshots; remove maintainer-specific repository publishing instructions.
- Separate historical 1.0.0 CI and field experience from the current candidate's verification record.
- Use a digest-pinned Debian Trixie Python 3.12 runtime with available OS updates after comparing native AMD64 images and compatibility; retain the Bookworm wheel builder.
- Remove unused `pip` and `ensurepip` from the runtime after installing the unchanged application dependencies.
- Add an unsuppressed Trivy vulnerability/license report to both native container CI jobs. Findings remain informational; scanner execution and evidence-consistency errors fail the job.
- Record the baseline and measured alternatives separately: the selected comparison removes the two CRITICAL and six pip findings, while its HIGH/CRITICAL gate still fails with 44 HIGH package/advisory pairs across eight CVEs.

The [release audit](RELEASE_AUDIT.md) records executed checks and pending qualification. Remote CI for the changed 1.0.1 candidate is pending. A formal release remains on HOLD until residual image risk is explicitly accepted and the final revision passes CI; no GitHub tag or formal Release is assumed to exist.

## 1.0.0 — 2026-10-13

Initial public source release of SDEX ConnectMap.

- Read-only SDEX discovery with protocol-specific normalization, shared polling and Server-Sent Events.
- Interactive topology with saved positions, connection details, interface assignment and active alarms.
- Local Rack/Switch editing, cable routing, waypoint controls and appearance options.
- Offline synthetic Mock Mode for demonstrations and regression testing.
- SQLite persistence and Fernet-encrypted saved SDEX passwords.
- Standalone Docker/Compose and Portainer deployment definitions with a non-root runtime and persistent data volume.
- Locked Python and npm dependencies, backend/frontend/browser tests, CI verification and source packaging tools.
- Deployment, architecture, configuration, security and licensing documentation.

### Release verification and test reliability

- Synchronize browser tests with animated viewport and SVG path geometry; verify that selecting an existing cable reveals saved waypoints without changing its route.
- Keep visual and editor browser failure traces separate in CI.
- Re-read the Docker test container's temporary loopback host port after restart to accommodate ephemeral-port reassignment without weakening network isolation.
- Linux/Windows source checks, configured security checks and native AMD64/ARM64 container acceptance passed in [GitHub Actions run #38408177090](https://github.com/pablonietopareja/sdex-connectmap/actions/runs/38408177090) for an earlier 1.0.0 commit.

These test-harness corrections were committed after the initial source publication and did not change the application's SDEX runtime behavior. At the 14 October 2026 baseline audit, version 1.0.0 had been published as source on `main`; no repository tag or formal GitHub Release existed.

The later baseline commit `90f89c0d91c57475dd9a893530b167481a07b1f0` passed [run #38412311674, attempt 2](https://github.com/pablonietopareja/sdex-connectmap/actions/runs/38412311674/attempts/2). Attempt 1 failed the Linux editor test after changing Rack dimensions; the rerun passed without a source change. That intermittent failure remains part of the baseline evidence and is not erased by the successful rerun.

There is no earlier public release history in this repository.
