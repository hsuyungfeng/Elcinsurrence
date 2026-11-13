"""Phase 31: 循環草稿醫師確認與排入 HIS 測試 (契約 §3, D-31-08, D-31-25, D-31-26, D-31-37, D-31-38)."""

from __future__ import annotations

import json
from unittest.mock import patch
import uuid


from elc_audit_engine.cycles.store import create_cycle, transition_cycle
from tests.phase31_support import phase31_app, phase31_client  # noqa: F401

SOAP_OK = {
    "s": "Patient presents with persistent cough and shortness of breath for two days.",
    "o": "Blood pressure 120/80 mmHg, respiratory rate 18, bilateral wheezing noted on auscultation.",
    "a": "Acute exacerbation of moderate persistent asthma, ICD-10 code J45.909.",
    "p": "Prescribed inhaled albuterol every 4 hours, follow up in clinic next week.",
}

SOAP_MODIFIED = {
    "s": "Patient presents with progressive chest tightness and shortness of breath for two days.",
    "o": "Blood pressure 125/82 mmHg, respiratory rate 20, bilateral expiratory wheezing noted.",
    "a": "Acute exacerbation of moderate persistent asthma, ICD-10 code J45.909 confirmed.",
    "p": "Prescribed inhaled albuterol and short course oral steroids, return in 3 days.",
}

SOAP_BAD = {
    "s": "咳嗽喉嚨痛兩天",
    "o": "喉嚨微紅發炎",
    "a": "感冒",
    "p": "給予普拿疼服用",
}


def _setup_cycle_with_draft(app, state="AWAITING_CONFIRM", soap=None):
    store = app.case_store
    m_id = str(uuid.uuid4())
    cycle, _ = create_cycle(store, command_id=uuid.uuid4().hex, machine_id=m_id, room_id="room_1")
    cid = cycle["cycle_id"]

    draft = store.create_soap_draft(
        case_id=f"case_{cid[:8]}",
        soap=soap or SOAP_OK,
        order_code="33001B",
        state="validated",
    )

    # 記錄 extras_json 在 recording_cycles
    extras = {
        "summary_zh": "病患主訴咳嗽氣喘",
        "past_history": "氣喘病史三年",
        "suggestions": {"icd10": ["J45.909"], "orders": ["33001B"], "meds": ["albuterol"]},
    }
    conn = store._connect()
    with conn:
        conn.execute(
            "UPDATE recording_cycles SET draft_id = ?, extras_json = ? WHERE cycle_id = ?",
            (draft.draft_id, json.dumps(extras), cid),
        )
    conn.close()

    transition_cycle(store, cid, "AWAITING_DRAFT")
    if state == "AWAITING_CONFIRM":
        transition_cycle(store, cid, "AWAITING_CONFIRM", fields={"draft_id": draft.draft_id})
    elif state == "DRAFT_UNUSABLE":
        transition_cycle(store, cid, "DRAFT_UNUSABLE", fields={"draft_id": draft.draft_id})

    return cid, draft, m_id


def test_confirm_unmodified_success(phase31_app, phase31_client):
    """Test 1 & 2: AWAITING_CONFIRM 未修改 soap → cycle_confirmations 寫入，草稿 queued，HIS_PUSH 任務綁定本機且 soap 嚴格僅 {s,o,a,p}。"""
    store = phase31_app.case_store
    cid, draft, m_id = _setup_cycle_with_draft(phase31_app, "AWAITING_CONFIRM")

    headers = {"X-API-Key": "valid-key-123"}
    resp = phase31_client.post(
        f"/api/cycles/{cid}/confirm",
        headers=headers,
        json={"content_hash": draft.content_hash, "reviewer_id": "Dr. Smith"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["cycle"]["state"] == "CONFIRMED"
    assert data["draft_id"] == draft.draft_id
    assert data["content_hash"] == draft.content_hash

    # 驗證 cycle_confirmations
    conn = store._connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM cycle_confirmations WHERE cycle_id = ?", (cid,))
    conf = cur.fetchone()
    assert conf is not None
    assert conf["draft_id"] == draft.draft_id
    assert conf["reviewer_id"] == "Dr. Smith"
    assert conf["content_hash"] == draft.content_hash

    # 驗證草稿狀態為 queued
    d_after = store.get_soap_draft(draft.draft_id)
    assert d_after.state == "queued"

    # Test 2: 驗證 HIS_PUSH 任務 extra_payload
    cur.execute("SELECT * FROM cases WHERE kind = 'bridge' ORDER BY created_at DESC LIMIT 1")
    job_row = cur.fetchone()
    conn.close()

    assert job_row is not None
    payload = json.loads(job_row["payload_json"])
    assert payload["s_type_code"] == "HIS_PUSH"
    extra = payload["extra_payload"]
    assert extra["machine_id"] == m_id

    # 嚴格驗證 soap 只有 s, o, a, p (D-31-26)
    assert set(extra["soap"].keys()) == {"s", "o", "a", "p"}
    for forbidden in ["summary_zh", "past_history", "suggestions", "transcript"]:
        assert forbidden not in extra


def test_confirm_stale_hash_rejected(phase31_app, phase31_client):
    """Test 3: content_hash 過期 → 409，無任何寫入。"""
    cid, draft, _ = _setup_cycle_with_draft(phase31_app, "AWAITING_CONFIRM")

    headers = {"X-API-Key": "valid-key-123"}
    resp = phase31_client.post(
        f"/api/cycles/{cid}/confirm",
        headers=headers,
        json={"content_hash": "stale_hash_xyz"},
    )
    assert resp.status_code == 409

    store = phase31_app.case_store
    conn = store._connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM cycle_confirmations WHERE cycle_id = ?", (cid,))
    assert cur.fetchone()["cnt"] == 0
    conn.close()


def test_confirm_modified_soap_valid(phase31_app, phase31_client):
    """Test 4: 帶修改後 soap（合格）→ 草稿版本遞增，確認版存新 soap 與新 hash。"""
    cid, draft, _ = _setup_cycle_with_draft(phase31_app, "AWAITING_CONFIRM")

    headers = {"X-API-Key": "valid-key-123"}
    resp = phase31_client.post(
        f"/api/cycles/{cid}/confirm",
        headers=headers,
        json={"content_hash": draft.content_hash, "soap": SOAP_MODIFIED},
    )
    assert resp.status_code == 200

    store = phase31_app.case_store
    d_after = store.get_soap_draft(draft.draft_id)
    assert d_after.version == draft.version + 1
    assert d_after.soap["s"] == SOAP_MODIFIED["s"]

    conn = store._connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM cycle_confirmations WHERE cycle_id = ?", (cid,))
    conf = cur.fetchone()
    conn.close()

    assert conf["content_hash"] == d_after.content_hash
    conf_soap = json.loads(conf["soap_json"])
    assert conf_soap["s"] == SOAP_MODIFIED["s"]


def test_confirm_modified_soap_invalid(phase31_app, phase31_client):
    """Test 5: 帶修改後 soap（不合格）→ 422 附 quality_issues，循環轉 DRAFT_UNUSABLE，無 HIS 任務。"""
    cid, draft, _ = _setup_cycle_with_draft(phase31_app, "AWAITING_CONFIRM")

    headers = {"X-API-Key": "valid-key-123"}
    resp = phase31_client.post(
        f"/api/cycles/{cid}/confirm",
        headers=headers,
        json={"content_hash": draft.content_hash, "soap": SOAP_BAD},
    )
    assert resp.status_code == 422
    data = resp.get_json()
    assert "quality_issues" in data or "issues" in data

    store = phase31_app.case_store
    from elc_audit_engine.cycles.store import get_cycle
    c = get_cycle(store, cid)
    assert c["state"] == "DRAFT_UNUSABLE"

    # 無 cycle_confirmations 與 HIS 任務
    conn = store._connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM cycle_confirmations WHERE cycle_id = ?", (cid,))
    assert cur.fetchone()["cnt"] == 0
    cur.execute("SELECT COUNT(*) AS cnt FROM cases WHERE kind = 'bridge'")
    assert cur.fetchone()["cnt"] == 0
    conn.close()


def test_confirm_draft_unusable_with_valid_soap(phase31_app, phase31_client):
    """Test 6: DRAFT_UNUSABLE 帶合格 soap → 建立新草稿改綁定，循環 CONFIRMED，舊草稿不動。"""
    cid, old_draft, _ = _setup_cycle_with_draft(phase31_app, "DRAFT_UNUSABLE", soap=SOAP_BAD)

    headers = {"X-API-Key": "valid-key-123"}
    resp = phase31_client.post(
        f"/api/cycles/{cid}/confirm",
        headers=headers,
        json={"content_hash": old_draft.content_hash, "soap": SOAP_OK},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    new_draft_id = data["draft_id"]
    assert new_draft_id != old_draft.draft_id
    assert data["cycle"]["state"] == "CONFIRMED"

    store = phase31_app.case_store
    d_old = store.get_soap_draft(old_draft.draft_id)
    assert d_old.draft_id == old_draft.draft_id  # 舊草稿保留


def test_confirm_draft_unusable_no_soap(phase31_app, phase31_client):
    """Test 7: DRAFT_UNUSABLE 不帶 soap → 422「草稿需修改後才能存檔」。"""
    cid, draft, _ = _setup_cycle_with_draft(phase31_app, "DRAFT_UNUSABLE", soap=SOAP_BAD)

    headers = {"X-API-Key": "valid-key-123"}
    resp = phase31_client.post(
        f"/api/cycles/{cid}/confirm",
        headers=headers,
        json={"content_hash": draft.content_hash},
    )
    assert resp.status_code == 422
    assert "需修改" in resp.get_json()["message"]


def test_confirm_idempotent_resend(phase31_app, phase31_client):
    """Test 8: 已 CONFIRMED 以相同 content_hash 重送 → 200，不產生第二筆任務或第二列確認版。"""
    cid, draft, _ = _setup_cycle_with_draft(phase31_app, "AWAITING_CONFIRM")
    headers = {"X-API-Key": "valid-key-123"}

    # 第一次 confirm
    resp1 = phase31_client.post(
        f"/api/cycles/{cid}/confirm",
        headers=headers,
        json={"content_hash": draft.content_hash},
    )
    assert resp1.status_code == 200

    # 重送
    resp2 = phase31_client.post(
        f"/api/cycles/{cid}/confirm",
        headers=headers,
        json={"content_hash": draft.content_hash},
    )
    assert resp2.status_code == 200

    store = phase31_app.case_store
    conn = store._connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM cycle_confirmations WHERE cycle_id = ?", (cid,))
    assert cur.fetchone()["cnt"] == 1
    cur.execute("SELECT COUNT(*) AS cnt FROM cases WHERE kind = 'bridge'")
    assert cur.fetchone()["cnt"] == 1
    conn.close()


def test_confirm_crash_recovery(phase31_app, phase31_client):
    """Test 9: ensure_job 第一次拋錯 500；重送 confirm → 200，恰一筆任務，循環 CONFIRMED (D-31-38)。"""
    cid, draft, _ = _setup_cycle_with_draft(phase31_app, "AWAITING_CONFIRM")
    headers = {"X-API-Key": "valid-key-123"}

    from elc_audit_engine.api.routes import soap_review

    original_ensure = soap_review.ensure_job
    call_cnt = 0

    def mock_ensure(*args, **kwargs):
        nonlocal call_cnt
        call_cnt += 1
        if call_cnt == 1:
            raise RuntimeError("Database IO transient error")
        return original_ensure(*args, **kwargs)

    with patch.object(soap_review, "ensure_job", side_effect=mock_ensure):
        resp1 = phase31_client.post(
            f"/api/cycles/{cid}/confirm",
            headers=headers,
            json={"content_hash": draft.content_hash},
        )
        assert resp1.status_code == 500

    # 重送成功恢復
    resp2 = phase31_client.post(
        f"/api/cycles/{cid}/confirm",
        headers=headers,
        json={"content_hash": draft.content_hash},
    )
    assert resp2.status_code == 200

    store = phase31_app.case_store
    conn = store._connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM cases WHERE kind = 'bridge'")
    assert cur.fetchone()["cnt"] == 1
    conn.close()


def test_confirm_audit_detail(phase31_app, phase31_client):
    """Test 10: 審計 detail 只含 action、cycle_id、draft_id、content_hash。"""
    cid, draft, _ = _setup_cycle_with_draft(phase31_app, "AWAITING_CONFIRM")
    headers = {"X-API-Key": "valid-key-123"}

    phase31_client.post(
        f"/api/cycles/{cid}/confirm",
        headers=headers,
        json={"content_hash": draft.content_hash},
    )

    from elc_audit_engine import audit_log
    entries = audit_log.read_entries(str(phase31_app.config.get("AUDIT_LOG_PATH", "")))
    conf_entries = [e for e in entries if e.get("detail", {}).get("action") == "cycle_confirm"]
    assert len(conf_entries) >= 1
    d = conf_entries[-1]["detail"]
    assert set(d.keys()) == {"action", "cycle_id", "draft_id", "content_hash"}
