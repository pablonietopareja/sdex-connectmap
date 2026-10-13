from __future__ import annotations

import pytest

from app.core.config import AppSettings, normalize_base_url


def test_source_settings_default_to_loopback(monkeypatch) -> None:
    monkeypatch.delenv("CONNECTMAP_HOST", raising=False)
    assert AppSettings.from_env().host == "127.0.0.1"


def test_explicit_container_bind_overrides_loopback_default(monkeypatch) -> None:
    container_bind = "0.0.0.0"  # noqa: S104 - explicit container bind override
    monkeypatch.setenv("CONNECTMAP_HOST", container_bind)
    assert AppSettings.from_env().host == container_bind


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://SDEX-SUITE:443/", "https://sdex-suite"),
        ("http://sdex-suite:80", "http://sdex-suite"),
        ("https://sdex-suite:1443///", "https://sdex-suite:1443"),
        ("https://[2001:db8::4]:443/", "https://[2001:db8::4]"),
        ("http://[2001:db8::4]:8080", "http://[2001:db8::4]:8080"),
    ],
)
def test_base_url_is_canonical(raw: str, expected: str) -> None:
    assert normalize_base_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "ftp://sdex-suite",
        "https://",
        "https://user:pass@sdex-suite",
        "https://sdex-suite/path",
        "https://sdex-suite?query=1",
        "http://sdex-suite:0",
        "http://bad host:8080",
        "https://sdex-suite:99999",
    ],
)
def test_invalid_base_urls_are_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_base_url(raw)


@pytest.mark.parametrize(
    "overrides",
    [
        {"port": 0},
        {"port": 65536},
        {"request_timeout_seconds": 0.5},
        {"request_timeout_seconds": 121},
        {"max_concurrency": 0},
        {"max_concurrency": 33},
        {"max_body_bytes": 0},
        {"mock_scenario": "surprise-production-mode"},
    ],
)
def test_application_setting_limits_fail_fast(
    tmp_path,
    settings_factory,
    overrides,
) -> None:
    with pytest.raises(ValueError):
        settings_factory(tmp_path, **overrides)


def test_custom_ca_path_from_environment_is_absolute_and_normalized(
    tmp_path,
    monkeypatch,
) -> None:
    ca_file = tmp_path / "local-ca.PEM"
    ca_file.write_text("certificate contents are validated by the TLS library", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CONNECTMAP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SDEX_CA_CERT_PATH", "./local-ca.PEM")

    settings = AppSettings.from_env()

    assert settings.sdex_ca_cert_path == ca_file.resolve()


@pytest.mark.parametrize("relative_path", ["missing.pem", "not-a-certificate.txt", "ca.crt"])
def test_custom_ca_path_rejects_missing_non_certificate_or_directory(
    tmp_path,
    monkeypatch,
    relative_path,
) -> None:
    if relative_path == "not-a-certificate.txt":
        (tmp_path / relative_path).write_text("not a certificate", encoding="utf-8")
    elif relative_path == "ca.crt":
        (tmp_path / relative_path).mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CONNECTMAP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SDEX_CA_CERT_PATH", relative_path)

    with pytest.raises(
        ValueError,
        match="SDEX_CA_CERT_PATH must reference an existing PEM or CRT file",
    ):
        AppSettings.from_env()
