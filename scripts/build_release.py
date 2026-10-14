"""Build deterministic source ZIP and Docker build-context TAR, then verify them."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path

from verify_release import ROOT, verify


def docker_input(path: Path) -> bool:
    name = path.relative_to(ROOT).as_posix()
    if name in {
        "Dockerfile",
        ".dockerignore",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "backend/requirements.txt",
    }:
        return True
    if name.startswith(("backend/app/", "icons/", "docs/licenses/")):
        return True
    if name.startswith("frontend/src/"):
        return "/test/" not in name and ".test." not in name
    return name in {
        "frontend/package.json",
        "frontend/package-lock.json",
        "frontend/index.html",
        "frontend/vite.config.ts",
        "frontend/icon-assets-plugin.ts",
        "frontend/tsconfig.json",
        "frontend/tsconfig.app.json",
        "frontend/tsconfig.node.json",
    }


def main() -> None:
    files = verify()
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    prefix = f"sdex-connectmap-{version}"
    source = destination / f"{prefix}-source.zip"
    context = destination / f"{prefix}-build-context.tar"
    source_contents = {path.relative_to(ROOT).as_posix(): path.read_bytes() for path in files}
    context_contents = {
        name: data for name, data in source_contents.items() if docker_input(ROOT / name)
    }
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in source_contents.items():
            entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.create_system = 3  # Stable UNIX file metadata on Windows and Linux.
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    with tarfile.open(context, "w", format=tarfile.PAX_FORMAT) as archive:
        for name, data in context_contents.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            entry.mode = 0o644
            entry.mtime = 0
            archive.addfile(entry, io.BytesIO(data))
    with zipfile.ZipFile(source) as archive:
        assert set(archive.namelist()) == set(source_contents)
        assert all(archive.read(name) == data for name, data in source_contents.items())
        assert archive.testzip() is None
    with tarfile.open(context) as archive:
        assert set(archive.getnames()) == set(context_contents)
        assert all(
            archive.extractfile(name).read() == data for name, data in context_contents.items()
        )
    checksums = []
    for artifact in (source, context):
        checksums.append(f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact.name}")
        print(f"PASS: {artifact.name} ({artifact.stat().st_size} bytes)")
    (destination / "SHA256SUMS").write_text(
        "\n".join(checksums) + "\n", encoding="utf-8", newline="\n"
    )
    inventory = {name: hashlib.sha256(data).hexdigest() for name, data in source_contents.items()}
    (destination / "source-manifest.json").write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
