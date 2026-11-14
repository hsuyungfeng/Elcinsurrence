"""Tests for C4: Health endpoint returns facility code, name and version (Phase 32 Plan 32-07)."""

import pytest


@pytest.fixture
def app(make_api_app):
    return make_api_app()


@pytest.fixture
def client(app):
    return app.test_client()


def test_health_returns_facility_and_version(client, monkeypatch):
    monkeypatch.setattr(
        "config.settings.load_facility_config",
        lambda: {
            "code": "3503250461",
            "name": "安健診所",
            "address": "台北市中山區某路1號",
            "physician_name": "王醫師",
        },
    )

    res = client.get("/api/health", environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert res.status_code == 200
    data = res.get_json()

    assert data["status"] == "ok"
    assert data["service"] == "elc-audit-engine"
    assert data["facility_code"] == "3503250461"
    assert data["facility_name"] == "安健診所"
    assert "version" in data and data["version"]

    # PHI and sensitive admin data check
    assert "address" not in data
    assert "physician_name" not in data


def test_health_load_facility_fails_returns_empty_strings(client, monkeypatch):
    def _raise():
        raise RuntimeError("DB error")

    monkeypatch.setattr("config.settings.load_facility_config", _raise)

    res = client.get("/api/health", environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert res.status_code == 200
    data = res.get_json()

    assert data["status"] == "ok"
    assert data["service"] == "elc-audit-engine"
    assert data["facility_code"] == ""
    assert data["facility_name"] == ""


def test_health_untrusted_source_returns_403(client):
    res = client.get("/api/health", environ_base={"REMOTE_ADDR": "8.8.8.8"})
    assert res.status_code == 403
