# Third-party notices

SDEX ConnectMap includes or depends on the following upstream software. Each component retains its own copyright and license. The project's MIT license does not replace these terms.

This inventory reflects the hash-locked Python runtime requirements and the non-development npm lock entries for version 1.0.0. It excludes development tools, browser binaries and operating-system packages in the container base image.

## Python runtime

| Component | Version | Upstream license | Retained notices |
| --- | --- | --- | --- |
| annotated-doc | 0.0.5 | MIT | [Files](docs/licenses/python/annotated-doc/licenses/LICENSE) |
| annotated-types | 0.8.0 | MIT | [Files](docs/licenses/python/annotated-types/licenses/LICENSE) |
| AnyIO | 4.14.2 | MIT | [Files](docs/licenses/python/anyio/licenses/LICENSE) |
| certifi | 2026.7.22 | MPL-2.0 | [Files](docs/licenses/python/certifi/licenses/LICENSE) |
| CFFI | 2.1.0 | MIT-0 | [Files](docs/licenses/python/cffi/licenses/LICENSE) |
| Click | 8.4.2 | BSD-3-Clause | [Files](docs/licenses/python/click/licenses/LICENSE.txt) |
| Colorama | 0.4.6 | BSD-3-Clause | [Files](docs/licenses/python/colorama/licenses/LICENSE.txt) |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | [Files](docs/licenses/python/cryptography/licenses/LICENSE) |
| FastAPI | 0.143.0 | MIT | [Files](docs/licenses/python/fastapi/licenses/LICENSE) |
| h11 | 0.16.0 | MIT | [Files](docs/licenses/python/h11/licenses/LICENSE.txt) |
| HTTPcore | 1.0.9 | BSD-3-Clause | [Files](docs/licenses/python/httpcore/licenses/LICENSE.md) |
| HTTPX | 0.28.1 | BSD-3-Clause | [Files](docs/licenses/python/httpx/licenses/LICENSE.md) |
| idna | 3.18 | BSD-3-Clause | [Files](docs/licenses/python/idna/licenses/LICENSE.md) |
| OpenTelemetry API | 1.45.1 | Apache-2.0 | [Files](docs/licenses/python/opentelemetry-api/licenses/LICENSE) |
| pycparser | 3.0 | BSD-3-Clause | [Files](docs/licenses/python/pycparser/licenses/LICENSE) |
| Pydantic | 2.11.5 | MIT | [Files](docs/licenses/python/pydantic/licenses/LICENSE) |
| pydantic-core | 2.33.2 | MIT | [Files](docs/licenses/python/pydantic-core/licenses/LICENSE) |
| Starlette | 1.3.1 | BSD-3-Clause | [Files](docs/licenses/python/starlette/licenses/LICENSE.md) |
| typing_extensions | 4.16.0 | PSF-2.0 | [Files](docs/licenses/python/typing-extensions/licenses/LICENSE) |
| typing-inspection | 0.4.2 | MIT | [Files](docs/licenses/python/typing-inspection/licenses/LICENSE) |
| Uvicorn | 0.34.3 | BSD-3-Clause | [Files](docs/licenses/python/uvicorn/licenses/LICENSE.md) |

The [machine-readable inventory](docs/licenses/python-runtime.json) records versions, declared metadata and retained file paths. Copyright statements are preserved in the upstream license files rather than replaced with the application's copyright.

certifi's Mozilla-derived certificate data retains its MPL notice and upstream source references. Its exact package source is available from [PyPI](https://pypi.org/project/certifi/2026.7.22/). ConnectMap does not modify those files.

## Browser UI

| Component | Version | Upstream license |
| --- | --- | --- |
| React and React DOM | 18.3.1 | MIT |
| React Flow (`@xyflow/react`) | 12.8.5 | MIT |
| `@xyflow/system` | 0.0.69 | MIT |
| Zustand | 4.5.7 | MIT |
| `classcat` | 5.0.5 | MIT |
| `use-sync-external-store` | 1.6.0 | MIT |
| React scheduler | 0.23.2 | MIT |
| `d3-color`, `d3-dispatch`, `d3-drag`, `d3-interpolate`, `d3-selection`, `d3-timer`, `d3-transition`, `d3-zoom` | Resolved in npm inventory | ISC |
| `d3-ease` | 3.0.1 | BSD-3-Clause |
| `js-tokens`, `loose-envify`, `csstype` and installed type definitions | Resolved in npm inventory | MIT |

The [npm inventory](docs/licenses/npm-runtime.json) gives every resolved non-development entry and exact version. [Upstream npm notices](docs/licenses/npm) are retained for those entries, including type-only packages that need not appear in the compiled JavaScript.

## Scope of these notices

The notices are copied from the installed upstream distributions corresponding to the lockfiles. They are included with source packaging and the Docker runtime. This inventory does not claim to be a complete SBOM of a built container; native wheel internals, the Python interpreter, OpenSSL and operating-system packages have additional upstream terms.

See [Licensing](docs/LICENSING.md) for application licensing, product-name use and redistribution guidance.
