# Runtime dependency inventories

- [Python CycloneDX inventory](python-runtime.cdx.json): generated with pip-audit 2.10.1 from the complete hash-locked `backend/requirements.txt` on 13 October 2026. Includes 21 resolved distributions; excludes development tools and embedded native-library internals.
- [Frontend CycloneDX inventory](frontend-runtime.cdx.json): generated deterministically by `scripts/build_frontend_sbom.py` from `frontend/package-lock.json` and the retained upstream license inventory. Includes all 28 non-development lock entries, their licenses, and dependency/peer references. Type-only entries need not appear in the compiled JavaScript.

The runtime dependency graph is unchanged for the 1.0.1 candidate. The frontend inventory corrects eight missing entries in the previous record and updates application metadata to version 1.0.1; dependency versions and retained upstream notices are unchanged.

Regenerate the frontend inventory from the repository root after updating runtime locks and upstream notices:

```sh
python scripts/build_frontend_sbom.py
python scripts/verify_release.py
```

These inventories describe application dependencies, not a built container. They exclude the operating-system packages, Python interpreter, image build tools and downloaded test browser. Regenerate them when changing lockfiles. The retained [license files](../licenses/README.md) and [release audit](../../RELEASE_AUDIT.md) record attribution and verification separately.
