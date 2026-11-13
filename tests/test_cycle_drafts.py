"""Tests for cycle draft submission and review view (Phase 31 Plan 31-10 Task 2)."""


from elc_audit_engine.cycles.states import (
    STATE_AWAITING_CONFIRM,
    STATE_AWAITING_DRAFT,
    STATE_DRAFT_UNUSABLE,
)
from elc_audit_engine.cycles.store import create_cycle, cycle_dir, transition_cycle
from tests.phase31_support import phase31_app, phase31_client  # noqa: F401

KEY = {"X-API-Key": "valid-key-123"}
AGENT_KEY = {"X-API-Key": "agent-key-1"}

SOAP_OK = {
    "s": "Patient presents with a three day history of sore throat, low grade fever, and runny nose.",
    "o": "Temperature 37.8 C, pharyngeal hyperemia, tender bilateral cervical lymphadenopathy.",
    "a": "Acute pharyngitis, most consistent with viral etiology, primary diagnosis coded J02.9.",
    "p": "Advise rest, warm fluids, and symptomatic relief; follow up in five days if fever persists.",
}
SOAP_BAD = {"s": "short", "o": "short", "a": "short", "p": "short"}


def _setup_cycle_ready(store, cycle_id: str = "c1" * 16, upload_complete: bool = True):
    c, _ = create_cycle(store, command_id="cmd_" + cycle_id[:16], machine_id="m1")
    cid = c["cycle_id"]
    transition_cycle(store, cid, STATE_AWAITING_DRAFT, actor="test")
    if upload_complete:
        conn = store._connect()
        try:
            with conn:
                conn.execute(
                    "UPDATE recording_cycles SET upload_complete = 1, audio_path = 'full.wav' WHERE cycle_id = ?",
                    (cid,),
                )
        finally:
            conn.close()
    return cid


def test_submit_draft_unfinalized_blocked(phase31_client, phase31_app):
    """Test 1: 未 finalize（upload_complete=0）送出草稿 → 409。"""
    store = phase31_app.case_store
    cid = _setup_cycle_ready(store, "11" * 16, upload_complete=False)

    payload = {
        "session_id": "sess_001",
        "soap": {"s": "發燒", "o": "38.5", "a": "上呼吸道感染", "p": "處方"},
        "transcript": "醫師：你好。病人：我發燒了。",
    }
    res = phase31_client.post(f"/api/cycles/{cid}/draft", headers=KEY, json=payload)
    assert res.status_code == 409


def test_submit_draft_success(phase31_client, phase31_app):
    """Test 2: 正確送出 → 201，cycle.state=AWAITING_CONFIRM，transcript.txt 保存，extras 存入。"""
    store = phase31_app.case_store
    cid = _setup_cycle_ready(store, "22" * 16, upload_complete=True)

    transcript_text = "醫師：你好。病人：我喉嚨痛兩天。"
    payload = {
        "session_id": "sess_002",
        "soap": SOAP_OK,
        "transcript": transcript_text,
        "extras": {
            "summary_zh": "主訴咽喉疼痛無發燒",
            "past_history": "無特殊病史",
            "suggestions": {"icd10": ["J02.9"], "orders": ["001"], "meds": ["Amoxicillin"]},
        },
    }
    res = phase31_client.post(f"/api/cycles/{cid}/draft", headers=KEY, json=payload)
    assert res.status_code == 201
    body = res.get_json()
    assert body["status"] == "success"
    assert body["cycle"]["state"] == STATE_AWAITING_CONFIRM
    assert body["cycle"]["chunks_received"] == 0
    draft_id = body["draft_id"]
    assert draft_id

    # 驗證 transcript.txt
    t_file = cycle_dir(cid) / "transcript.txt"
    assert t_file.is_file()
    assert t_file.read_text(encoding="utf-8") == transcript_text


def test_submit_draft_idempotency_and_state_conflict(phase31_client, phase31_app):
    """Test 3: 同 session_id 重送 → 200 同一 draft_id；不同 session_id 於 AWAITING_CONFIRM → 409。"""
    store = phase31_app.case_store
    cid = _setup_cycle_ready(store, "33" * 16, upload_complete=True)

    payload1 = {
        "session_id": "sess_003",
        "soap": SOAP_OK,
        "transcript": "逐字稿內容",
    }
    r1 = phase31_client.post(f"/api/cycles/{cid}/draft", headers=KEY, json=payload1)
    assert r1.status_code == 201
    assert r1.get_json()["cycle"]["state"] == STATE_AWAITING_CONFIRM
    d1_id = r1.get_json()["draft_id"]

    # 1. 同 session_id 重送
    r2 = phase31_client.post(f"/api/cycles/{cid}/draft", headers=KEY, json=payload1)
    assert r2.status_code == 200
    assert r2.get_json()["draft_id"] == d1_id

    # 2. 不同 session_id 於 AWAITING_CONFIRM 再送
    payload2 = {
        "session_id": "sess_004",
        "soap": SOAP_OK,
        "transcript": "另一篇逐字稿",
    }
    r3 = phase31_client.post(f"/api/cycles/{cid}/draft", headers=KEY, json=payload2)
    assert r3.status_code == 409


def test_submit_draft_quality_unusable_then_retry(phase31_client, phase31_app):
    """Test 4: 品質不合格 soap → 201 DRAFT_UNUSABLE；於 DRAFT_UNUSABLE 再送合格 soap → AWAITING_CONFIRM。"""
    store = phase31_app.case_store
    cid = _setup_cycle_ready(store, "44" * 16, upload_complete=True)

    # 不合格 soap
    bad_payload = {
        "session_id": "sess_bad",
        "soap": SOAP_BAD,
        "transcript": "話不多",
    }
    r_bad = phase31_client.post(f"/api/cycles/{cid}/draft", headers=KEY, json=bad_payload)
    assert r_bad.status_code == 201
    assert r_bad.get_json()["cycle"]["state"] == STATE_DRAFT_UNUSABLE

    # 於 DRAFT_UNUSABLE 再送新 session_id 與合格 soap
    good_payload = {
        "session_id": "sess_fixed",
        "soap": SOAP_OK,
        "transcript": "完整問診記錄",
    }
    r_good = phase31_client.post(f"/api/cycles/{cid}/draft", headers=KEY, json=good_payload)
    assert r_good.status_code == 201
    assert r_good.get_json()["cycle"]["state"] == STATE_AWAITING_CONFIRM
    assert r_good.get_json()["draft_id"] != r_bad.get_json()["draft_id"]


def test_cycle_draft_never_auto_accepted(phase31_client, phase31_app, monkeypatch):
    """Test 5: 自動接入設定為 true 時，循環草稿仍停在 validated (未 approved, D-31-08)。"""
    store = phase31_app.case_store
    cid = _setup_cycle_ready(store, "55" * 16, upload_complete=True)

    # 啟用自動接入
    monkeypatch.setenv("SOAP_AUTO_ACCEPT_ENABLED", "1")

    payload = {
        "session_id": "sess_no_auto",
        "soap": SOAP_OK,
        "transcript": "跌倒擦傷",
    }
    res = phase31_client.post(f"/api/cycles/{cid}/draft", headers=KEY, json=payload)
    assert res.status_code == 201
    draft_id = res.get_json()["draft_id"]

    d = store.get_soap_draft(draft_id)
    assert d.state == "validated"  # 絕不可為 approved 或 queued


def test_get_cycle_draft_view_structure(phase31_client, phase31_app):
    """Test 6: GET /api/cycles/{id}/draft 唯讀建議項、可選逐字稿。"""
    store = phase31_app.case_store
    cid = _setup_cycle_ready(store, "66" * 16, upload_complete=True)

    payload = {
        "session_id": "sess_view",
        "soap": SOAP_OK,
        "transcript": "這是逐字稿全文記錄",
        "extras": {
            "summary_zh": "摘要文字",
            "past_history": "過去病史",
            "suggestions": {"icd10": ["J00"], "orders": ["O1"], "meds": ["M1"]},
        },
    }
    phase31_client.post(f"/api/cycles/{cid}/draft", headers=KEY, json=payload)

    # 1. 預設不帶 include_transcript
    r1 = phase31_client.get(f"/api/cycles/{cid}/draft", headers=KEY)
    assert r1.status_code == 200
    b1 = r1.get_json()
    assert b1["cycle_id"] == cid
    assert b1["draft"]["soap"]["s"] == SOAP_OK["s"]
    assert b1["draft"]["content_hash"]
    assert b1["advisory"]["read_only"] is True
    assert b1["extras"]["summary_zh"] == "摘要文字"
    assert "transcript" not in b1

    # 2. 帶 include_transcript=1
    r2 = phase31_client.get(f"/api/cycles/{cid}/draft?include_transcript=1", headers=KEY)
    assert r2.status_code == 200
    b2 = r2.get_json()
    assert b2["transcript"] == "這是逐字稿全文記錄"


def test_submit_draft_payload_boundary_validation(phase31_client, phase31_app):
    """Test 7: soap 缺鍵、extras 長度超限、suggestions 清單超限 → 422。"""
    store = phase31_app.case_store
    cid = _setup_cycle_ready(store, "77" * 16, upload_complete=True)

    # 1. 缺少 soap.p
    bad_soap = {"session_id": "s_b1", "soap": {"s": "a", "o": "b", "a": "c"}}
    assert phase31_client.post(f"/api/cycles/{cid}/draft", headers=KEY, json=bad_soap).status_code == 422

    # 2. summary_zh 超過 20000 字
    bad_extra_str = {
        "session_id": "s_b2",
        "soap": {"s": "s", "o": "o", "a": "a", "p": "p"},
        "extras": {"summary_zh": "x" * 20001},
    }
    assert phase31_client.post(f"/api/cycles/{cid}/draft", headers=KEY, json=bad_extra_str).status_code == 422

    # 3. suggestions 清單超過 200 項
    bad_extra_list = {
        "session_id": "s_b3",
        "soap": {"s": "s", "o": "o", "a": "a", "p": "p"},
        "extras": {"suggestions": {"icd10": ["item"] * 201}},
    }
    assert phase31_client.post(f"/api/cycles/{cid}/draft", headers=KEY, json=bad_extra_list).status_code == 422


def test_cycle_draft_auth(phase31_client, phase31_app):
    """Test 8: Agent 金鑰 → 403；無 key → 401。"""
    store = phase31_app.case_store
    cid = _setup_cycle_ready(store, "88" * 16, upload_complete=True)

    # 無 key
    assert phase31_client.get(f"/api/cycles/{cid}/draft").status_code == 401
    assert phase31_client.post(f"/api/cycles/{cid}/draft", json={}).status_code == 401

    # Agent 金鑰
    assert phase31_client.get(f"/api/cycles/{cid}/draft", headers=AGENT_KEY).status_code == 403
    assert phase31_client.post(f"/api/cycles/{cid}/draft", headers=AGENT_KEY, json={}).status_code == 403


def test_cycle_draft_caplog_no_leak(phase31_client, phase31_app, caplog):
    """Test 9: 審計與日誌不含 transcript 或 soap 內文。"""
    store = phase31_app.case_store
    cid = _setup_cycle_ready(store, "99" * 16, upload_complete=True)

    secret_soap_text = "SECRET-PHRASE-XYZ-PATIENT-DIAGNOSIS-999"
    secret_transcript = "SECRET-TRANSCRIPT-TEXT-CONVERSATION-999"

    leak_soap = dict(SOAP_OK)
    leak_soap["s"] = f"Patient presents with {secret_soap_text} and general malaise."

    payload = {
        "session_id": "sess_audit_test",
        "soap": leak_soap,
        "transcript": secret_transcript,
    }
    phase31_client.post(f"/api/cycles/{cid}/draft", headers=KEY, json=payload)

    for record in caplog.records:
        msg = record.getMessage()
        assert secret_soap_text not in msg
        assert secret_transcript not in msg
