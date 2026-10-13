"""Check public source boundaries, local documentation links and build inputs."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    ".dockerignore",
    ".env.example",
    ".gitattributes",
    ".gitignore",
    ".gitleaks.toml",
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "RELEASE_AUDIT.md",
    "THIRD_PARTY_NOTICES.md",
    "LICENSE",
    "VERSION",
    "Dockerfile",
    "compose.yaml",
    "portainer-stack.yml",
}
SOURCE_DIRS = {"backend", "frontend", "icons", "imgs", "docs", "scripts", ".github"}
IGNORED_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "artifacts",
    "test-results",
    "test-artifacts",
    "playwright-report",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "coverage",
}
SENSITIVE_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pem", ".crt", ".key", ".log"}
TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".json",
    ".md",
    ".yml",
    ".yaml",
    ".txt",
    ".in",
    ".svg",
}


def source_files(root: Path = ROOT) -> list[Path]:
    result = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED_DIRS for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"Symlinks are not allowed: {relative.as_posix()}")
        if not path.is_file() or path.name.endswith((".pyc", ".pyo", ".tsbuildinfo")):
            continue
        if len(relative.parts) == 1 and path.name not in ROOT_FILES:
            raise ValueError(f"Unexpected repository-root file: {path.name}")
        if len(relative.parts) > 1 and relative.parts[0] not in SOURCE_DIRS:
            raise ValueError(f"Unexpected source directory: {relative.parts[0]}")
        if (
            path.suffix.lower() in SENSITIVE_SUFFIXES
            or (path.name.startswith(".env") and path.name != ".env.example")
            or path.name == ".connectmap-key"
        ):
            raise ValueError(
                f"Private deployment state is not a source asset: {relative.as_posix()}"
            )
        result.append(path)
    return result


def verify(root: Path = ROOT) -> list[Path]:
    files = source_files(root)
    required = ROOT_FILES - {".gitleaks.toml"}
    missing = sorted(name for name in required if not (root / name).is_file())
    required_inputs = (
        "backend/app/main.py",
        "backend/requirements.txt",
        "backend/requirements-dev.txt",
        "backend/requirements.in",
        "backend/requirements-dev.in",
        "frontend/package-lock.json",
        "frontend/package.json",
        "frontend/src/main.tsx",
        ".github/workflows/ci.yml",
    )
    missing += [name for name in required_inputs if not (root / name).is_file()]
    if missing:
        raise ValueError("Missing source/build inputs: " + ", ".join(missing))
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    package = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))
    if package["version"] != version:
        raise ValueError("Frontend version differs from VERSION")
    for path in files:
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8-sig")
        if re.search(r"[A-Za-z]:[\\/]Users[\\/]", text, re.I):
            raise ValueError(f"Machine-specific home path in {path.relative_to(root)}")
        if path.suffix == ".md":
            for target in re.findall(r"!?\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)", text):
                if target.startswith(("https://", "http://", "mailto:", "#")):
                    continue
                target = unquote(target.split("#", 1)[0].strip("<>"))
                resolved = (path.parent / target).resolve()
                if not resolved.is_relative_to(root.resolve()) or not resolved.exists():
                    raise ValueError(
                        f"Broken or external local link in {path.relative_to(root)}: {target}"
                    )
        if path.suffix == ".svg" and re.search(
            r"<script\b|<foreignObject\b|\bon\w+\s*=|(?:href|xlink:href)=[\"'](?:https?:|data:)",
            text,
            re.I,
        ):
            raise ValueError(f"Active/external SVG content in {path.relative_to(root)}")
    print(f"PASS: {len(files)} public source files; inputs, boundaries and local links verified.")
    return files


if __name__ == "__main__":
    try:
        verify()
    except (OSError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
