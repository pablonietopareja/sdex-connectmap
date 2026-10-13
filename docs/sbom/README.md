# Runtime dependency inventories

- [Python CycloneDX inventory](python-runtime.cdx.json): generated with pip-audit 2.10.1 from the complete hash-locked `backend/requirements.txt` on 13 October 2026. Includes 21 resolved distributions; excludes development tools and embedded native-library internals.
- [Frontend CycloneDX inventory](frontend-runtime.cdx.json): generated with npm 11.16.0 using `npm sbom --omit=dev --sbom-format=cyclonedx`. Describes 20 components in npm's runtime graph, including type-only entries that may not appear in the compiled JavaScript. The license inventory separately covers all 28 non-development lock entries.

These inventories describe application dependencies, not a built container. They exclude the operating-system packages, Python interpreter, image build tools and downloaded test browser. Regenerate them when changing lockfiles. The retained [license files](../licenses/README.md) and [release audit](../../RELEASE_AUDIT.md) record attribution and verification separately.
