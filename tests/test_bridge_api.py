"""Phase 21-03 測試：地端 Local Agent 橋接 API（建立、拉取佇列、狀態回報與更新閉環）。"""

from __future__ import annotations

import pytest

KEY = {"X-API-Key": "valid-key-123"}


@pytest.fixture
def api(make_api_app):
    return make_api_app()


@pytest.fixture
def client(api):
    with api.test_client() as c:
        yield c


def _create(client, s_type_code="15", target_id="MONTHLY-202307"):
    res = client.post(
        "/api/bridge/jobs",
        json={"s_type_code": s_type_code, "target_id": target_id},
        headers=KEY,
    )
    assert res.status_code == 201
    return res.get_json()["job"]


def test_create_job_is_pending_with_download_path(client):
    job = _create(client, "15")
    assert job["status"] == "PENDING"
    assert job["s_type_code"] == "15"
    assert job["download_path"] == "/api/sampling/export-batch-xml"
    assert job["local_id"] is None and job["nhi_id"] is None and job["nhi_status"] is None
    assert len(job["job_id"]) == 32


def test_download_path_follows_job_type(client):
    assert _create(client, "00", "A123456789-2307")["download_path"] == (
        "/api/sampling/cases/A123456789-2307/export-package"
    )
    assert _create(client, "07", "APL")["download_path"] == "/api/appeal/export-batch-xml"
    assert _create(client, "09", "APL")["download_path"] == "/api/appeal/export-batch-xml"


@pytest.mark.parametrize("code", ["99", "", "1"])
def test_unknown_s_type_code_is_rejected(client, code):
    res = client.post("/api/bridge/jobs", json={"s_type_code": code, "target_id": "X"}, headers=KEY)
    assert res.status_code == 422


def test_empty_target_is_rejected(client):
    res = client.post("/api/bridge/jobs", json={"s_type_code": "15", "target_id": "  "}, headers=KEY)
    assert res.status_code == 422


def test_non_json_body_is_rejected(client):
    res = client.post("/api/bridge/jobs", data="not json", headers={**KEY, "Content-Type": "text/plain"})
    assert res.status_code == 400


def test_pending_queue_lists_pending_and_filters_by_code(client):
    _create(client, "15", "MONTHLY-202307")
    _create(client, "07", "APL-1")
    all_jobs = client.get("/api/bridge/jobs/pending", headers=KEY).get_json()
    assert all_jobs["count"] == 2
    only_15 = client.get("/api/bridge/jobs/pending?sTypeCode=15", headers=KEY).get_json()
    assert [job["s_type_code"] for job in only_15["jobs"]] == ["15"]


def test_pending_rejects_unknown_filter(client):
    res = client.get("/api/bridge/jobs/pending?sTypeCode=XX", headers=KEY)
    assert res.status_code == 422


def test_full_status_loop_updates_identifiers_and_leaves_queue(client):
    job = _create(client, "07", "APL-1")
    job_id = job["job_id"]

    res = client.post(f"/api/bridge/jobs/{job_id}/status", json={"status": "SENDING"}, headers=KEY)
    assert res.status_code == 200
    assert res.get_json()["job"]["status"] == "SENDING"
    assert client.get("/api/bridge/jobs/pending", headers=KEY).get_json()["count"] == 0

    res = client.post(
        f"/api/bridge/jobs/{job_id}/status",
        json={"status": "SUCCESS", "sLocal_ID": "LOC-9", "sNHI_ID": "NHI-42", "NHI_Query": "A99"},
        headers=KEY,
    )
    assert res.status_code == 200
    updated = res.get_json()["job"]
    assert updated["status"] == "SUCCESS"
    assert updated["local_id"] == "LOC-9"
    assert updated["nhi_id"] == "NHI-42"
    assert updated["nhi_status"] == "A99"

    fetched = client.get(f"/api/bridge/jobs/{job_id}", headers=KEY).get_json()["job"]
    assert fetched["status"] == "SUCCESS"


def test_failed_path_records_nhi_query_status(client):
    job_id = _create(client, "15")["job_id"]
    client.post(f"/api/bridge/jobs/{job_id}/status", json={"status": "SENDING"}, headers=KEY)
    res = client.post(
        f"/api/bridge/jobs/{job_id}/status",
        json={"status": "FAILED", "NHI_Query": "A12"},
        headers=KEY,
    )
    assert res.status_code == 200
    assert res.get_json()["job"]["nhi_status"] == "A12"


def test_illegal_transition_is_conflict(client):
    job_id = _create(client, "15")["job_id"]
    res = client.post(f"/api/bridge/jobs/{job_id}/status", json={"status": "SUCCESS"}, headers=KEY)
    assert res.status_code == 409


def test_terminal_state_cannot_be_reopened(client):
    job_id = _create(client, "15")["job_id"]
    client.post(f"/api/bridge/jobs/{job_id}/status", json={"status": "SENDING"}, headers=KEY)
    client.post(f"/api/bridge/jobs/{job_id}/status", json={"status": "SUCCESS"}, headers=KEY)
    res = client.post(f"/api/bridge/jobs/{job_id}/status", json={"status": "SENDING"}, headers=KEY)
    assert res.status_code == 409


@pytest.mark.parametrize("nhi_query", ["A1", "a12", "AA12", "A123"])
def test_malformed_nhi_query_is_rejected(client, nhi_query):
    job_id = _create(client, "15")["job_id"]
    client.post(f"/api/bridge/jobs/{job_id}/status", json={"status": "SENDING"}, headers=KEY)
    res = client.post(
        f"/api/bridge/jobs/{job_id}/status",
        json={"status": "SUCCESS", "NHI_Query": nhi_query},
        headers=KEY,
    )
    assert res.status_code == 422


def test_unknown_job_is_404(client):
    assert client.get("/api/bridge/jobs/does-not-exist", headers=KEY).status_code == 404
    res = client.post("/api/bridge/jobs/does-not-exist/status", json={"status": "SENDING"}, headers=KEY)
    assert res.status_code == 404


def test_bridge_endpoints_require_api_key(client):
    assert client.get("/api/bridge/jobs/pending").status_code in (401, 403)
    assert client.post("/api/bridge/jobs", json={"s_type_code": "15", "target_id": "X"}).status_code in (401, 403)


def test_non_bridge_case_is_not_exposed_as_job(client, api):
    store = api.extensions["elc"].case_store
    store.create(case_id="SAMP-NOT-BRIDGE", kind="sampling", payload={"x": 1}, actor="test")
    assert client.get("/api/bridge/jobs/SAMP-NOT-BRIDGE", headers=KEY).status_code == 404
