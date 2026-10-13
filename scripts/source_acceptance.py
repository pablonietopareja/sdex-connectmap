"""Check compiled UI, SSE and restart persistence using disposable Mock Mode."""

from __future__ import annotations

import hashlib
import http.client
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from container_acceptance import request


class DisposableDirectory(TemporaryDirectory):
    """Retry transient Windows file locks after the isolated server exits."""

    def cleanup(self) -> None:
        for attempt in range(10):
            try:
                super().cleanup()
                return
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.25)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / "frontend/dist/index.html").is_file():
        raise RuntimeError("Build the frontend with npm run build first")
    with DisposableDirectory(prefix="connectmap-source-acceptance-") as directory:
        storage = Path(directory)
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("SDEX_", "CONNECTMAP_")) and key != "PYTHONPATH"
        }
        environment.update(
            CONNECTMAP_MOCK_MODE="true",
            CONNECTMAP_MOCK_SCENARIO="stable",
            CONNECTMAP_DATA_DIR=str(storage),
            CONNECTMAP_STATIC_DIR=str(root / "frontend/dist"),
            CONNECTMAP_DISABLE_DOCS="true",
            CONNECTMAP_LOG_LEVEL="ERROR",
            PYTHONDONTWRITEBYTECODE="1",
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        def start():
            log = (storage / "server.log").open("ab")
            # Only the current Python interpreter and this checkout are executed.
            process = subprocess.Popen(  # noqa: S603
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--no-access-log",
                ],
                cwd=root / "backend",
                env=environment,
                stdout=log,
                stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Mock Mode server exited before startup")
                    try:
                        topology = request(port, "/api/topology")
                        if topology.get("nodes"):
                            return process, log, topology
                    except (OSError, http.client.HTTPException):
                        pass
                    time.sleep(0.1)
                raise RuntimeError("Mock Mode server did not become ready")
            except BaseException:
                process.terminate()
                process.wait(timeout=10)
                log.close()
                raise

        process, log, topology = start()
        try:
            assert topology["mock_mode"] is True and len(topology["nodes"]) >= 8
            assert request(port, "/api/config/status")["source"] == "mock"
            assert request(port, "/api/health")["database"] == "ok"
            assert "SDEX ConnectMap" in request(port, "/", text=True)
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                connection.request("GET", "/api/events")
                response = connection.getresponse()
                assert response.status == 200
                assert response.getheader("Content-Type").startswith("text/event-stream")
                assert response.readline().decode().strip() == "event: topology"
                assert '"type":"connected"' in response.readline().decode()
            finally:
                connection.close()
            saved = request(port, "/api/settings", {"refresh_interval_seconds": 600})
            assert saved["refresh_interval_seconds"] == 600
            key_hash = hashlib.sha256((storage / ".connectmap-key").read_bytes()).hexdigest()
        finally:
            process.terminate()
            process.wait(timeout=10)
            log.close()
        process, log, _ = start()
        try:
            assert request(port, "/api/settings")["refresh_interval_seconds"] == 600
            assert (
                key_hash == hashlib.sha256((storage / ".connectmap-key").read_bytes()).hexdigest()
            )
        finally:
            process.terminate()
            process.wait(timeout=10)
            log.close()
        print("PASS: compiled HTTP UI, Mock Mode, health, SSE, restart settings and key retention.")


if __name__ == "__main__":
    main()
