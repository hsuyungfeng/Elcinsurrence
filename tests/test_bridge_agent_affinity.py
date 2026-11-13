"""Phase 31 Plan 04: HIS_PUSH 任務 machine_id 綁定與隔離測試 (D-31-37, D-31-16, D-31-14)."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from elc_audit_engine.api.routes.soap_review import approve_and_enqueue
from elc_audit_engine.bridge_queue import get_job
from elc_audit_engine.case_store.soap_draft_states import STATE_PUSHED, STATE_VALIDATED
from deploy.windows_agent.agent import WindowsAgent
from deploy.windows_agent.review_client import ReviewClient
from tests.phase31_support import phase31_app, phase31_client  # noqa: F401

KEY = {"X-API-Key": "valid-key-123"}
AGENT_KEY = {"X-API-Key": "valid-key-123"}  # 在 phase31_app 中 valid-key-123 為一般授權

SOAP_OK = {
    "s": "Patient presents with sore throat and fever.",
    "o": "T 38.0 C, throat red, tonsils mildly enlarged.",
    "a": "Acute tonsillitis, J03.9.",
    "p": "Rest, oral hydration, symptomatic medication.",
}


def _create_bound_draft(store, case_id: str, machine_id: str | None = None):
    store.create(case_id=case_id, kind="monthly", payload={"patient": "test"})
    draft = store.create_soap_draft(
        case_id=case_id,
        soap=SOAP_OK,
        state=STATE_VALIDATED,
    )
    draft, job = approve_and_enqueue(
        store,
        draft_id=draft.draft_id,
        reviewer_id="dr_test",
        machine_id=machine_id,
    )
    return draft, job


def test_pending_filter_by_machine_id(phase31_app, phase31_client):
    """Test 1: 帶 machine_id=m1 輪詢時，只會取得 m1 的任務，不會拿到 m2 的任務。"""
    store = phase31_app.case_store
    _, job_m1 = _create_bound_draft(store, "C-AFF-01", machine_id="m1")
    _, job_m2 = _create_bound_draft(store, "C-AFF-02", machine_id="m2")

    res = phase31_client.get(
        "/api/bridge/jobs/pending?sTypeCode=HIS_PUSH&machine_id=m1",
        headers=KEY,
    )
    assert res.status_code == 200
    data = res.get_json()
    job_ids = [j["job_id"] for j in data.get("jobs", [])]

    assert job_m1["job_id"] in job_ids
    assert job_m2["job_id"] not in job_ids


def test_pending_without_machine_id_returns_only_unbound(phase31_app, phase31_client):
    """Test 2: 未帶 machine_id 的輪詢只會回傳未綁定任務，不含 m1、m2。"""
    store = phase31_app.case_store
    _, job_m1 = _create_bound_draft(store, "C-AFF-03", machine_id="m1")
    _, job_m2 = _create_bound_draft(store, "C-AFF-04", machine_id="m2")
    _, job_unbound = _create_bound_draft(store, "C-AFF-05", machine_id=None)

    res = phase31_client.get(
        "/api/bridge/jobs/pending?sTypeCode=HIS_PUSH",
        headers=KEY,
    )
    assert res.status_code == 200
    data = res.get_json()
    job_ids = [j["job_id"] for j in data.get("jobs", [])]

    assert job_unbound["job_id"] in job_ids
    assert job_m1["job_id"] not in job_ids
    assert job_m2["job_id"] not in job_ids


def test_pending_with_machine_id_includes_unbound(phase31_app, phase31_client):
    """Test 3: 帶 machine_id=m1 的輪詢會同時包含 m1 任務與未綁定任務（相容性）。"""
    store = phase31_app.case_store
    _, job_m1 = _create_bound_draft(store, "C-AFF-06", machine_id="m1")
    _, job_unbound = _create_bound_draft(store, "C-AFF-07", machine_id=None)

    res = phase31_client.get(
        "/api/bridge/jobs/pending?sTypeCode=HIS_PUSH&machine_id=m1",
        headers=KEY,
    )
    assert res.status_code == 200
    data = res.get_json()
    job_ids = [j["job_id"] for j in data.get("jobs", [])]

    assert job_m1["job_id"] in job_ids
    assert job_unbound["job_id"] in job_ids


def test_wrong_machine_id_claim_rejected(phase31_app, phase31_client):
    """Test 4: 以 machine_id=m2 認領 m1 任務時回傳 409，狀態仍保持 PENDING。"""
    store = phase31_app.case_store
    _, job_m1 = _create_bound_draft(store, "C-AFF-08", machine_id="m1")
    job_id = job_m1["job_id"]

    res = phase31_client.post(
        f"/api/bridge/jobs/{job_id}/status",
        json={"status": "SENDING", "expected_status": "PENDING", "machine_id": "m2"},
        headers=KEY,
    )
    assert res.status_code == 409

    job_now = get_job(store, job_id)
    assert job_now["status"] == "PENDING"


def test_matching_machine_id_claim_and_report_success(phase31_app, phase31_client):
    """Test 5: 以 machine_id=m1 認領並回報 SUCCESS，任務成功且草稿轉 pushed。"""
    store = phase31_app.case_store
    draft, job_m1 = _create_bound_draft(store, "C-AFF-09", machine_id="m1")
    job_id = job_m1["job_id"]

    # 認領
    res1 = phase31_client.post(
        f"/api/bridge/jobs/{job_id}/status",
        json={"status": "SENDING", "expected_status": "PENDING", "machine_id": "m1"},
        headers=KEY,
    )
    assert res1.status_code == 200

    # 回報 SUCCESS
    res2 = phase31_client.post(
        f"/api/bridge/jobs/{job_id}/status",
        json={"status": "SUCCESS", "expected_status": "SENDING", "machine_id": "m1"},
        headers=KEY,
    )
    assert res2.status_code == 200

    job_now = get_job(store, job_id)
    assert job_now["status"] == "SUCCESS"

    d_now = store.get_soap_draft(draft.draft_id)
    assert d_now.state == STATE_PUSHED


def test_windows_agent_sends_machine_id():
    """Test 6: WindowsAgent 輪詢路徑與 status 回報 body 均包含 machine_id。"""
    requests_log = []

    class MockHttpClient:
        def request(self, method, path, json_data=None):
            requests_log.append((method, path, json_data))
            if "pending" in path:
                return 200, {"jobs": []}
            return 200, {}

    mock_client = MockHttpClient()
    cfg = MagicMock()
    cfg.server_url = "http://localhost:5000"
    cfg.agent_key = "test-key"
    cfg.vendor_key = "mock"

    agent = WindowsAgent(
        config=cfg,
        http_client=mock_client,
        machine_id="m-test-1",
        allow_uncalibrated=True,
    )

    # 1. 輪詢
    agent.poll_pending_jobs()
    assert len(requests_log) == 1
    method, path, body = requests_log[0]
    assert method == "GET"
    assert "machine_id=m-test-1" in path

    # 2. 認領
    agent.claim_job("job-123")
    assert len(requests_log) == 2
    method, path, body = requests_log[1]
    assert method == "POST"
    assert body.get("machine_id") == "m-test-1"

    # 3. 回報
    agent.report_job_status("job-123", "SUCCESS")
    assert len(requests_log) == 3
    method, path, body = requests_log[2]
    assert method == "POST"
    assert body.get("machine_id") == "m-test-1"


def test_review_client_approve_sends_machine_id():
    """Test 7: ReviewClient.approve 請求 body 含 machine_id。"""
    requests_log = []

    class MockReviewHttp:
        def request(self, base_url, method, path, json_body=None):
            requests_log.append((method, path, json_body))
            return 200, {"status": "success"}

    mock_http = MockReviewHttp()
    client = ReviewClient(
        base_url="http://localhost:5000",
        operator_key="test-op-key",
        http=mock_http,
        machine_id="m-review-1",
    )

    client.approve("d-123", "content-hash-abc")
    assert len(requests_log) == 1
    method, path, body = requests_log[0]
    assert method == "POST"
    assert path == "/api/soap/drafts/d-123/approve"
    assert body.get("machine_id") == "m-review-1"
    assert body.get("content_hash") == "content-hash-abc"


def test_uncalibrated_agent_blocks_writeback():
    """Test 8: 未校正 profile 的 WindowsAgent 依然拒絕真實寫入。"""
    from deploy.windows_agent.agent import UncalibratedVendorProfileError

    cfg = MagicMock()
    cfg.server_url = "http://localhost:5000"
    cfg.agent_key = "test-key"
    cfg.vendor_key = "uncalibrated_vendor"

    # 未標記校正且未提供 calibration_store，啟動即拋錯拒絕
    with pytest.raises(UncalibratedVendorProfileError):
        WindowsAgent(
            config=cfg,
            http_client=MagicMock(),
            machine_id="m-1",
            allow_uncalibrated=False,
        )
