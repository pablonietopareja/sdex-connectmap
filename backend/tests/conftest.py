from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.core.config import AppSettings
from app.core.security import CredentialCipher
from app.persistence import Database


def make_settings(
    root: Path,
    *,
    mock_mode: bool = False,
    mock_scenario: str = "stable",
    **overrides,
) -> AppSettings:
    values = {
        "host": "127.0.0.1",
        "port": 8080,
        "data_dir": root,
        "database_path": root / "connectmap.db",
        "secret_key": Fernet.generate_key().decode("ascii"),
        "log_level": "WARNING",
        "mock_mode": mock_mode,
        "mock_scenario": mock_scenario,
        "default_refresh_seconds": 300,
        "request_timeout_seconds": 1.0,
        "max_concurrency": 4,
        "disable_docs": True,
        "static_dir": None,
        "max_body_bytes": 256 * 1024,
        "sdex_base_url": None,
        "sdex_username": None,
        "sdex_password": None,
        "sdex_verify_tls": True,
        "sdex_ca_cert_path": None,
    }
    values.update(overrides)
    return AppSettings(**values)


@pytest.fixture
def settings_factory():
    return make_settings


@pytest.fixture
async def database(tmp_path: Path) -> Database:
    cipher = CredentialCipher(Fernet.generate_key())
    db = Database(tmp_path / "connectmap.db", cipher)
    await db.initialize()
    return db
