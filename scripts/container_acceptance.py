"""Exercise one disposable Docker container and volume using only Mock Mode."""

from __future__ import annotations

import argparse
import http.client
import json
import shutil
import subprocess
import time
from uuid import uuid4


def docker(*args: str, check: bool = True) -> str:
    executable = shutil.which("docker")
    if executable is None:
        raise RuntimeError("Docker CLI is required for container acceptance")
    # The local CLI receives an argv list; no shell or external command text is used.
    result = subprocess.run(  # noqa: S603
        [executable, *args], text=True, capture_output=True, check=check
    )
    return result.stdout.strip()


def published_port(name: str) -> int:
    binding = json.loads(docker("inspect", name))[0]["NetworkSettings"]["Ports"]["8080/tcp"][0]
    assert binding["HostIp"] == "127.0.0.1"
    return int(binding["HostPort"])


def request(port: int, path: str, payload: dict | None = None, *, text: bool = False):
    body = json.dumps(payload).encode() if payload is not None else None
    origin = f"http://127.0.0.1:{port}"
    headers = {"Content-Type": "application/json", "Origin": origin} if body else {}
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("PUT" if body else "GET", path, body=body, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f"Unexpected HTTP {response.status} for {path}")
        data = response.read().decode()
        return data if text else json.loads(data)
    finally:
        connection.close()


def wait_ready(name: str, port: int) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            health = request(port, "/api/health")
            if health["database"] == "ok" and health["scheduler"] == "running":
                if docker("inspect", "--format", "{{.State.Health.Status}}", name) == "healthy":
                    return
        except (OSError, KeyError, http.client.HTTPException):
            pass
        time.sleep(1)
    raise RuntimeError("Disposable container did not become healthy")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="sdex-connectmap:1.0.0")
    args = parser.parse_args()
    name = "connectmap-acceptance-" + uuid4().hex[:12]
    volume = name + "-data"
    docker("volume", "create", volume)
    try:
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",  # noqa: S108 - container-only tmpfs mount
            "-p",
            "127.0.0.1::8080",
            "-v",
            volume + ":/data",
            "-e",
            "CONNECTMAP_MOCK_MODE=true",
            "-e",
            "CONNECTMAP_MOCK_SCENARIO=stable",
            args.image,
        )
        port = published_port(name)
        wait_ready(name, port)
        assert docker("exec", name, "id", "-u") == "10001"
        assert request(port, "/api/config/status")["mock_mode"] is True
        topology = request(port, "/api/topology")
        assert topology["nodes"] and topology["mock_mode"] is True
        assert "SDEX" in request(port, "/", text=True)
        request(port, "/api/settings", {"refresh_interval_seconds": 600})
        key_hash = docker(
            "exec",
            name,
            "python",
            "-c",
            "import hashlib; "
            "print(hashlib.sha256(open('/data/.connectmap-key','rb').read()).hexdigest())",
        )
        docker("restart", name)
        # Docker may allocate a different ephemeral host port when the container restarts.
        port = published_port(name)
        wait_ready(name, port)
        assert request(port, "/api/settings")["refresh_interval_seconds"] == 600
        assert key_hash == docker(
            "exec",
            name,
            "python",
            "-c",
            "import hashlib; "
            "print(hashlib.sha256(open('/data/.connectmap-key','rb').read()).hexdigest())",
        )
        print(
            "PASS: Mock Mode, HTTP UI, healthcheck, UID10001, restart settings and key persistence."
        )
    finally:
        docker("rm", "-f", name, check=False)
        docker("volume", "rm", volume)


if __name__ == "__main__":
    main()
