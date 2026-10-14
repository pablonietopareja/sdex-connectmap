"""Retain an unsuppressed image inventory and an explicit vulnerability-gate result."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

SEVERITIES = ("UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL")
HIGH_CRITICAL = {"HIGH", "CRITICAL"}
FINDINGS_EXIT_CODE = 42


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, document: object) -> None:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")


def vulnerability_rows(document: dict) -> list[dict]:
    return [
        {**finding, "ResultClass": result.get("Class", "unknown")}
        for result in document["Results"]
        for finding in result.get("Vulnerabilities") or []
    ]


def summarize(rows: list[dict]) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["VulnerabilityID"]].append(row)
    counts = Counter(row["Severity"] for row in rows)
    return {
        "package_advisory_pairs": len(rows),
        "unique_cves": len(groups),
        "severity_counts": {severity: counts[severity] for severity in SEVERITIES},
        "fixed_version_available_pairs": sum(bool(row.get("FixedVersion")) for row in rows),
        "no_fixed_version_pairs": sum(not row.get("FixedVersion") for row in rows),
        "vendor_status_counts": dict(Counter(row.get("Status") or "unknown" for row in rows)),
        "cve_groups": [
            {
                "id": cve,
                "package_advisory_pairs": len(findings),
                "packages": sorted({row["PkgName"] for row in findings}),
                "severities": sorted({row["Severity"] for row in findings}),
                "vendor_statuses": sorted({row.get("Status") or "unknown" for row in findings}),
                "fixed_version_available_pairs": sum(
                    bool(row.get("FixedVersion")) for row in findings
                ),
            }
            for cve, findings in sorted(groups.items())
        ],
    }


def fingerprints(rows: list[dict]) -> Counter:
    fields = (
        "VulnerabilityID",
        "PkgName",
        "InstalledVersion",
        "FixedVersion",
        "Severity",
        "Status",
        "PkgPath",
        "ResultClass",
    )
    return Counter(tuple(row.get(field) or "" for field in fields) for row in rows)


def read_scan(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or document.get("ArtifactType") != "container_image"
        or not isinstance(document.get("Results"), list)
        or not all(isinstance(result, dict) for result in document["Results"])
        or not isinstance(document.get("Metadata"), dict)
        or not document.get("Metadata", {}).get("ImageID")
    ):
        raise ValueError(f"Incomplete container image report: {path.name}")
    return document


def generate_report(
    image: str, output: Path, cache_dir: Path, trivy: str | None = None, *, enforce: bool = False
) -> int:
    output = output.resolve()
    cache_dir = cache_dir.resolve()
    if any((output / name).exists() for name in ("report.json", "full.json", "high-critical.json")):
        print(
            "ERROR: Use a new output directory to preserve previous scan evidence.", file=sys.stderr
        )
        return 1
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "requested_image": image,
        "started_at": timestamp(),
        "scan_execution": "ERROR",
        "high_critical_gate": {
            "status": "NOT_RUN",
            "severities": ["HIGH", "CRITICAL"],
            "enforced": enforce,
            "findings_exit_code": FINDINGS_EXIT_CODE,
        },
    }
    commands: list[dict] = []
    # Repository configuration and inherited scanner filters must not suppress findings.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("TRIVY_")}

    def execute(argv: list[str], log_name: str) -> subprocess.CompletedProcess:
        record = {"argv": argv, "started_at": timestamp()}
        commands.append(record)
        try:
            # Trusted local executables receive an argv list without shell evaluation.
            result = subprocess.run(  # noqa: S603
                argv, capture_output=True, text=True, env=environment, timeout=660, check=False
            )
            (output / log_name).write_text(
                result.stdout + result.stderr, encoding="utf-8", newline="\n"
            )
            record["exit_code"] = result.returncode
            return result
        except (OSError, subprocess.SubprocessError) as exc:
            record["error"] = str(exc)
            partial_log = ""
            if isinstance(exc, subprocess.TimeoutExpired):
                for chunk in (exc.stdout, exc.stderr):
                    if chunk:
                        partial_log += (
                            chunk.decode("utf-8", errors="replace")
                            if isinstance(chunk, bytes)
                            else chunk
                        )
            (output / log_name).write_text(partial_log + str(exc) + "\n", encoding="utf-8")
            raise
        finally:
            record["finished_at"] = timestamp()
            write_json(output / "commands.json", commands)

    try:
        docker = shutil.which("docker")
        scanner = shutil.which(trivy or "trivy")
        if docker is None or scanner is None:
            raise RuntimeError("Docker and the checksum-verified Trivy executable are required")
        inspection = execute([docker, "image", "inspect", image], "docker-inspect.log")
        if inspection.returncode != 0:
            raise RuntimeError(f"Docker image inspection failed with exit {inspection.returncode}")
        images = json.loads(inspection.stdout)
        image_id = images[0]["Id"]
        if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
            raise ValueError("Docker did not return an immutable image ID")
        write_json(output / "docker-inspect.json", images)
        report["image_id"] = image_id
        version = execute([scanner, "--version"], "trivy-version.log")
        if version.returncode != 0:
            raise RuntimeError(f"Trivy version query failed with exit {version.returncode}")
        if not version.stdout.strip():
            raise ValueError("Trivy did not report its version")
        report["scanner_version"] = version.stdout.strip()
        common = [
            scanner,
            "image",
            "--config=",
            "--ignorefile=",
            "--image-src",
            "docker",
            "--cache-dir",
            str(cache_dir),
            "--timeout",
            "10m",
            "--format",
            "json",
            "--list-all-pkgs",
        ]
        full_path = output / "full.json"
        full_scan = execute(
            [
                *common,
                "--scanners",
                "vuln,license",
                "--license-full",
                "--severity",
                ",".join(SEVERITIES),
                "--exit-code",
                "0",
                "--output",
                str(full_path),
                image_id,
            ],
            "full-scan.log",
        )
        if full_scan.returncode != 0:
            raise RuntimeError(f"Full image scan failed with exit {full_scan.returncode}")
        full = read_scan(full_path)
        if full["Metadata"]["ImageID"] != image_id:
            raise ValueError("Full report image ID differs from the Docker-inspected image")
        if not any(
            result.get("Class") == "os-pkgs" and result.get("Packages")
            for result in full["Results"]
        ):
            raise ValueError("Full report has no operating-system package inventory")
        report["distro"] = full["Metadata"].get("OS")
        if not isinstance(report["distro"], dict) or not all(
            report["distro"].get(key) for key in ("Family", "Name")
        ):
            raise ValueError("Full report has no operating-system distribution/version")
        report["scanner_image_id"] = full["Metadata"]["ImageID"]
        rows = vulnerability_rows(full)
        report["vulnerabilities"] = summarize(rows)
        report["vulnerabilities_by_class"] = {
            name: summarize([row for row in rows if row["ResultClass"] == name])
            for name in sorted({row["ResultClass"] for row in rows})
        }
        licenses = [row for result in full["Results"] for row in result.get("Licenses") or []]
        report["license_inventory"] = {
            "full_scan_requested": True,
            "reported_license_rows": len(licenses),
            "classification_counts": dict(
                Counter(row.get("Category") or "unknown" for row in licenses)
            ),
            "note": "Scanner classifications are inventory evidence, not a legal approval.",
        }
        metadata_path = cache_dir / "db" / "metadata.json"
        metadata = metadata_path.read_bytes()
        write_json(output / "db-metadata.json", json.loads(metadata))
        report["db_metadata_sha256"] = hashlib.sha256(metadata).hexdigest()
        gate_path = output / "high-critical.json"
        gate_scan = execute(
            [
                *common,
                "--skip-db-update",
                "--scanners",
                "vuln",
                "--severity",
                "HIGH,CRITICAL",
                "--exit-code",
                str(FINDINGS_EXIT_CODE),
                "--output",
                str(gate_path),
                image_id,
            ],
            "high-critical-scan.log",
        )
        report["high_critical_gate"]["exit_code"] = gate_scan.returncode
        if gate_scan.returncode not in (0, FINDINGS_EXIT_CODE):
            raise RuntimeError(f"Vulnerability-gate scan failed with exit {gate_scan.returncode}")
        gate = read_scan(gate_path)
        expected_rows = [row for row in rows if row["Severity"] in HIGH_CRITICAL]
        if (
            gate["Metadata"]["ImageID"] != full["Metadata"]["ImageID"]
            or gate["Metadata"].get("OS") != full["Metadata"].get("OS")
            or metadata_path.read_bytes() != metadata
            or fingerprints(vulnerability_rows(gate)) != fingerprints(expected_rows)
        ):
            raise ValueError(
                "Gate report differs from the same-image, same-database full inventory"
            )
        expected_exit = FINDINGS_EXIT_CODE if expected_rows else 0
        if gate_scan.returncode != expected_exit:
            raise ValueError("Gate exit code disagrees with the retained HIGH/CRITICAL findings")
        report["high_critical_gate"].update(
            status="FAIL" if expected_rows else "PASS", **summarize(expected_rows)
        )
        report["scan_execution"] = "COMPLETE"
        exit_code = expected_exit if enforce else 0
    except (OSError, ValueError, KeyError, IndexError, TypeError, RuntimeError) as exc:
        report["error"] = str(exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        exit_code = 1
    except subprocess.SubprocessError as exc:
        report["error"] = str(exc)
        print(f"ERROR: Scanner execution failed: {exc}", file=sys.stderr)
        exit_code = 1
    report["finished_at"] = timestamp()
    write_json(output / "report.json", report)
    if report["scan_execution"] == "COMPLETE":
        gate = report["high_critical_gate"]
        disposition = "enforced" if enforce else "informational; not enforced"
        print(
            f"COMPLETE: Image vulnerability/license inventory; HIGH/CRITICAL vulnerability gate "
            f"{gate['status']} ({gate['package_advisory_pairs']} package/advisory pairs, "
            f"{gate['unique_cves']} unique CVEs; {disposition})."
        )
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Already-built local Docker image")
    parser.add_argument("--output", required=True, type=Path, help="New evidence directory")
    parser.add_argument(
        "--cache-dir", required=True, type=Path, help="Trivy database/cache directory"
    )
    parser.add_argument("--trivy", help="Path to the checksum-verified Trivy executable")
    parser.add_argument("--enforce-high-critical", action="store_true")
    args = parser.parse_args(argv)
    return generate_report(
        args.image, args.output, args.cache_dir, args.trivy, enforce=args.enforce_high_critical
    )


if __name__ == "__main__":
    sys.exit(main())
