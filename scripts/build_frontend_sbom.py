"""Build a deterministic runtime CycloneDX inventory from the npm lock and notices."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def build(root: Path = ROOT) -> dict:
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    package = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((root / "frontend/package-lock.json").read_text(encoding="utf-8"))
    notices = json.loads((root / "docs/licenses/npm-runtime.json").read_text(encoding="utf-8"))
    licenses = {entry["name"]: entry["license"] for entry in notices}
    runtime = {
        name.removeprefix("node_modules/"): entry
        for name, entry in lock["packages"].items()
        if name and not entry.get("dev")
    }
    if set(runtime) != set(licenses):
        raise ValueError("Runtime npm entries and license notices must match")
    refs = {name: f"{name}@{entry['version']}" for name, entry in runtime.items()}
    root_ref = f"{package['name']}@{version}"
    components = [
        {
            "type": "library",
            "bom-ref": refs[name],
            "name": name,
            "version": entry["version"],
            "scope": "required",
            "purl": f"pkg:npm/{quote(name, safe='/')}@{entry['version']}",
            "licenses": [{"license": {"id": licenses[name]}}],
        }
        for name, entry in sorted(runtime.items())
    ]
    dependencies = [
        {"ref": root_ref, "dependsOn": sorted(refs[name] for name in package["dependencies"])}
    ]
    for name, entry in sorted(runtime.items()):
        required = set(entry.get("dependencies", {})) | set(entry.get("peerDependencies", {}))
        dependencies.append(
            {"ref": refs[name], "dependsOn": sorted(refs[key] for key in required if key in refs)}
        )
    return {
        "$schema": "http://cyclonedx.org/schema/bom-1.5.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "tools": [{"vendor": "SDEX ConnectMap", "name": "build_frontend_sbom.py"}],
            "component": {
                "type": "application",
                "bom-ref": root_ref,
                "name": package["name"],
                "version": version,
                "purl": f"pkg:npm/{package['name']}@{version}",
            },
        },
        "components": components,
        "dependencies": dependencies,
    }


if __name__ == "__main__":
    destination = ROOT / "docs/sbom/frontend-runtime.cdx.json"
    document = build()
    destination.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"PASS: {len(document['components'])} locked npm runtime components inventoried.")
