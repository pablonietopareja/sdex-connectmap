"""Check public source boundaries, local documentation links and build inputs."""

from __future__ import annotations

import json
import re
import sys
import unicodedata
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
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
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


def verify_versions(root: Path) -> str:
    """Check project metadata without treating dependency or history versions as releases."""
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("VERSION must contain a semantic release version")
    for name in ("frontend/package.json", "frontend/package-lock.json"):
        package = json.loads((root / name).read_text(encoding="utf-8"))
        if package.get("version") != version:
            raise ValueError(f"Project version differs from VERSION in {name}")
        if name.endswith("package-lock.json") and package["packages"][""].get("version") != version:
            raise ValueError("Frontend lock root version differs from VERSION")
    patterns = {
        "backend/app/__init__.py": r'__version__\s*=\s*"([^\"]+)"',
        "Dockerfile": r'org\.opencontainers\.image\.version="([^\"]+)"',
        "compose.yaml": r"CONNECTMAP_IMAGE:-sdex-connectmap:([^}]+)",
        "portainer-stack.yml": r"CONNECTMAP_IMAGE:-sdex-connectmap:([^}]+)",
        ".env.example": r"^CONNECTMAP_IMAGE=sdex-connectmap:([^\s]+)",
        "scripts/container_acceptance.py": r'default="sdex-connectmap:([^\"]+)"',
    }
    for name, pattern in patterns.items():
        match = re.search(pattern, (root / name).read_text(encoding="utf-8"), re.MULTILINE)
        if match is None or match.group(1) != version:
            raise ValueError(f"Project version differs from VERSION in {name}")
    sbom = json.loads((root / "docs/sbom/frontend-runtime.cdx.json").read_text(encoding="utf-8"))
    component = sbom["metadata"]["component"]
    if component["version"] != version or not component["purl"].endswith("@" + version):
        raise ValueError("Frontend SBOM root version differs from VERSION")
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    if re.search(r"sdex-connectmap-\d+\.\d+\.\d+-(?:source\.zip|build-context\.tar)", workflow):
        raise ValueError("CI archive paths must read VERSION rather than hard-code a release")
    builder = (root / "scripts/build_release.py").read_text(encoding="utf-8")
    if 'ROOT / "VERSION"' not in builder or 'f"sdex-connectmap-{version}"' not in builder:
        raise ValueError("Release archive names must derive from VERSION")
    return version


def markdown_anchors(text: str) -> set[str]:
    """Recognize GitHub-style heading anchors, including duplicate headings."""
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.MULTILINE):
        heading = re.sub(r"<[^>]+>", "", heading).lower()
        slug = "".join(
            char for char in heading if char in "-_ " or unicodedata.category(char)[0] in "LN"
        ).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        anchors.add(f"{slug}-{count}" if count else slug)
    return anchors


def verify_dependency_notices(root: Path) -> None:
    def python_name(value: str) -> str:
        return re.sub(r"[-_.]+", "-", value).lower()

    locked_python = dict(
        re.findall(
            r"^([\w.-]+)==([^\s\\]+)",
            (root / "backend/requirements.txt").read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    )
    locked_python = {python_name(name): version for name, version in locked_python.items()}
    python_notices = json.loads((root / "docs/licenses/python-runtime.json").read_text())
    python_sbom = json.loads((root / "docs/sbom/python-runtime.cdx.json").read_text())
    for entries in (python_notices, python_sbom["components"]):
        if {python_name(entry["name"]): entry["version"] for entry in entries} != locked_python:
            raise ValueError("Python runtime inventory differs from the locked dependencies")
    lock = json.loads((root / "frontend/package-lock.json").read_text())
    runtime = {
        name.removeprefix("node_modules/"): entry["version"]
        for name, entry in lock["packages"].items()
        if name and not entry.get("dev")
    }
    npm_notices = json.loads((root / "docs/licenses/npm-runtime.json").read_text())
    if {entry["name"]: entry["version"] for entry in npm_notices} != runtime:
        raise ValueError("npm license inventory differs from the runtime lock entries")
    npm_sbom = json.loads((root / "docs/sbom/frontend-runtime.cdx.json").read_text())
    if {entry["name"]: entry["version"] for entry in npm_sbom["components"]} != runtime:
        raise ValueError("Frontend SBOM differs from the runtime lock entries")
    for entry in python_notices + npm_notices:
        for name in entry["files"]:
            path = (root / name).resolve()
            if not path.is_relative_to((root / "docs/licenses").resolve()) or not path.is_file():
                raise ValueError(f"Missing upstream license file: {name}")


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
    version = verify_versions(root)
    verify_dependency_notices(root)
    if (root / "docs/PUBLISHING.md").exists():
        raise ValueError("Maintainer-specific publishing notes are not a public release asset")
    for path in files:
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8-sig")
        if re.search(r"[A-Za-z]:[\\/]Users[\\/]", text, re.I):
            raise ValueError(f"Machine-specific home path in {path.relative_to(root)}")
        if path.suffix == ".md":
            for target in re.findall(r"!?\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)", text):
                if target.startswith(("https://", "http://", "mailto:")):
                    continue
                target = target.strip("<>")
                local, _, anchor = target.partition("#")
                resolved = (path.parent / unquote(local)).resolve() if local else path.resolve()
                if not resolved.is_relative_to(root.resolve()) or not resolved.exists():
                    raise ValueError(
                        f"Broken or external local link in {path.relative_to(root)}: {target}"
                    )
                if anchor and resolved.suffix == ".md":
                    anchors = markdown_anchors(resolved.read_text(encoding="utf-8"))
                    if unquote(anchor) not in anchors:
                        raise ValueError(
                            f"Broken heading link in {path.relative_to(root)}: {target}"
                        )
        if path.suffix == ".svg" and re.search(
            r"<script\b|<foreignObject\b|\bon\w+\s*=|(?:href|xlink:href)=[\"'](?:https?:|data:)",
            text,
            re.I,
        ):
            raise ValueError(f"Active/external SVG content in {path.relative_to(root)}")
    print(
        f"PASS: {len(files)} public source files; version {version}, inputs, notices, "
        "boundaries and local links/anchors verified."
    )
    return files


if __name__ == "__main__":
    try:
        verify()
    except (OSError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
