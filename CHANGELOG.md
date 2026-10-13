# Changelog

## Unreleased

- Synchronize editor browser tests with animated viewport/path geometry and cover selection of a persisted waypoint without route changes.
- Preserve separate visual/editor failure traces in CI while retaining native container job prerequisites.
- Re-read the disposable container's loopback host port after restart to support Docker's ephemeral-port reassignment.

## 1.0.0 — 2026-10-13

Initial public source release of SDEX ConnectMap.

- Read-only SDEX discovery with protocol-specific normalization, shared polling and Server-Sent Events.
- Interactive topology with saved positions, connection details, interface assignment and active alarms.
- Local Rack/Switch editing, cable routing and appearance controls.
- Offline synthetic Mock Mode for demonstrations and regression tests.
- SQLite persistence and Fernet-encrypted saved passwords.
- Standalone Docker/Compose and Portainer deployment files with a non-root runtime and persistent data volume.
- Locked dependencies, synthetic backend/frontend/browser tests, CI verification and source packaging tools.
- Deployment, configuration, security, licensing and manual publishing documentation.

The [release audit](RELEASE_AUDIT.md) records the exact checks and qualification limits for this version. There is no earlier public release history in this repository.
