from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "release_verifier", PROJECT_ROOT / "scripts" / "verify_release.py"
)
assert spec is not None and spec.loader is not None
release_verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_verifier)

METADATA_FILES = (
    "VERSION",
    "backend/app/__init__.py",
    "frontend/package.json",
    "frontend/package-lock.json",
    "Dockerfile",
    "compose.yaml",
    "portainer-stack.yml",
    ".env.example",
    "scripts/container_acceptance.py",
    "scripts/build_release.py",
    ".github/workflows/ci.yml",
    "docs/sbom/frontend-runtime.cdx.json",
)


def copy_files(destination: Path, names) -> None:
    for name in names:
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((PROJECT_ROOT / name).read_bytes())


@pytest.fixture
def metadata_tree(tmp_path: Path) -> Path:
    copy_files(tmp_path, METADATA_FILES)
    return tmp_path


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize(
    ("name", "json_path"),
    [
        ("frontend/package.json", ("version",)),
        ("frontend/package-lock.json", ("version",)),
        ("frontend/package-lock.json", ("packages", "", "version")),
        ("docs/sbom/frontend-runtime.cdx.json", ("metadata", "component", "version")),
        ("docs/sbom/frontend-runtime.cdx.json", ("metadata", "component", "purl")),
    ],
)
def test_project_json_version_drift_is_rejected(metadata_tree, name, json_path) -> None:
    path = metadata_tree / name
    data = json.loads(path.read_text(encoding="utf-8"))
    current = data
    for key in json_path[:-1]:
        current = current[key]
    current[json_path[-1]] = (
        "pkg:npm/sdex-connectmap-frontend@9.9.9" if (json_path[-1] == "purl") else "9.9.9"
    )
    write_json(path, data)
    with pytest.raises(ValueError, match="version differs"):
        release_verifier.verify_versions(metadata_tree)


@pytest.mark.parametrize(
    ("name", "field"),
    [
        ("backend/app/__init__.py", '__version__ = "{version}"'),
        ("Dockerfile", 'org.opencontainers.image.version="{version}"'),
        ("compose.yaml", "CONNECTMAP_IMAGE:-sdex-connectmap:{version}"),
        ("portainer-stack.yml", "CONNECTMAP_IMAGE:-sdex-connectmap:{version}"),
        (".env.example", "CONNECTMAP_IMAGE=sdex-connectmap:{version}"),
        ("scripts/container_acceptance.py", 'default="sdex-connectmap:{version}"'),
    ],
)
def test_runtime_and_deployment_version_drift_is_rejected(metadata_tree, name, field) -> None:
    version = (metadata_tree / "VERSION").read_text().strip()
    path = metadata_tree / name
    text = path.read_text(encoding="utf-8")
    expected = field.format(version=version)
    assert expected in text
    path.write_text(text.replace(expected, field.format(version="9.9.9")), encoding="utf-8")
    with pytest.raises(ValueError, match="version differs"):
        release_verifier.verify_versions(metadata_tree)


@pytest.mark.parametrize("version", ["v1.0.1", "1.0", "1.0.1-rc.1", "1.0.1\n1.0.0"])
def test_invalid_release_version_is_rejected(metadata_tree, version) -> None:
    (metadata_tree / "VERSION").write_text(version, encoding="utf-8")
    with pytest.raises(ValueError, match="semantic release version"):
        release_verifier.verify_versions(metadata_tree)


@pytest.mark.parametrize("suffix", ["source.zip", "build-context.tar"])
def test_hardcoded_ci_archive_version_is_rejected(metadata_tree, suffix) -> None:
    path = metadata_tree / ".github/workflows/ci.yml"
    path.write_text(
        path.read_text() + f"\n      - run: ls dist/sdex-connectmap-1.0.0-{suffix}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="CI archive paths must read VERSION"):
        release_verifier.verify_versions(metadata_tree)


def test_history_and_dependency_versions_do_not_count_as_project_drift(metadata_tree) -> None:
    (metadata_tree / "CHANGELOG.md").write_text(
        "# Changelog\n\n## 1.0.0\n\nInitial public source publication.\n", encoding="utf-8"
    )
    (metadata_tree / "backend/requirements-dev.txt").write_text(
        "pytest-asyncio==1.0.0\n", encoding="utf-8"
    )
    lock_path = metadata_tree / "frontend/package-lock.json"
    lock = json.loads(lock_path.read_text())
    lock["packages"]["node_modules/synthetic-dependency"] = {"version": "1.0.0", "dev": True}
    write_json(lock_path, lock)
    assert (
        release_verifier.verify_versions(metadata_tree)
        == (metadata_tree / "VERSION").read_text().strip()
    )


def test_public_api_metadata_agrees_with_release_version(tmp_path, settings_factory) -> None:
    version = (PROJECT_ROOT / "VERSION").read_text().strip()
    settings = settings_factory(tmp_path, mock_mode=True, disable_docs=False)
    application = create_app(settings)
    assert application.version == version
    with TestClient(application) as client:
        assert client.get("/api/health").json()["version"] == version
        assert client.get("/api/openapi.json").json()["info"]["version"] == version


@pytest.fixture
def notice_tree(tmp_path: Path) -> Path:
    names = [
        "backend/requirements.txt",
        "frontend/package-lock.json",
        "docs/licenses/python-runtime.json",
        "docs/licenses/npm-runtime.json",
        "docs/sbom/python-runtime.cdx.json",
        "docs/sbom/frontend-runtime.cdx.json",
    ]
    for inventory in ("docs/licenses/python-runtime.json", "docs/licenses/npm-runtime.json"):
        for entry in json.loads((PROJECT_ROOT / inventory).read_text()):
            names.extend(entry["files"])
    copy_files(tmp_path, set(names))
    return tmp_path


@pytest.mark.parametrize(
    ("name", "component_path"),
    [
        ("docs/licenses/python-runtime.json", ()),
        ("docs/licenses/npm-runtime.json", ()),
        ("docs/sbom/python-runtime.cdx.json", ("components",)),
        ("docs/sbom/frontend-runtime.cdx.json", ("components",)),
    ],
)
def test_dependency_inventory_version_drift_is_rejected(notice_tree, name, component_path) -> None:
    path = notice_tree / name
    data = json.loads(path.read_text())
    components = data
    for key in component_path:
        components = components[key]
    components[0]["version"] = "9.9.9"
    write_json(path, data)
    with pytest.raises(ValueError, match="(?:inventory differs|SBOM)"):
        release_verifier.verify_dependency_notices(notice_tree)


def test_missing_frontend_sbom_component_is_rejected(notice_tree) -> None:
    path = notice_tree / "docs/sbom/frontend-runtime.cdx.json"
    data = json.loads(path.read_text())
    data["components"].pop()
    write_json(path, data)
    with pytest.raises(ValueError, match="SBOM"):
        release_verifier.verify_dependency_notices(notice_tree)


def test_missing_upstream_license_text_is_rejected(notice_tree) -> None:
    inventory = json.loads((notice_tree / "docs/licenses/python-runtime.json").read_text())
    (notice_tree / inventory[0]["files"][0]).unlink()
    with pytest.raises(ValueError, match="Missing upstream license file"):
        release_verifier.verify_dependency_notices(notice_tree)


def test_github_heading_anchors_handle_duplicates_unicode_and_fenced_code() -> None:
    anchors = release_verifier.markdown_anchors(
        "# Quick start\n## Repeat\n## Repeat\n### Install `package`\n"
        "## Español & APIs\n```md\n# Hidden heading\n```\n"
    )
    assert anchors == {"quick-start", "repeat", "repeat-1", "install-package", "español--apis"}


@pytest.fixture
def linked_tree(metadata_tree: Path, notice_tree: Path) -> Path:
    assert metadata_tree == notice_tree
    names = (release_verifier.ROOT_FILES - {".gitleaks.toml"}) | {
        "backend/app/main.py",
        "backend/requirements-dev.txt",
        "backend/requirements.in",
        "backend/requirements-dev.in",
        "frontend/src/main.tsx",
    }
    copy_files(metadata_tree, names)
    for name in release_verifier.ROOT_FILES:
        if name.endswith(".md"):
            (metadata_tree / name).write_text("# Guide\n", encoding="utf-8")
    (metadata_tree / "docs/guide.md").write_text(
        "# Known heading\n\n## Repeat\n\n## Repeat\n", encoding="utf-8"
    )
    return metadata_tree


@pytest.mark.parametrize("anchor", ["known-heading", "repeat-1"])
def test_local_heading_links_are_validated_against_target_document(linked_tree, anchor) -> None:
    (linked_tree / "README.md").write_text(
        f"# Guide\n\n[Related guide](docs/guide.md#{anchor})\n", encoding="utf-8"
    )
    assert linked_tree / "docs/guide.md" in release_verifier.verify(linked_tree)


def test_missing_heading_link_is_rejected_even_when_document_exists(linked_tree) -> None:
    (linked_tree / "README.md").write_text(
        "# Guide\n\n[Related guide](docs/guide.md#missing-heading)\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Broken heading link"):
        release_verifier.verify(linked_tree)


def load_script(filename: str):
    script_spec = importlib.util.spec_from_file_location(
        filename.removesuffix(".py"), PROJECT_ROOT / "scripts" / filename
    )
    assert script_spec is not None and script_spec.loader is not None
    module = importlib.util.module_from_spec(script_spec)
    script_spec.loader.exec_module(module)
    return module


@pytest.fixture
def sbom_tree(metadata_tree: Path) -> Path:
    copy_files(metadata_tree, ("docs/licenses/npm-runtime.json",))
    return metadata_tree


def test_runtime_sbom_covers_direct_dependencies_peers_and_all_lock_entries(sbom_tree) -> None:
    document = load_script("build_frontend_sbom.py").build(sbom_tree)
    lock = json.loads((sbom_tree / "frontend/package-lock.json").read_text())
    runtime = {
        name.removeprefix("node_modules/"): entry["version"]
        for name, entry in lock["packages"].items()
        if name and not entry.get("dev")
    }
    assert {component["name"]: component["version"] for component in document["components"]} == (
        runtime
    )
    refs = {component["name"]: component["bom-ref"] for component in document["components"]}
    graph = {entry["ref"]: set(entry["dependsOn"]) for entry in document["dependencies"]}
    root_ref = document["metadata"]["component"]["bom-ref"]
    assert graph[root_ref] == {refs["@xyflow/react"], refs["react"], refs["react-dom"]}
    assert {refs["react"], refs["react-dom"]} <= graph[refs["@xyflow/react"]]
    assert graph[refs["react-dom"]] >= {refs["react"], refs["scheduler"]}
    assert set(graph) == set(refs.values()) | {root_ref}
    assert all(required <= set(refs.values()) for required in graph.values())


def test_runtime_sbom_is_deterministic_under_lock_entry_reordering(sbom_tree) -> None:
    builder = load_script("build_frontend_sbom.py")
    expected = json.dumps(builder.build(sbom_tree), indent=2)
    path = sbom_tree / "frontend/package-lock.json"
    lock = json.loads(path.read_text())
    lock["packages"] = dict(reversed(tuple(lock["packages"].items())))
    write_json(path, lock)
    assert json.dumps(builder.build(sbom_tree), indent=2) == expected


def test_runtime_sbom_rejects_missing_license_notice(sbom_tree) -> None:
    path = sbom_tree / "docs/licenses/npm-runtime.json"
    notices = json.loads(path.read_text())
    notices.pop()
    write_json(path, notices)
    with pytest.raises(ValueError, match="license notices must match"):
        load_script("build_frontend_sbom.py").build(sbom_tree)


def test_archive_names_contents_checksums_and_rebuild_are_versioned_and_deterministic(
    tmp_path, monkeypatch
) -> None:
    version = (PROJECT_ROOT / "VERSION").read_text().strip()
    names = (
        "VERSION",
        "README.md",
        "Dockerfile",
        "backend/requirements.txt",
        "backend/app/__init__.py",
    )
    copy_files(tmp_path, names)
    monkeypatch.setitem(sys.modules, "verify_release", release_verifier)
    builder = load_script("build_release.py")
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "verify", lambda: [tmp_path / name for name in sorted(names)])
    builder.main()
    source = tmp_path / "dist" / f"sdex-connectmap-{version}-source.zip"
    context = tmp_path / "dist" / f"sdex-connectmap-{version}-build-context.tar"
    with zipfile.ZipFile(source) as archive:
        assert set(archive.namelist()) == set(names)
        assert all(archive.read(name) == (tmp_path / name).read_bytes() for name in names)
        assert all(entry.external_attr >> 16 == 0o100644 for entry in archive.infolist())
    with tarfile.open(context) as archive:
        assert set(archive.getnames()) == {
            "Dockerfile",
            "backend/requirements.txt",
            "backend/app/__init__.py",
        }
        assert all(entry.mode == 0o644 and entry.mtime == 0 for entry in archive.getmembers())
    checksums = (tmp_path / "dist/SHA256SUMS").read_text().splitlines()
    assert checksums == [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
        for path in (source, context)
    ]
    first = [path.read_bytes() for path in (source, context)]
    builder.main()
    assert [path.read_bytes() for path in (source, context)] == first
