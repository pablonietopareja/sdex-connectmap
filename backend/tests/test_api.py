from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.security import CredentialCipher
from app.main import create_app
from app.models.schemas import ConnectionProfile
from app.persistence import Database
from app.services.mock_sdex import SYSTEM_FIXTURE


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://untrusted.example"},
        {"Origin": "null"},
        {"Origin": "http://testserver/invalid-path"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_browser_cross_origin_changes_are_rejected_without_mutating_settings(
    tmp_path: Path, settings_factory, headers: dict[str, str]
) -> None:
    settings = settings_factory(tmp_path, mock_mode=True)
    with TestClient(create_app(settings)) as client:
        result = client.put("/api/settings", json={"theme": "dark"}, headers=headers)
        assert result.status_code == 403
        assert result.json()["error"]["code"] == "cross_origin_request"
        assert result.headers["x-frame-options"] == "DENY"
        assert client.get("/api/settings").json()["theme"] == "system"
        assert client.post("/api/layout/reset", headers=headers).status_code == 403


@pytest.mark.parametrize("headers", [{}, {"Origin": "http://testserver"}])
def test_same_origin_and_native_api_changes_remain_supported(
    tmp_path: Path, settings_factory, headers: dict[str, str]
) -> None:
    settings = settings_factory(tmp_path, mock_mode=True)
    with TestClient(create_app(settings)) as client:
        result = client.put("/api/settings", json={"theme": "dark"}, headers=headers)
        assert result.status_code == 200
        assert client.get("/api/settings").json()["theme"] == "dark"


def test_topology_layout_and_settings_survive_application_restart(
    tmp_path: Path, settings_factory
) -> None:
    settings = settings_factory(tmp_path, mock_mode=True, mock_scenario="visual_preview")
    node_id = "mqtt_broker:factory-mqtt-broker"
    with TestClient(create_app(settings)) as client:
        client.portal.call(asyncio.sleep, 0.1)
        assert (
            client.put(
                "/api/layout",
                json={
                    "positions": [{"node_id": node_id, "x": 44, "y": 55}],
                    "viewport": {"x": 12, "y": 24, "zoom": 1.25},
                },
            ).status_code
            == 200
        )
        assert client.put("/api/settings", json={"theme": "dark"}).status_code == 200
    with TestClient(create_app(settings)) as restarted:
        restarted.portal.call(asyncio.sleep, 0.1)
        persisted = restarted.get("/api/topology").json()["layout"]
        assert persisted["positions"][node_id] == {"x": 44.0, "y": 55.0}
        assert persisted["viewport"]["zoom"] == 1.25
        assert restarted.get("/api/settings").json()["theme"] == "dark"


def test_mock_api_health_refresh_topology_settings_and_layout(
    tmp_path: Path,
    settings_factory,
) -> None:
    settings = settings_factory(tmp_path, mock_mode=True, mock_scenario="stable")
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["mock_mode"] is True
        assert health.json()["scheduler"] == "running"
        assert health.headers["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in health.headers["content-security-policy"]

        accepted = client.post("/api/topology/refresh")
        assert accepted.status_code == 202
        assert accepted.json()["accepted"] is True
        # The coordinated task is short; wait through the application's event loop.
        client.portal.call(asyncio.sleep, 0.1)
        topology = client.get("/api/topology").json()
        node_types = {node["type"] for node in topology["nodes"]}
        assert len(node_types) == 9
        assert topology["mock_mode"] is True
        assert topology["stale"] is False
        assert topology["layout"]["positions"]["sdex_gateway:sdex"] == {
            "x": 0.0,
            "y": 0.0,
        }
        assert topology["layout"]["viewport"] is None

        settings_response = client.put(
            "/api/settings",
            json={
                "refresh_interval_seconds": 900,
                "show_not_enabled": True,
                "theme": "dark",
            },
        )
        assert settings_response.status_code == 200
        assert settings_response.json()["allowed_refresh_intervals"] == [
            60,
            300,
            600,
            900,
            1800,
            3600,
        ]
        assert settings_response.json()["theme"] == "dark"

        assert (
            client.put(
                "/api/layout",
                json={
                    "positions": [{"node_id": "mqtt_broker:plant-broker", "x": 22, "y": 33}],
                    "viewport": {"x": 10, "y": 20, "zoom": 1.4},
                },
            ).status_code
            == 200
        )
        persisted = client.get("/api/topology").json()["layout"]
        assert persisted["positions"]["mqtt_broker:plant-broker"] == {
            "x": 22.0,
            "y": 33.0,
        }
        assert persisted["viewport"]["zoom"] == 1.4
        assert client.post("/api/layout/reset").status_code == 200
        reset = client.get("/api/topology").json()["layout"]
        assert reset["viewport"] is None


def test_validation_and_body_limit_do_not_echo_password(
    tmp_path: Path,
    settings_factory,
) -> None:
    settings = settings_factory(
        tmp_path,
        mock_mode=True,
        max_body_bytes=128,
    )
    with TestClient(create_app(settings)) as client:
        secret = "never-echo-this-password"
        invalid = client.post(
            "/api/config/test",
            content=json.dumps(
                {
                    "base_url": "https://sdex",
                    "password": secret,
                    "verify_tls": True,
                }
            ),
            headers={"content-type": "application/json"},
        )
        assert invalid.status_code == 422
        assert secret not in invalid.text
        assert "traceback" not in invalid.text.casefold()

        oversized = client.put(
            "/api/settings",
            content=b"x" * 129,
            headers={"content-type": "application/json"},
        )
        assert oversized.status_code == 413
        assert oversized.json()["error"]["code"] == "body_too_large"
        assert oversized.headers["x-frame-options"] == "DENY"


def _seed_profile(settings, profile: ConnectionProfile) -> None:
    async def seed() -> None:
        cipher = CredentialCipher.from_settings(settings.data_dir, settings.secret_key)
        database = Database(settings.database_path, cipher)
        await database.initialize()
        await database.save_profile(profile)

    asyncio.run(seed())


def test_database_profile_overrides_environment_and_password_is_never_exposed(
    tmp_path: Path,
    settings_factory,
    monkeypatch,
) -> None:
    settings = settings_factory(
        tmp_path,
        sdex_base_url="https://environment-sdex",
        sdex_username="environment-user",
        sdex_password="environment-secret",
    )
    stored = ConnectionProfile(
        base_url="http://127.0.0.1:1",
        username="database-user",
        password="database-secret",
        verify_tls=False,
        timeout_seconds=5,
    )
    _seed_profile(settings, stored)
    captured_profiles = []

    class TestSDEXClient:
        def __init__(self, profile):
            captured_profiles.append(profile)

        async def get_system(self):
            return SYSTEM_FIXTURE

        async def close(self):
            return None

    monkeypatch.setattr("app.api.router.SDEXClient", TestSDEXClient)
    with TestClient(create_app(settings)) as client:
        status = client.get("/api/config/status")
        assert status.status_code == 200
        body = status.json()
        assert body["source"] == "database"
        assert body["base_url"] == "http://127.0.0.1:1"
        assert body["username"] == "database-user"
        assert body["password_configured"] is True
        assert "password" not in body
        assert "database-secret" not in status.text
        assert "environment-secret" not in status.text

        tested = client.post(
            "/api/config/test",
            json={
                "base_url": "http://127.0.0.1:1",
                "username": "database-user",
                "verify_tls": False,
                "timeout_seconds": 5,
            },
        )
        assert tested.status_code == 200
        assert captured_profiles[-1].password.get_secret_value() == "database-secret"
        mismatch = client.post(
            "/api/config/test",
            json={
                "base_url": "https://different-sdex",
                "username": "database-user",
                "verify_tls": True,
                "timeout_seconds": 5,
            },
        )
        assert mismatch.status_code == 400
        assert mismatch.json()["error"]["code"] == "invalid_configuration"
        assert "database-secret" not in mismatch.text


def test_config_update_reuses_password_only_for_same_target(
    tmp_path: Path,
    settings_factory,
    monkeypatch,
) -> None:
    settings = settings_factory(tmp_path)
    _seed_profile(
        settings,
        ConnectionProfile(
            base_url="http://127.0.0.1:1",
            username="reader",
            password="stored-secret",
        ),
    )
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        client.portal.call(runtime.scheduler.stop)

        async def no_reset():
            return None

        async def no_refresh(_trigger):
            return SimpleNamespace(correlation_id="test", reused=False)

        monkeypatch.setattr(runtime.discovery, "reset_client", no_reset)
        monkeypatch.setattr(runtime.discovery, "start_refresh", no_refresh)
        same = client.put(
            "/api/config",
            json={
                "base_url": "http://127.0.0.1:1",
                "username": "reader",
                "verify_tls": True,
                "timeout_seconds": 8,
            },
        )
        assert same.status_code == 200
        assert "stored-secret" not in same.text
        assert same.json()["password_configured"] is True

        different = client.put(
            "/api/config",
            json={
                "base_url": "https://other",
                "username": "reader",
                "verify_tls": True,
                "timeout_seconds": 8,
            },
        )
        assert different.status_code == 400


def test_health_degrades_instead_of_raising_on_database_error(
    tmp_path: Path,
    settings_factory,
    monkeypatch,
) -> None:
    settings = settings_factory(tmp_path, mock_mode=True)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime

        async def broken_ping():
            raise RuntimeError("injected sqlite failure")

        monkeypatch.setattr(runtime.database, "ping", broken_ping)
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "degraded"
        assert response.json()["database"] == "error"


def test_exact_api_path_never_falls_back_to_spa(
    tmp_path: Path,
    settings_factory,
) -> None:
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        "<!doctype html><title>ConnectMap SPA</title>",
        encoding="utf-8",
    )
    settings = settings_factory(tmp_path, static_dir=static_dir)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api")
        assert response.status_code == 404
        assert response.json() == {
            "error": {"code": "not_found", "message": "API route not found."}
        }
        assert "ConnectMap SPA" not in response.text
