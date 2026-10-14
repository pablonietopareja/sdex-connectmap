from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "image_security_report", PROJECT_ROOT / "scripts" / "image_security_report.py"
)
assert spec is not None and spec.loader is not None
image_security = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image_security)

IMAGE_ID = "sha256:" + "a" * 64
FINDINGS = [
    {
        "VulnerabilityID": "CVE-2099-0001",
        "PkgName": "library-a",
        "InstalledVersion": "1.0",
        "Severity": "HIGH",
        "Status": "fix_deferred",
    },
    {
        "VulnerabilityID": "CVE-2099-0001",
        "PkgName": "library-b",
        "InstalledVersion": "1.0",
        "Severity": "HIGH",
        "Status": "fix_deferred",
    },
    {
        "VulnerabilityID": "CVE-2099-0002",
        "PkgName": "library-c",
        "InstalledVersion": "1.0",
        "Severity": "CRITICAL",
        "Status": "will_not_fix",
    },
    {
        "VulnerabilityID": "CVE-2099-0003",
        "PkgName": "library-d",
        "InstalledVersion": "1.0",
        "FixedVersion": "1.1",
        "Severity": "MEDIUM",
        "Status": "fixed",
    },
]


def scan_document(rows: list[dict]) -> dict:
    return {
        "ArtifactType": "container_image",
        "Metadata": {"ImageID": IMAGE_ID, "OS": {"Family": "debian", "Name": "13"}},
        "Results": [
            {
                "Class": "os-pkgs",
                "Packages": [{"Name": "library-a", "Version": "1.0"}],
                "Vulnerabilities": copy.deepcopy(rows),
            }
        ],
    }


@pytest.fixture
def scan_process(tmp_path, monkeypatch):
    def install(
        *,
        rows=None,
        failure_stage=None,
        failure_exit=1,
        gate_exit=None,
        gate_edit=None,
        full_edit=None,
        change_database=False,
        timeout_stage=None,
    ):
        findings = copy.deepcopy(FINDINGS if rows is None else rows)
        output = tmp_path / "evidence"
        cache = tmp_path / "cache"
        metadata = cache / "db" / "metadata.json"
        metadata.parent.mkdir(parents=True)
        metadata.write_text('{"UpdatedAt":"2099-01-01T00:00:00Z"}', encoding="utf-8")
        calls = []
        monkeypatch.setattr(image_security.shutil, "which", lambda command: command)

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            if argv[0] == "docker":
                stage = "docker"
                stdout = json.dumps([{"Id": IMAGE_ID, "Architecture": "amd64"}])
                exit_code = 0
            elif argv[1] == "--version":
                stage = "version"
                stdout = "Version: 0.75.0\n"
                exit_code = 0
            else:
                stage = "gate" if "--skip-db-update" in argv else "full"
                stage_rows = (
                    [row for row in findings if row["Severity"] in {"HIGH", "CRITICAL"}]
                    if stage == "gate"
                    else findings
                )
                document = scan_document(stage_rows)
                if stage == "full":
                    document["Results"].append(
                        {
                            "Class": "license",
                            "Licenses": [
                                {"Name": "GPL-2.0", "Severity": "HIGH", "Category": "restricted"}
                            ],
                        }
                    )
                    if full_edit:
                        full_edit(document)
                elif gate_edit:
                    gate_edit(document)
                path = Path(argv[argv.index("--output") + 1])
                path.write_text(json.dumps(document), encoding="utf-8")
                if stage == "gate" and change_database:
                    metadata.write_text('{"UpdatedAt":"2099-01-02T00:00:00Z"}', encoding="utf-8")
                stdout = f"{stage} scan log\n"
                exit_code = 42 if stage == "gate" and stage_rows else 0
                if stage == "gate" and gate_exit is not None:
                    exit_code = gate_exit
            if stage == timeout_stage:
                raise subprocess.TimeoutExpired(argv, timeout=660)
            if stage == failure_stage:
                exit_code = failure_exit
            return subprocess.CompletedProcess(argv, exit_code, stdout, "")

        monkeypatch.setattr(image_security.subprocess, "run", run)
        return output, cache, calls

    return install


def read_report(output: Path) -> dict:
    return json.loads((output / "report.json").read_text(encoding="utf-8"))


def test_unsuppressed_inventory_preserves_unfixed_findings_and_groups_duplicate_cves(
    scan_process, monkeypatch, capsys
) -> None:
    output, cache, calls = scan_process()
    monkeypatch.setenv("TRIVY_IGNORE_UNFIXED", "true")
    monkeypatch.setenv("TRIVY_SEVERITY", "CRITICAL")
    assert image_security.generate_report("synthetic:ci", output, cache) == 0
    report = read_report(output)
    assert report["scan_execution"] == "COMPLETE"
    assert report["high_critical_gate"]["status"] == "FAIL"
    assert report["high_critical_gate"]["exit_code"] == 42
    assert report["high_critical_gate"]["enforced"] is False
    assert report["high_critical_gate"]["package_advisory_pairs"] == 3
    assert report["high_critical_gate"]["unique_cves"] == 2
    assert report["vulnerabilities"]["fixed_version_available_pairs"] == 1
    assert report["vulnerabilities"]["no_fixed_version_pairs"] == 3
    assert report["vulnerabilities"]["cve_groups"][0]["packages"] == ["library-a", "library-b"]
    full = json.loads((output / "full.json").read_text())
    assert full["Results"][0]["Vulnerabilities"] == FINDINGS
    assert full["Results"][1]["Licenses"][0]["Name"] == "GPL-2.0"
    image_commands = [argv for argv, _ in calls if argv[0] == "trivy" and argv[1] == "image"]
    assert len(image_commands) == 2
    assert all(argv[-1] == IMAGE_ID for argv in image_commands)
    assert all("--config=" in argv and "--ignorefile=" in argv for argv in image_commands)
    assert all("--ignore-unfixed" not in argv for argv in image_commands)
    assert "--license-full" in image_commands[0]
    assert "UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL" in image_commands[0]
    assert "vuln,license" in image_commands[0] and "vuln" in image_commands[1]
    assert all(not any(key.startswith("TRIVY_") for key in kwargs["env"]) for _, kwargs in calls)
    assert (output / "docker-inspect.json").is_file()
    assert (output / "db-metadata.json").is_file()
    assert (output / "commands.json").is_file()
    assert "COMPLETE" in capsys.readouterr().out


def test_high_license_classification_does_not_fail_a_vulnerability_only_gate(scan_process) -> None:
    output, cache, _ = scan_process(rows=[FINDINGS[-1]])
    assert image_security.generate_report("synthetic:ci", output, cache) == 0
    report = read_report(output)
    assert report["high_critical_gate"]["status"] == "PASS"
    assert report["high_critical_gate"]["exit_code"] == 0
    assert report["license_inventory"]["classification_counts"] == {"restricted": 1}


def test_explicit_cli_enforcement_returns_findings_exit_without_discarding_evidence(
    scan_process,
) -> None:
    output, cache, _ = scan_process()
    assert (
        image_security.main(
            [
                "--image",
                "synthetic:ci",
                "--output",
                str(output),
                "--cache-dir",
                str(cache),
                "--trivy",
                "trivy",
                "--enforce-high-critical",
            ]
        )
        == 42
    )
    assert read_report(output)["high_critical_gate"]["enforced"] is True
    assert (output / "full.json").is_file() and (output / "high-critical.json").is_file()


@pytest.mark.parametrize("stage", ["docker", "version", "full", "gate"])
def test_operational_failures_are_errors_even_if_partial_json_exists(scan_process, stage) -> None:
    output, cache, _ = scan_process(failure_stage=stage, failure_exit=7)
    assert image_security.generate_report("synthetic:ci", output, cache) == 1
    report = read_report(output)
    assert report["scan_execution"] == "ERROR"
    assert report["high_critical_gate"]["status"] == "NOT_RUN"
    assert "exit 7" in report["error"]


@pytest.mark.parametrize("exit_code", [0, 1])
def test_exit_code_cannot_claim_pass_or_findings_without_agreeing_with_raw_scan(
    scan_process, exit_code
) -> None:
    output, cache, _ = scan_process(gate_exit=exit_code)
    assert image_security.generate_report("synthetic:ci", output, cache) == 1
    assert read_report(output)["scan_execution"] == "ERROR"


def test_findings_exit_with_zero_high_critical_rows_is_an_error(scan_process) -> None:
    output, cache, _ = scan_process(rows=[], gate_exit=42)
    assert image_security.generate_report("synthetic:ci", output, cache) == 1
    assert "exit code disagrees" in read_report(output)["error"]


def test_dropped_advisory_pair_in_gate_is_rejected(scan_process) -> None:
    output, cache, _ = scan_process(
        gate_edit=lambda data: data["Results"][0]["Vulnerabilities"].pop()
    )
    assert image_security.generate_report("synthetic:ci", output, cache) == 1
    assert "differs" in read_report(output)["error"]


def test_gate_image_drift_is_rejected(scan_process) -> None:
    output, cache, _ = scan_process(
        gate_edit=lambda data: data["Metadata"].update(ImageID="sha256:" + "b" * 64)
    )
    assert image_security.generate_report("synthetic:ci", output, cache) == 1
    assert "same-image" in read_report(output)["error"]


def test_matching_scanner_reports_for_another_image_are_rejected(scan_process) -> None:
    def change_image(document):
        document["Metadata"]["ImageID"] = "sha256:" + "b" * 64

    output, cache, calls = scan_process(full_edit=change_image, gate_edit=change_image)
    assert image_security.generate_report("synthetic:ci", output, cache) == 1
    report = read_report(output)
    assert report["scan_execution"] == "ERROR"
    assert "Docker-inspected image" in report["error"]
    assert (output / "full.json").is_file()
    assert not any("--skip-db-update" in argv for argv, _ in calls)


def test_gate_database_drift_is_rejected(scan_process) -> None:
    output, cache, _ = scan_process(change_database=True)
    assert image_security.generate_report("synthetic:ci", output, cache) == 1
    assert "same-database" in read_report(output)["error"]


def test_absent_os_inventory_is_an_error(scan_process) -> None:
    output, cache, _ = scan_process(full_edit=lambda data: data["Results"][0].pop("Packages"))
    assert image_security.generate_report("synthetic:ci", output, cache) == 1
    assert "operating-system package inventory" in read_report(output)["error"]


def test_missing_distro_version_is_an_error(scan_process) -> None:
    output, cache, _ = scan_process(full_edit=lambda data: data["Metadata"].pop("OS"))
    assert image_security.generate_report("synthetic:ci", output, cache) == 1
    assert "distribution/version" in read_report(output)["error"]


def test_malformed_scanner_json_is_not_reported_complete(scan_process) -> None:
    output, cache, _ = scan_process(full_edit=lambda data: data.update(Results=[None]))
    assert image_security.generate_report("synthetic:ci", output, cache) == 1
    assert "Incomplete container image report" in read_report(output)["error"]


def test_scanner_timeout_is_recorded_as_error(scan_process) -> None:
    output, cache, _ = scan_process(timeout_stage="full")
    assert image_security.generate_report("synthetic:ci", output, cache) == 1
    assert read_report(output)["scan_execution"] == "ERROR"
    commands = json.loads((output / "commands.json").read_text())
    assert "error" in commands[-1] and "finished_at" in commands[-1]


def test_missing_scanner_is_not_a_successful_scan(scan_process, monkeypatch) -> None:
    output, cache, _ = scan_process()
    monkeypatch.setattr(image_security.shutil, "which", lambda command: None)
    assert image_security.generate_report("synthetic:ci", output, cache) == 1
    assert read_report(output)["scan_execution"] == "ERROR"


def test_existing_evidence_is_never_overwritten(scan_process) -> None:
    output, cache, calls = scan_process()
    assert image_security.generate_report("synthetic:ci", output, cache) == 0
    previous = (output / "full.json").read_bytes()
    command_count = len(calls)
    assert image_security.generate_report("synthetic:ci", output, cache) == 1
    assert (output / "full.json").read_bytes() == previous
    assert len(calls) == command_count
