# Licensing

I publish SDEX ConnectMap under the [MIT License](../LICENSE), copyright 2026 Pablo Nieto Pareja. The license covers the original application source, documentation and project assets. Dependencies retain their own licenses and copyright notices; they are not relicensed by this repository's MIT file.

## Integration and product names

SDEX ConnectMap is an independent application using SDEX's publicly available API. This repository does not distribute SDEX software, edgeNode firmware, a proprietary SDK or confidential API documentation. The API references in [Architecture](ARCHITECTURE.md) link to the public upstream documentation.

SDEX, edgeNode, Softing and other product names identify the systems with which the application works. Their respective owners retain trademark rights. The application does not imply official endorsement, certification or inclusion with a Softing product.

## Third-party components

[Third-party notices](../THIRD_PARTY_NOTICES.md) lists the resolved runtime dependencies and license families. The upstream license files retained under [licenses](licenses) are part of the distribution and must remain available when distributing source or built images.

Most runtime packages use MIT, ISC, BSD or Apache terms. Two details deserve separate attention:

- **certifi:** the package includes Mozilla-derived certificate data under MPL-2.0. Retain its notice and the applicable source-availability information. The exact upstream distribution is available from [certifi 2026.7.22 on PyPI](https://pypi.org/project/certifi/2026.7.22/); the retained license file identifies Mozilla's original certificate-data source. ConnectMap does not modify certifi's files.
- **cryptography:** upstream offers Apache-2.0 or BSD-3-Clause terms. Both upstream license files are retained. Binary wheels may include additional embedded components governed by their upstream distribution terms; preserve the installed wheel metadata and notices when distributing an image.

The Python runtime retains dependency distribution metadata in the image. The compiled browser UI includes npm code, so its upstream notices are also retained with the application. Development-only tools and downloaded browser binaries are not shipped as application source or as runtime tooling.

## Distribution changes

Keep `LICENSE`, `THIRD_PARTY_NOTICES.md` and the relevant upstream license files when redistributing. If changing dependencies, regenerate their version/license inventory from the new lockfiles and installed distributions, review new obligations and update the notices before publishing.

The runtime inventory does not describe every OS package in the base image or every development tool. A complete binary-distribution review must also account for the chosen base image, compiled native libraries and any additional files introduced by the distributor. The [release audit](../RELEASE_AUDIT.md) records the checks actually completed.
