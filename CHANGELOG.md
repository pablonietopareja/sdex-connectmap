# Changelog

## 1.0.0 — 2026-10-13

Initial public source release of SDEX ConnectMap.

- Read-only SDEX discovery with protocol-specific normalization, shared polling and Server-Sent Events.
- Interactive topology with saved positions, connection details, interface assignment and active alarms.
- Local Rack/Switch editing, cable routing, waypoint controls and appearance options.
- Offline synthetic Mock Mode for demonstrations and regression testing.
- SQLite persistence and Fernet-encrypted saved SDEX passwords.
- Standalone Docker/Compose and Portainer deployment definitions with a non-root runtime and persistent data volume.
- Locked Python and npm dependencies, backend/frontend/browser tests, CI verification and source packaging tools.
- Deployment, architecture, configuration, security, licensing and manual publishing documentation.

### Release verification and test reliability

- Synchronize browser tests with animated viewport and SVG path geometry; verify that selecting an existing cable reveals saved waypoints without changing its route.
- Keep visual and editor browser failure traces separate in CI.
- Re-read the Docker test container's temporary loopback host port after restart to accommodate ephemeral-port reassignment without weakening network isolation.
- Confirm Linux/Windows source checks, configured security checks and native AMD64/ARM64 container acceptance in [GitHub Actions run #38408177090](https://github.com/pablonietopareja/sdex-connectmap/actions/runs/38408177090).

These test-harness corrections were committed after the initial source publication and before a formal `v1.0.0` tag or GitHub Release. They did not change the application's SDEX runtime behavior.

The [release audit](RELEASE_AUDIT.md) records the validated commit, checks performed and remaining qualification boundaries. There is no earlier public release history in this repository.
