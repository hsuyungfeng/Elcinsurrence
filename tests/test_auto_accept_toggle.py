from __future__ import annotations

import json
from pathlib import Path
import pytest

from elc_audit_engine.api.app import create_app
from elc_audit_engine.case_store import CaseStore
from elc_audit_engine.case_store.soap_draft_states import (
    STATE_PUSHED,
    STATE_QUEUED,
    STATE_VALIDATED,
    STATE_QUALITY_FAILED,
)


@pytest.fixture
def app_with_db(tmp_path, monkeypatch):
    db_file = tmp_path / "cases.sqlite3"
    audit_log_path = tmp_path / "audit" / "access.log"
    monkeypatch.setenv("CASES_DB_PATH", str(db_file))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_log_path))
    monkeypatch.setenv("DISABLE_AUTH", "0")

    from config import settings
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "CASES_DB_PATH", str(db_file))
    monkeypatch.setattr(settings, "AUDIT_LOG_PATH", str(audit_log_path))

    from elc_audit_engine import audit_log
    monkeypatch.setattr(audit_log, "AUDIT_LOG_PATH", str(audit_log_path))

    store = CaseStore(str(db_file))
    app = create_app(
        config={
            "TESTING": True,
            "DISABLE_AUTH": False,
            "ELC_API_KEYS": {
                "valid_client_key_12345": "caller_client",
                "doc_a_key_12345678": "doc_a",
                "doc_b_key_12345678": "doc_b",
            },
            "ELC_AGENT_KEYS": {
                "valid_agent_key_67890": "agent_win",
            },
            "ELC_ALLOWED_HOSTS": ["localhost", "127.0.0.1", "testserver"],
            "DATA_DIR": str(tmp_path),
        },
        case_store=store,
        migrate_legacy=False,
    )
    return app


# --- Task 1: Auto-accept settings endpoints & audit tests ---

def test_auto_accept_default_false(app_with_db):
    """Test 1: 全新資料庫的 GET /api/soap/settings/auto-accept 回傳 enabled=false"""
    client = app_with_db.test_client()
    resp = client.get("/api/soap/settings/auto-accept", headers={"X-API-Key": "valid_client_key_12345"})
    assert resp.status_code == 200
    assert resp.get_json()["enabled"] is False


def test_auto_accept_toggle_and_audit(app_with_db):
    """Test 2 & 3: PUT enabled=true 成功，GET 為 true，審計包含完整變更且不含 SOAP 文字"""
    client = app_with_db.test_client()
    headers = {"X-API-Key": "valid_client_key_12345"}

    put_resp = client.put(
        "/api/soap/settings/auto-accept",
        json={"enabled": True, "reason_code": "CLINIC_POLICY"},
        headers=headers,
    )
    assert put_resp.status_code == 200
    assert put_resp.get_json()["enabled"] is True

    get_resp = client.get("/api/soap/settings/auto-accept", headers=headers)
    assert get_resp.get_json()["enabled"] is True

    # Check access.log
    audit_file = Path(app_with_db.config.get("DATA_DIR", "data")) / "audit" / "access.log"
    assert audit_file.exists()
    lines = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").strip().split("\n")]
    toggle_events = [l for l in lines if l.get("detail", {}).get("action") == "soap_auto_accept_toggle"]
    assert len(toggle_events) >= 1
    ev = toggle_events[-1]["detail"]
    assert ev["old"] is False
    assert ev["new"] is True
    assert ev["changed"] is True
    assert ev["reason_code"] == "CLINIC_POLICY"
    assert ev["caller"] == "caller_client"

    # Test 3: Ensure no SOAP text in audit detail
    raw_text = json.dumps(ev)
    assert "subjective" not in raw_text.lower()
    assert "objective" not in raw_text.lower()


def test_auto_accept_agent_key_forbidden(app_with_db):
    """Test 4: Agent 金鑰 PUT 回傳 403"""
    client = app_with_db.test_client()
    resp = client.put(
        "/api/soap/settings/auto-accept",
        json={"enabled": True, "reason_code": "CLINIC_POLICY"},
        headers={"X-API-Key": "valid_agent_key_67890"},
    )
    assert resp.status_code == 403


def test_auto_accept_admin_callers_restriction(app_with_db, monkeypatch):
    """Test 5: 設定 ELC_SOAP_ADMIN_CALLERS 為 'doc_a' 時，caller 'doc_b' 的 PUT 回傳 403"""
    monkeypatch.setenv("ELC_SOAP_ADMIN_CALLERS", "doc_a")
    client = app_with_db.test_client()

    # doc_b is forbidden
    resp_b = client.put(
        "/api/soap/settings/auto-accept",
        json={"enabled": True, "reason_code": "CLINIC_POLICY"},
        headers={"X-API-Key": "doc_b_key_12345678"},
    )
    assert resp_b.status_code == 403

    # doc_a is allowed
    resp_a = client.put(
        "/api/soap/settings/auto-accept",
        json={"enabled": True, "reason_code": "CLINIC_POLICY"},
        headers={"X-API-Key": "doc_a_key_12345678"},
    )
    assert resp_a.status_code == 200


def test_auto_accept_repeated_put_changed_false(app_with_db):
    """Test 6: 相同值重複 PUT 仍寫入審計列，標註 changed=false"""
    client = app_with_db.test_client()
    headers = {"X-API-Key": "valid_client_key_12345"}

    client.put("/api/soap/settings/auto-accept", json={"enabled": True, "reason_code": "DEFAULT"}, headers=headers)
    client.put("/api/soap/settings/auto-accept", json={"enabled": True, "reason_code": "DEFAULT"}, headers=headers)

    audit_file = Path(app_with_db.config.get("DATA_DIR", "data")) / "audit" / "access.log"
    lines = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").strip().split("\n")]
    toggle_events = [l for l in lines if l.get("detail", {}).get("action") == "soap_auto_accept_toggle"]
    assert len(toggle_events) >= 2
    assert toggle_events[-1]["detail"]["changed"] is False


def test_auto_accept_invalid_reason_code_400(app_with_db):
    """Test 7: reason_code 不在允許清單時回傳 400"""
    client = app_with_db.test_client()
    resp = client.put(
        "/api/soap/settings/auto-accept",
        json={"enabled": True, "reason_code": "invalid_reason"},
        headers={"X-API-Key": "valid_client_key_12345"},
    )
    assert resp.status_code == 400


# --- Task 2: Auto-accept branch on draft creation ---

def _valid_soap():
    return {
        "s": "Patient presented with acute right lower quadrant abdominal pain for 6 hours.",
        "o": "Tenderness and rebound tenderness at McBurney point. Low grade fever 37.8C.",
        "a": "K35.80 Acute appendicitis, other and unspecified.",
        "p": "Urgent surgical consultation and abdominal sonography scheduled.",
    }


def _invalid_soap():
    return {
        "s": "",  # Empty -> fails quality check
        "o": "Normal",
        "a": "Cold",
        "p": "Rest",
    }


def test_auto_accept_enabled_quality_pass_auto_queues(app_with_db):
    """Test 1: 開關 ON、草稿品質通過，建立草稿後 state 為 queued，且 bridge_queue 出現 HIS_PUSH 任務"""
    client = app_with_db.test_client()
    headers = {"X-API-Key": "valid_client_key_12345"}

    # Turn ON auto-accept
    client.put("/api/soap/settings/auto-accept", json={"enabled": True, "reason_code": "DEFAULT"}, headers=headers)

    resp = client.post(
        "/api/soap/drafts",
        json={"case_id": "CASE-AUTO-01", "soap": _valid_soap()},
        headers=headers,
    )
    assert resp.status_code == 201
    draft_data = resp.get_json()["draft"]
    assert draft_data["state"] == STATE_QUEUED

    # Verify job queued in bridge
    bridge_resp = client.get("/api/bridge/jobs/pending?sTypeCode=HIS_PUSH", headers={"X-API-Key": "valid_agent_key_67890"})
    assert bridge_resp.status_code == 200
    jobs = bridge_resp.get_json()["jobs"]
    matching = [j for j in jobs if j.get("extra_payload", {}).get("draft_id") == draft_data["draft_id"]]
    assert len(matching) == 1
    assert matching[0]["extra_payload"]["content_hash"] == draft_data["content_hash"]


def test_auto_accept_enabled_quality_failed_stays_quality_failed(app_with_db):
    """Test 2: 開關 ON、品質未通過，state 為 quality_failed，無 HIS_PUSH 任務"""
    client = app_with_db.test_client()
    headers = {"X-API-Key": "valid_client_key_12345"}

    client.put("/api/soap/settings/auto-accept", json={"enabled": True, "reason_code": "DEFAULT"}, headers=headers)

    resp = client.post(
        "/api/soap/drafts",
        json={"case_id": "CASE-AUTO-FAIL", "soap": _invalid_soap()},
        headers=headers,
    )
    assert resp.status_code == 201
    draft_data = resp.get_json()["draft"]
    assert draft_data["state"] == STATE_QUALITY_FAILED

    # Verify NO job queued in bridge
    bridge_resp = client.get("/api/bridge/jobs/pending?sTypeCode=HIS_PUSH", headers={"X-API-Key": "valid_agent_key_67890"})
    jobs = bridge_resp.get_json()["jobs"]
    matching = [j for j in jobs if j.get("extra_payload", {}).get("draft_id") == draft_data["draft_id"]]
    assert len(matching) == 0


def test_auto_accept_disabled_quality_pass_stays_validated(app_with_db):
    """Test 3: 開關 OFF、品質通過，state 為 validated，無 HIS_PUSH 任務"""
    client = app_with_db.test_client()
    headers = {"X-API-Key": "valid_client_key_12345"}

    # Default is OFF
    resp = client.post(
        "/api/soap/drafts",
        json={"case_id": "CASE-MANUAL-01", "soap": _valid_soap()},
        headers=headers,
    )
    assert resp.status_code == 201
    draft_data = resp.get_json()["draft"]
    assert draft_data["state"] == STATE_VALIDATED

    # Verify NO job queued in bridge
    bridge_resp = client.get("/api/bridge/jobs/pending?sTypeCode=HIS_PUSH", headers={"X-API-Key": "valid_agent_key_67890"})
    jobs = bridge_resp.get_json()["jobs"]
    matching = [j for j in jobs if j.get("extra_payload", {}).get("draft_id") == draft_data["draft_id"]]
    assert len(matching) == 0


def test_auto_accept_audit_format_and_reviewer_id(app_with_db):
    """Test 4: 自動核准寫入 soap_auto_accept_approve 審計，reviewer_id 為 'auto-accept:<caller>'，不含 SOAP 文字"""
    client = app_with_db.test_client()
    headers = {"X-API-Key": "valid_client_key_12345"}

    client.put("/api/soap/settings/auto-accept", json={"enabled": True, "reason_code": "DEFAULT"}, headers=headers)
    client.post("/api/soap/drafts", json={"case_id": "CASE-AUDIT-01", "soap": _valid_soap()}, headers=headers)

    audit_file = Path(app_with_db.config.get("DATA_DIR", "data")) / "audit" / "access.log"
    lines = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").strip().split("\n")]
    approve_events = [l for l in lines if l.get("detail", {}).get("action") == "soap_auto_accept_approve"]
    assert len(approve_events) >= 1
    ev = approve_events[-1]
    assert ev["caller_id"] == "auto-accept:caller_client"
    assert "draft_id" in ev["detail"]
    assert "content_hash" in ev["detail"]


def test_auto_accept_tampered_hash_rejection(app_with_db):
    """Test 5: 自動核准後內容若被竄改（hash 不符），HIS_PUSH 不會因舊核准而執行"""
    from elc_audit_engine.case_store.soap_draft_states import compute_soap_content_hash
    client = app_with_db.test_client()
    headers = {"X-API-Key": "valid_client_key_12345"}

    client.put("/api/soap/settings/auto-accept", json={"enabled": True, "reason_code": "DEFAULT"}, headers=headers)
    resp = client.post("/api/soap/drafts", json={"case_id": "CASE-TAMPER", "soap": _valid_soap()}, headers=headers)
    draft_id = resp.get_json()["draft"]["draft_id"]

    # Simulating DB tamper
    from elc_audit_engine.api.context import case_store
    with app_with_db.app_context():
        store = case_store()
        conn = store._connect()
        with conn:
            conn.execute("UPDATE soap_drafts SET soap_json = ? WHERE draft_id = ?", ('{"s":"tampered"}', draft_id))
        conn.close()

        tampered_draft = store.get_soap_draft(draft_id)
        actual_tampered_hash = compute_soap_content_hash(tampered_draft.soap)
        # The stored content_hash no longer matches the content of soap_json
        assert actual_tampered_hash != tampered_draft.content_hash


def test_auto_accept_already_pushed_idempotency(app_with_db):
    """Test 6: 同一 case_id 與 content_hash 已 pushed 時，自動路徑不重複排程"""
    from elc_audit_engine.api.context import case_store
    from elc_audit_engine.case_store.soap_draft_states import compute_soap_content_hash
    client = app_with_db.test_client()
    headers = {"X-API-Key": "valid_client_key_12345"}

    soap = _valid_soap()
    chash = compute_soap_content_hash(soap)
    with app_with_db.app_context():
        store = case_store()
        # Seed an already pushed draft
        store.create_soap_draft(case_id="CASE-PUSHED-IDEMP", soap=soap, state=STATE_PUSHED)

    # Now enable auto-accept and post another draft with same case_id and soap content
    client.put("/api/soap/settings/auto-accept", json={"enabled": True, "reason_code": "DEFAULT"}, headers=headers)
    resp = client.post("/api/soap/drafts", json={"case_id": "CASE-PUSHED-IDEMP", "soap": soap}, headers=headers)
    assert resp.status_code == 201

    # Should not queue new HIS_PUSH job for this case
    bridge_resp = client.get("/api/bridge/jobs/pending?sTypeCode=HIS_PUSH", headers={"X-API-Key": "valid_agent_key_67890"})
    jobs = bridge_resp.get_json()["jobs"]
    matching = [j for j in jobs if j.get("extra_payload", {}).get("case_id") == "CASE-PUSHED-IDEMP"]
    assert len(matching) == 0


# --- Task 3: Permission & Audit Integrity Tests ---

def test_auto_vs_manual_approve_action_names(app_with_db):
    """Test 1: 自動核准與手動核准的審計列 action 名稱不同且可區分"""
    client = app_with_db.test_client()
    headers = {"X-API-Key": "valid_client_key_12345"}

    # 1. Manual approve
    resp1 = client.post("/api/soap/drafts", json={"case_id": "CASE-MANUAL-ACT", "soap": _valid_soap()}, headers=headers)
    draft1 = resp1.get_json()["draft"]
    client.post(
        f"/api/soap/drafts/{draft1['draft_id']}/approve",
        json={"content_hash": draft1["content_hash"]},
        headers=headers,
    )

    # 2. Auto approve
    client.put("/api/soap/settings/auto-accept", json={"enabled": True, "reason_code": "DEFAULT"}, headers=headers)
    client.post("/api/soap/drafts", json={"case_id": "CASE-AUTO-ACT", "soap": _valid_soap()}, headers=headers)

    audit_file = Path(app_with_db.config.get("DATA_DIR", "data")) / "audit" / "access.log"
    lines = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").strip().split("\n")]
    actions = [l.get("detail", {}).get("action") for l in lines]
    assert "soap_review_approve" in actions
    assert "soap_auto_accept_approve" in actions


def test_toggle_off_after_queued_preserves_queued(app_with_db):
    """Test 2: 開關在排入 queued 後被切換為 OFF，已排程者不回收"""
    client = app_with_db.test_client()
    headers = {"X-API-Key": "valid_client_key_12345"}

    client.put("/api/soap/settings/auto-accept", json={"enabled": True, "reason_code": "DEFAULT"}, headers=headers)
    resp = client.post("/api/soap/drafts", json={"case_id": "CASE-OFF-AFTER", "soap": _valid_soap()}, headers=headers)
    draft_id = resp.get_json()["draft"]["draft_id"]

    # Toggle turned OFF
    client.put("/api/soap/settings/auto-accept", json={"enabled": False, "reason_code": "DEFAULT"}, headers=headers)

    # Queued job remains in bridge_queue
    bridge_resp = client.get("/api/bridge/jobs/pending?sTypeCode=HIS_PUSH", headers={"X-API-Key": "valid_agent_key_67890"})
    jobs = bridge_resp.get_json()["jobs"]
    matching = [j for j in jobs if j.get("extra_payload", {}).get("draft_id") == draft_id]
    assert len(matching) == 1


def test_toggle_audit_history_sequence(app_with_db):
    """Test 3: 審計表可依 action=soap_auto_accept_toggle 查詢到完整的切換歷程（ON->OFF->ON）"""
    client = app_with_db.test_client()
    headers = {"X-API-Key": "valid_client_key_12345"}

    client.put("/api/soap/settings/auto-accept", json={"enabled": True, "reason_code": "DEFAULT"}, headers=headers)
    client.put("/api/soap/settings/auto-accept", json={"enabled": False, "reason_code": "CLINIC_POLICY"}, headers=headers)
    client.put("/api/soap/settings/auto-accept", json={"enabled": True, "reason_code": "DEFAULT"}, headers=headers)

    audit_file = Path(app_with_db.config.get("DATA_DIR", "data")) / "audit" / "access.log"
    lines = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").strip().split("\n")]
    toggle_events = [l for l in lines if l.get("detail", {}).get("action") == "soap_auto_accept_toggle"]
    assert len(toggle_events) == 3
    assert [ev["detail"]["new"] for ev in toggle_events] == [True, False, True]
