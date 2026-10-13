from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any

import pytest

from app.models.schemas import ConnectionProfile
from app.services import sdex_client
from app.services.sdex_client import SDEXClient


class _UnusedAsyncClient:
    pass


def _profile(ca_cert_path: Path) -> ConnectionProfile:
    return ConnectionProfile(
        base_url="https://sdex.test",
        username="reader",
        password="secret",
        verify_tls=True,
        ca_cert_path=ca_cert_path,
    )


def test_custom_ca_builds_ssl_context_and_disables_ambient_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ca_file = tmp_path / "sdex-ca.crt"
    ca_file.write_text("fixture content", encoding="utf-8")
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    captured_context_args: dict[str, Any] = {}
    captured_client_options: dict[str, Any] = {}

    def create_default_context(*, cafile: str) -> ssl.SSLContext:
        captured_context_args["cafile"] = cafile
        return ssl_context

    def client_factory(**options: Any) -> _UnusedAsyncClient:
        captured_client_options.update(options)
        return _UnusedAsyncClient()

    monkeypatch.setattr(sdex_client.ssl, "create_default_context", create_default_context)
    monkeypatch.setattr(sdex_client.httpx, "AsyncClient", client_factory)

    SDEXClient(_profile(ca_file.resolve()))

    assert captured_context_args == {"cafile": str(ca_file.resolve())}
    assert captured_client_options["verify"] is ssl_context
    assert captured_client_options["trust_env"] is False
    timeout = captured_client_options["timeout"]
    assert timeout.connect == 5.0
    assert timeout.read == 15.0


def test_invalid_custom_ca_content_fails_before_http_client_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ca_file = tmp_path / "invalid-ca.pem"
    ca_file.write_text("not a PEM certificate", encoding="utf-8")
    client_created = False

    def client_factory(**_options: Any) -> _UnusedAsyncClient:
        nonlocal client_created
        client_created = True
        return _UnusedAsyncClient()

    monkeypatch.setattr(sdex_client.httpx, "AsyncClient", client_factory)

    with pytest.raises(
        ValueError,
        match="configured SDEX CA certificate could not be loaded",
    ):
        SDEXClient(_profile(ca_file.resolve()))

    assert client_created is False
