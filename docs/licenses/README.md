# Upstream runtime license files

These files preserve the notices supplied by the installed dependencies corresponding to the release lockfiles.

- [Python inventory](python-runtime.json): distributions in `backend/requirements.txt`, including platform-conditional runtime entries installed for this review.
- [npm inventory](npm-runtime.json): entries not marked development-only in `frontend/package-lock.json`, including type-only dependencies.
- `python/`: upstream wheel license files and their original names.
- `npm/`: upstream package license/notice files; scoped package directory names replace `/` with `__`.

Keep the upstream text unchanged. Regenerate inventories and retained files from a clean locked installation when dependencies change; compare the versions with the manifests before committing. The container includes these notices, and installed Python distribution metadata remains available separately.

The inventories do not include development-only dependencies, downloaded Chromium binaries or the operating-system packages of a built image. Read [Third-party notices](../../THIRD_PARTY_NOTICES.md) and [Licensing](../LICENSING.md) for the distribution scope.
