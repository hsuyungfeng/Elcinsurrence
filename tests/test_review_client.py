from __future__ import annotations

import logging
from pathlib import Path
import pytest

from deploy.windows_agent.review_client import (
    DraftChangedError,
    ReviewClient,
    build_review_view_model,
)
from elc_audit_engine.api.app import create_app
from elc_audit_engine.case_store import CaseStore
from elc_audit_engine.case_store.soap_draft_states import (
    STATE_APPROVED,
    STATE_QUALITY_FAILED,
    STATE_VALIDATED,
)


def _sample_valid_soap():
    return {
        "s": "Patient presented with acute right lower quadrant abdominal pain for 6 hours.",
        "o": "Tenderness and rebound tenderness at McBurney point. Low grade fever 37.8C.",
        "a": "K35.80 Acute appendicitis, other and unspecified.",
        "p": "Urgent surgical consultation and abdominal sonography scheduled.",
    }


@pytest.fixture
def app_with_store(tmp_path, monkeypatch):
    db_file = tmp_path / "cases.sqlite3"
    audit_file = tmp_path / "audit" / "access.log"
    monkeypatch.setenv("CASES_DB_PATH", str(db_file))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_file))
    monkeypatch.setenv("DISABLE_AUTH", "0")

    from config import settings
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "CASES_DB_PATH", str(db_file))
    monkeypatch.setattr(settings, "AUDIT_LOG_PATH", str(audit_file))

    from elc_audit_engine import audit_log
    monkeypatch.setattr(audit_log, "AUDIT_LOG_PATH", str(audit_file))

    store = CaseStore(str(db_file))
    app = create_app(
        config={
            "TESTING": True,
            "DISABLE_AUTH": False,
            "ELC_API_KEYS": {
                "key_operator_12345": "physician_user",
            },
            "ELC_AGENT_KEYS": {
                "key_agent_67890": "agent_win",
            },
            "ELC_ALLOWED_HOSTS": ["localhost", "127.0.0.1", "testserver"],
            "DATA_DIR": str(tmp_path),
        },
        case_store=store,
        migrate_legacy=False,
    )
    return app, store


# --- Task 1: Server Pending Review Queue Endpoint Tests ---

def test_pending_review_only_validated(app_with_store):
    """Test 1: 操作者金鑰 GET pending-review 只回傳 state=validated 的草稿"""
    app, store = app_with_store
    client = app.test_client()
    headers = {"X-API-Key": "key_operator_12345"}

    # Seed drafts in various states
    store.create_soap_draft(case_id="P12345", soap=_sample_valid_soap(), state=STATE_VALIDATED)
    store.create_soap_draft(case_id="P67890", soap={"s": "X", "o": "X", "a": "X", "p": "X"}, state=STATE_QUALITY_FAILED)
    store.create_soap_draft(case_id="P99999", soap=_sample_valid_soap(), state=STATE_APPROVED)

    resp = client.get("/api/soap/drafts/pending-review", headers=headers)
    assert resp.status_code == 200
    drafts = resp.get_json()["drafts"]
    assert len(drafts) == 1
    assert drafts[0]["soap"]["s"] == _sample_valid_soap()["s"]


def test_pending_review_agent_key_rejected(app_with_store):
    """Test 2: Agent 金鑰 GET 回傳 403"""
    app, store = app_with_store
    client = app.test_client()
    headers = {"X-API-Key": "key_agent_67890"}

    resp = client.get("/api/soap/drafts/pending-review", headers=headers)
    assert resp.status_code == 403


def test_pending_review_fields_and_advisory_structure(app_with_store):
    """Test 3: 每筆含 draft_id, content_hash, version, soap, advisory 且 advisory read_only=True"""
    app, store = app_with_store
    client = app.test_client()
    headers = {"X-API-Key": "key_operator_12345"}

    comp_payload = {
        "icd10_suggestions": ["K35.80"],
        "order_suggestions": ["28016C"],
        "med_suggestions": ["Amoxicillin"],
    }
    store.create_soap_draft(
        case_id="P11111",
        soap=_sample_valid_soap(),
        state=STATE_VALIDATED,
        comparison=comp_payload,
    )

    resp = client.get("/api/soap/drafts/pending-review", headers=headers)
    assert resp.status_code == 200
    draft = resp.get_json()["drafts"][0]
    assert "draft_id" in draft
    assert "content_hash" in draft
    assert "version" in draft
    assert "soap" in draft
    assert draft["advisory"]["read_only"] is True
    assert draft["advisory"]["icd10_suggestions"] == ["K35.80"]


def test_pending_review_patient_ref_masked(app_with_store):
    """Test 4: patient_ref 僅以遮罩形式回傳（前 2 字加 ***）"""
    app, store = app_with_store
    client = app.test_client()
    headers = {"X-API-Key": "key_operator_12345"}

    store.create_soap_draft(case_id="PATIENT999", soap=_sample_valid_soap(), state=STATE_VALIDATED)
    resp = client.get("/api/soap/drafts/pending-review", headers=headers)
    draft = resp.get_json()["drafts"][0]
    assert draft["patient_ref"] == "PA***"
    assert "PATIENT999" not in str(resp.get_json())


def test_pending_review_limit_and_order(app_with_store):
    """Test 5: 清單依 created_at 升序，支援 limit 上限 50"""
    app, store = app_with_store
    client = app.test_client()
    headers = {"X-API-Key": "key_operator_12345"}

    for i in range(10):
        store.create_soap_draft(case_id=f"P_{i:02d}", soap=_sample_valid_soap(), state=STATE_VALIDATED)

    resp = client.get("/api/soap/drafts/pending-review?limit=3", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["count"] == 3


# --- Task 2: ReviewClient & View Model Tests ---

class MockHttpClient:
    def __init__(self):
        self.recorded_calls = []
        self.mock_responses = {}

    def request(self, base_url, method, path, json_body=None):
        self.recorded_calls.append({
            "base_url": base_url,
            "method": method,
            "path": path,
            "body": json_body,
        })
        key = (method, path.split("?")[0])
        return self.mock_responses.get(key, (200, {"status": "success"}))


def test_review_client_approve_request_format():
    """Test 1: approve 請求標頭使用操作者金鑰，body 含 content_hash，不含 reviewer_id"""
    http_mock = MockHttpClient()
    client = ReviewClient(base_url="http://localhost:5000", operator_key="valid_op_key", http=http_mock)

    client.approve("draft_123", "hash_abc")
    assert len(http_mock.recorded_calls) == 1
    call = http_mock.recorded_calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/api/soap/drafts/draft_123/approve"
    assert call["body"] == {"content_hash": "hash_abc"}
    assert "reviewer_id" not in call["body"]


def test_review_client_approve_409_raises_draft_changed_error():
    """Test 2: 伺服器回 409 時拋出 DraftChangedError，不重試"""
    http_mock = MockHttpClient()
    http_mock.mock_responses[("POST", "/api/soap/drafts/draft_123/approve")] = (
        409,
        {"status": "error", "message": "content_hash mismatch"},
    )
    client = ReviewClient(base_url="http://localhost:5000", operator_key="valid_op_key", http=http_mock)

    with pytest.raises(DraftChangedError):
        client.approve("draft_123", "old_hash")
    assert len(http_mock.recorded_calls) == 1


def test_review_client_edit_success():
    """Test 3: edit 請求 body 含 base_content_hash 與 soap 四欄，成功回傳新 version"""
    http_mock = MockHttpClient()
    http_mock.mock_responses[("POST", "/api/soap/drafts/draft_123/edit")] = (
        200,
        {"status": "success", "version": 2},
    )
    client = ReviewClient(base_url="http://localhost:5000", operator_key="valid_op_key", http=http_mock)

    soap = {"s": "new s", "o": "new o", "a": "new a", "p": "new p"}
    res = client.edit("draft_123", soap, base_content_hash="hash_v1")
    assert res.get("version") == 2
    assert http_mock.recorded_calls[0]["body"]["base_content_hash"] == "hash_v1"
    assert http_mock.recorded_calls[0]["body"]["soap"] == soap


def test_build_review_view_model_advisory_isolation():
    """Test 4: build_review_view_model 對 advisory 項目一律 writable=False、read_only=True"""
    draft_data = {
        "draft_id": "draft_test_vm",
        "version": 1,
        "content_hash": "hash_vm_123",
        "patient_ref": "P1***",
        "soap": {"s": "S val", "o": "O val", "a": "A val", "p": "P val"},
        "advisory": {
            "icd10_suggestions": ["K35.80"],
            "order_suggestions": ["28016C"],
            "med_suggestions": ["Amoxicillin"],
        },
    }
    vm = build_review_view_model(draft_data)
    # Check editors
    for k in ("s", "o", "a", "p"):
        assert vm["editors"][k]["writable"] is True
        assert vm["editors"][k]["read_only"] is False

    # Check advisory
    assert vm["advisory"]["read_only"] is True
    assert vm["advisory"]["icd10"]["writable"] is False
    assert vm["advisory"]["icd10"]["read_only"] is True
    assert vm["advisory"]["order"]["writable"] is False
    assert vm["advisory"]["med"]["writable"] is False


def test_review_client_log_safety(caplog):
    """Test 5: 任何日誌不含 SOAP 文字"""
    caplog.set_level(logging.DEBUG)
    http_mock = MockHttpClient()
    client = ReviewClient(base_url="http://localhost:5000", operator_key="valid_op_key", http=http_mock)

    secret_soap = "SECRET_DOCTOR_FINDING_XYZ"
    client.approve("draft_100", "content_hash_123")
    client.reject("draft_100", "TEST_REJECT")

    for record in caplog.records:
        assert secret_soap not in record.getMessage()


def test_review_client_empty_operator_key_rejected():
    """Test 6: ReviewClient 建構時若 operator_key 為空字串拋出 ValueError"""
    with pytest.raises(ValueError):
        ReviewClient(base_url="http://localhost:5000", operator_key="")
    with pytest.raises(ValueError):
        ReviewClient(base_url="http://localhost:5000", operator_key="   ")
