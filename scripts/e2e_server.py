"""Serve the real application with disposable, strictly synthetic test state."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--scenario", choices=("visual_preview", "editor_preview"), required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    static = root / "frontend" / "dist"
    if not (static / "index.html").is_file():
        parser.error("Build the frontend with npm run build before starting browser tests.")
    # Inherited deployment settings must never select a real SDEX server.
    for name in tuple(os.environ):
        if name.startswith(("SDEX_", "CONNECTMAP_")):
            del os.environ[name]
    with TemporaryDirectory(prefix="connectmap-browser-") as data_dir:
        os.environ.update(
            CONNECTMAP_HOST="127.0.0.1",
            CONNECTMAP_PORT=str(args.port),
            CONNECTMAP_DATA_DIR=data_dir,
            CONNECTMAP_STATIC_DIR=str(static),
            CONNECTMAP_MOCK_MODE="true",
            CONNECTMAP_MOCK_SCENARIO=args.scenario,
            CONNECTMAP_DISABLE_DOCS="true",
            CONNECTMAP_LOG_LEVEL="WARNING",
        )
        sys.path.insert(0, str(root / "backend"))
        import uvicorn

        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
