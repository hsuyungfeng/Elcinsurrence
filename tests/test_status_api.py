"""Wave 0 contract and integration tests for system status API (Phase 32 Plan 32-08, D3, D5, D6)."""

import pytest


@pytest.fixture
def app(make_api_app):
    return make_api_app()


@pytest.fixture
def client(app):
    return app.test_client()


def test_status_api_structure_and_probe_injection(client, app):
    # Remote loopback client
    environ = {"REMOTE_ADDR": "127.0.0.1"}

    # Inject mock LLM probe that reports failure
    app.config["ELC_LLM_PROBE"] = lambda: False

    resp = client.get("/api/status", environ_base=environ)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "overall" in data
    assert "checks" in data
    assert data["overall"] in {"green", "yellow", "red", "unknown"}

    checks = {c["key"]: c for c in data["checks"]}
    required_keys = {"engine", "llm", "disk", "database", "backup", "clients"}
    assert required_keys.issubset(set(checks.keys()))

    llm_check = checks["llm"]
    assert llm_check["color"] == "red"
    assert "AI" in llm_check["message"] or "暫停" in llm_check["message"]

    # /api/health/deep returns 503 when red
    deep_resp = client.get("/api/health/deep", environ_base=environ)
    assert deep_resp.status_code == 503
    deep_data = deep_resp.get_json()
    assert deep_data["overall"] == data["overall"]
    assert deep_data["status"] == data["status"]
    assert len(deep_data["checks"]) == len(data["checks"])
    assert {c["key"]: c["color"] for c in deep_data["checks"]} == {c["key"]: c["color"] for c in data["checks"]}

    # /api/health remains 200 (liveness not broken by LLM failure)
    health_resp = client.get("/api/health", environ_base=environ)
    assert health_resp.status_code == 200

    # No PHI leak
    text_data = resp.get_data(as_text=True).lower()
    assert "patient" not in text_data
    assert "soap" not in text_data


def test_status_page_html_served(client):
    environ = {"REMOTE_ADDR": "127.0.0.1"}
    resp = client.get("/status", environ_base=environ)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["Content-Type"]
    assert "系統運作狀態" in resp.get_data(as_text=True)
