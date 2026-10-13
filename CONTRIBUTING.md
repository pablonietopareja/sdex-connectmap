# Contributing

I welcome focused bug reports and changes that make SDEX ConnectMap easier to deploy, understand and maintain on small edge hosts. Preserve the read-only SDEX boundary and keep unknown or missing information explicit.

## Setup and checks

Use Python 3.12 and Node.js 22. Follow [Development](docs/DEVELOPMENT.md) for the virtual environment, locked installation, local demo and browser dependencies.

Before opening a pull request, run the relevant backend tests, frontend lint/tests/build and `python scripts/verify_release.py`. Run browser tests for canvas, form or editor changes. Run isolated container acceptance when changing dependencies, storage, Docker or deployment behavior.

## Changes and test data

- Keep changes small enough to review. Explain the observed problem and resulting behavior.
- Add regression coverage for behavior fixes, using synthetic SDEX responses and temporary data directories.
- Never depend on a real gateway, private endpoint, plant topology or production credential in tests.
- Treat Rack, Switch, layout and cable changes as local presentation data. Do not add writes to SDEX without an explicit project-level design change.
- Preserve keyboard access, visible status text and reduced-motion behavior in UI changes.
- Keep source comments and public documentation in English.

## Dependencies and notices

Python direct requirements are declared in `backend/requirements.in` and `backend/requirements-dev.in`; the corresponding `.txt` files hold resolved versions and hashes. Update the declaration and lock together. npm dependencies are locked in `frontend/package-lock.json`.

Review advisories, upstream licenses and bundled notices when adding or updating a package. Preserve required notices in [docs/licenses](docs/licenses) and update [Third-party notices](THIRD_PARTY_NOTICES.md). Avoid runtime CDN dependencies and private registries.

## Pull requests and reports

A useful bug report identifies the version, deployment method, synthetic reproduction, expected behavior and observed behavior. Remove addresses, device names, usernames, passwords and customer data from logs before sharing them.

A pull request should describe why the change is needed, the checks actually run and any migration or deployment implications. Contributions must be original or redistributable under terms compatible with this project's MIT license. Report vulnerabilities through the private process in [Security](SECURITY.md).
