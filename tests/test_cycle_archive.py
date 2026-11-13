"""Phase 31: 循環黃燈封存與 HIS 寫入收斂測試 (契約 §3, D-31-06, D-31-07, D-31-08, D-31-14, D-31-29)."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
import uuid


from elc_audit_engine.cycles.store import create_cycle, get_cycle, transition_cycle
from tests.phase31_support import phase31_app, phase31_client  # noqa: F401

SOAP_OK = {
    "s": "Patient presents with persistent cough and shortness of breath for two days.",
    "o": "Blood pressure 120/80 mmHg, respiratory rate 18, bilateral wheezing noted on auscultation.",
    "a": "Acute exacerbation of moderate persistent asthma, ICD-10 code J45.909.",
    "p": "Prescribed inhaled albuterol every 4 hours, follow up in clinic next week.",
}


def _setup_confirmed_cycle(app, client):
    """建立並確認一個循環，回傳 (cid, draft, machine_id)。"""
    store = app.case_store
    m_id = str(uuid.uuid4())
    cycle, _ = create_cycle(store, command_id=uuid.uuid4().hex, machine_id=m_id, room_id="room_1")
    cid = cycle["cycle_id"]

    draft = store.create_soap_draft(
        case_id=f"case_{cid[:8]}",
        soap=SOAP_OK,
        order_code="33001B",
        state="validated",
    )

    conn = store._connect()
    with conn:
        conn.execute("UPDATE recording_cycles SET draft_id = ? WHERE cycle_id = ?", (draft.draft_id, cid))
    conn.close()

    transition_cycle(store, cid, "AWAITING_DRAFT")
    transition_cycle(store, cid, "AWAITING_CONFIRM", fields={"draft_id": draft.draft_id})

    # 執行 confirm
    headers = {"X-API-Key": "valid-key-123"}
    resp = client.post(
        f"/api/cycles/{cid}/confirm",
        headers=headers,
        json={"content_hash": draft.content_hash},
    )
    assert resp.status_code == 200

    return cid, draft, m_id


def test_archive_requires_confirmed(phase31_app, phase31_client):
    """Test 1: AWAITING_CONFIRM 封存 → 409 not_confirmed，循環狀態不變 (D-31-08)。"""
    store = phase31_app.case_store
    m_id = str(uuid.uuid4())
    cycle, _ = create_cycle(store, command_id=uuid.uuid4().hex, machine_id=m_id)
    cid = cycle["cycle_id"]
    transition_cycle(store, cid, "AWAITING_DRAFT")
    transition_cycle(store, cid, "AWAITING_CONFIRM")

    headers = {"X-API-Key": "valid-key-123"}
    resp = phase31_client.post(f"/api/cycles/{cid}/archive", headers=headers)
    assert resp.status_code == 409
    assert resp.get_json()["status"] == "not_confirmed"

    c = get_cycle(store, cid)
    assert c["state"] == "AWAITING_CONFIRM"


def test_archive_his_pending(phase31_app, phase31_client):
    """Test 2: CONFIRMED、草稿 queued → 202 his_pending，循環 ARCHIVING。"""
    store = phase31_app.case_store
    cid, _, _ = _setup_confirmed_cycle(phase31_app, phase31_client)

    headers = {"X-API-Key": "valid-key-123"}
    resp = phase31_client.post(f"/api/cycles/{cid}/archive", headers=headers)
    assert resp.status_code == 202
    assert resp.get_json()["status"] == "his_pending"

    c = get_cycle(store, cid)
    assert c["state"] == "ARCHIVING"


def test_archive_success_and_already_archived(phase31_app, phase31_client):
    """Test 3: Agent 回報 SUCCESS → 草稿 pushed → 封存 200 archived、再封存 200 already_archived。"""
    store = phase31_app.case_store
    cid, draft, m_id = _setup_confirmed_cycle(phase31_app, phase31_client)

    # 模擬 Agent 認領並回報 SUCCESS
    agent_headers = {"X-API-Key": "agent-key-1"}
    claim_resp = phase31_client.get(
        f"/api/bridge/jobs/pending?machine_id={m_id}&sTypeCode=HIS_PUSH",
        headers=agent_headers,
    )
    assert claim_resp.status_code == 200
    job = claim_resp.get_json()["jobs"][0]

    phase31_client.post(
        f"/api/bridge/jobs/{job['job_id']}/status",
        headers=agent_headers,
        json={"status": "SENDING", "expected_status": "PENDING", "machine_id": m_id},
    )
    rep_resp = phase31_client.post(
        f"/api/bridge/jobs/{job['job_id']}/status",
        headers=agent_headers,
        json={"status": "SUCCESS", "machine_id": m_id},
    )
    assert rep_resp.status_code == 200

    # 草稿應已為 pushed
    d_after = store.get_soap_draft(draft.draft_id)
    assert d_after.state == "pushed"

    # 執行封存
    headers = {"X-API-Key": "valid-key-123"}
    resp = phase31_client.post(f"/api/cycles/{cid}/archive", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "archived"

    c = get_cycle(store, cid)
    assert c["state"] == "ARCHIVED"
    assert c["archived_at"] is not None

    # 再次封存 → 200 already_archived (冪等)
    resp2 = phase31_client.post(f"/api/cycles/{cid}/archive", headers=headers)
    assert resp2.status_code == 200
    assert resp2.get_json()["status"] == "already_archived"


def test_archive_his_failed(phase31_app, phase31_client):
    """Test 4: Agent 回報 FAILED → 草稿 failed；封存 → 409 his_failed，循環 ARCHIVE_FAILED。"""
    store = phase31_app.case_store
    cid, draft, m_id = _setup_confirmed_cycle(phase31_app, phase31_client)

    agent_headers = {"X-API-Key": "agent-key-1"}
    claim_resp = phase31_client.get(
        f"/api/bridge/jobs/pending?machine_id={m_id}&sTypeCode=HIS_PUSH",
        headers=agent_headers,
    )
    assert claim_resp.status_code == 200
    job = claim_resp.get_json()["jobs"][0]

    phase31_client.post(
        f"/api/bridge/jobs/{job['job_id']}/status",
        headers=agent_headers,
        json={"status": "SENDING", "expected_status": "PENDING", "machine_id": m_id},
    )
    phase31_client.post(
        f"/api/bridge/jobs/{job['job_id']}/status",
        headers=agent_headers,
        json={"status": "FAILED", "reason": "HIS_WINDOW_NOT_FOUND", "machine_id": m_id},
    )

    headers = {"X-API-Key": "valid-key-123"}
    resp = phase31_client.post(f"/api/cycles/{cid}/archive", headers=headers)
    assert resp.status_code == 409
    data = resp.get_json()
    assert data["status"] == "his_failed"
    assert "HIS_WINDOW_NOT_FOUND" in data["reason"]

    c = get_cycle(store, cid)
    assert c["state"] == "ARCHIVE_FAILED"


def test_archive_retry_from_failed(phase31_app, phase31_client):
    """Test 5: 從 ARCHIVE_FAILED 再封存 → 202 his_retry_queued，產生新 HIS_PUSH 任務，確認版不重寫。"""
    store = phase31_app.case_store
    cid, draft, m_id = _setup_confirmed_cycle(phase31_app, phase31_client)

    agent_headers = {"X-API-Key": "agent-key-1"}
    claim_resp = phase31_client.get(
        f"/api/bridge/jobs/pending?machine_id={m_id}&sTypeCode=HIS_PUSH",
        headers=agent_headers,
    )
    assert claim_resp.status_code == 200
    job1 = claim_resp.get_json()["jobs"][0]

    phase31_client.post(
        f"/api/bridge/jobs/{job1['job_id']}/status",
        headers=agent_headers,
        json={"status": "SENDING", "expected_status": "PENDING", "machine_id": m_id},
    )
    phase31_client.post(
        f"/api/bridge/jobs/{job1['job_id']}/status",
        headers=agent_headers,
        json={"status": "FAILED", "reason": "ERROR_TEST", "machine_id": m_id},
    )

    headers = {"X-API-Key": "valid-key-123"}
    # 第一次封存得 409
    phase31_client.post(f"/api/cycles/{cid}/archive", headers=headers)

    conn = store._connect()
    cur = conn.cursor()
    cur.execute("SELECT confirmed_at FROM cycle_confirmations WHERE cycle_id = ?", (cid,))
    orig_confirmed_at = cur.fetchone()["confirmed_at"]
    conn.close()

    # 第二次封存重試
    resp_retry = phase31_client.post(f"/api/cycles/{cid}/archive", headers=headers)
    assert resp_retry.status_code == 202
    assert resp_retry.get_json()["status"] == "his_retry_queued"

    c = get_cycle(store, cid)
    assert c["state"] == "ARCHIVING"

    # 確認產生新任務且確認版時間不變
    conn = store._connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM cases WHERE kind = 'bridge'")
    assert cur.fetchone()["cnt"] == 2
    cur.execute("SELECT confirmed_at FROM cycle_confirmations WHERE cycle_id = ?", (cid,))
    assert cur.fetchone()["confirmed_at"] == orig_confirmed_at
    conn.close()


def test_archive_missing_confirmation_snapshot(phase31_app, phase31_client):
    """Test 6: 人為刪除 cycle_confirmations 列後封存 → 409 confirmation_missing，循環轉 ARCHIVE_FAILED。"""
    store = phase31_app.case_store
    cid, _, _ = _setup_confirmed_cycle(phase31_app, phase31_client)

    conn = store._connect()
    with conn:
        conn.execute("DELETE FROM cycle_confirmations WHERE cycle_id = ?", (cid,))
    conn.close()

    headers = {"X-API-Key": "valid-key-123"}
    resp = phase31_client.post(f"/api/cycles/{cid}/archive", headers=headers)
    assert resp.status_code == 409
    data = resp.get_json()
    assert data["status"] == "his_failed"
    assert data["reason"] == "confirmation_missing"

    c = get_cycle(store, cid)
    assert c["state"] == "ARCHIVE_FAILED"


def test_archive_stuck_approved_recovery(phase31_app, phase31_client):
    """Test 7: 草稿 approved 且無任務（31-02 崩潰窗口）→ 封存自動恢復排入任務回 202 his_pending。"""
    store = phase31_app.case_store
    cid, draft, m_id = _setup_confirmed_cycle(phase31_app, phase31_client)

    # 模擬崩潰狀態：草稿設為 approved，並刪除 bridge 任務
    conn = store._connect()
    with conn:
        conn.execute("UPDATE soap_drafts SET state = 'approved' WHERE draft_id = ?", (draft.draft_id,))
        conn.execute("DELETE FROM cases WHERE kind = 'bridge'")
    conn.close()

    headers = {"X-API-Key": "valid-key-123"}
    resp = phase31_client.post(f"/api/cycles/{cid}/archive", headers=headers)
    assert resp.status_code == 202
    assert resp.get_json()["status"] == "his_pending"

    # 驗證補排入任務
    conn = store._connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM cases WHERE kind = 'bridge'")
    assert cur.fetchone()["cnt"] == 1
    conn.close()


def test_archive_double_submit_concurrency(phase31_app, phase31_client):
    """Test 8: 兩個執行緒同時封存 → 一個 200 archived、一個 200 already_archived；ARCHIVED 轉換與審計恰一筆。"""
    store = phase31_app.case_store
    cid, draft, m_id = _setup_confirmed_cycle(phase31_app, phase31_client)

    # 先推進至 pushed
    conn = store._connect()
    with conn:
        conn.execute("UPDATE soap_drafts SET state = 'pushed' WHERE draft_id = ?", (draft.draft_id,))
    conn.close()

    headers = {"X-API-Key": "valid-key-123"}
    results = []

    def call_archive():
        r = phase31_client.post(f"/api/cycles/{cid}/archive", headers=headers)
        return r.status_code, r.get_json()["status"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(call_archive)
        f2 = executor.submit(call_archive)
        results = [f1.result(), f2.result()]

    statuses = [s for _, s in results]
    assert 200 in [r[0] for r in results]
    assert "archived" in statuses
    assert "already_archived" in statuses

    # 驗證 cycle_events
    conn = store._connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM cycle_events WHERE cycle_id = ? AND to_state = 'ARCHIVED'", (cid,))
    assert cur.fetchone()["cnt"] == 1
    conn.close()

    # 驗證 audit_log 恰一筆
    from elc_audit_engine import audit_log
    entries = audit_log.read_entries(str(phase31_app.config.get("AUDIT_LOG_PATH", "")))
    arch_entries = [e for e in entries if e.get("detail", {}).get("action") == "cycle_archive" and e["detail"].get("cycle_id") == cid]
    assert len(arch_entries) == 1


def test_archive_allows_new_cycle(phase31_app, phase31_client):
    """Test 9: 封存後同一 machine_id 可建立新循環（回到待命）。"""
    cid, draft, m_id = _setup_confirmed_cycle(phase31_app, phase31_client)

    conn = phase31_app.case_store._connect()
    with conn:
        conn.execute("UPDATE soap_drafts SET state = 'pushed' WHERE draft_id = ?", (draft.draft_id,))
    conn.close()

    headers = {"X-API-Key": "valid-key-123"}
    phase31_client.post(f"/api/cycles/{cid}/archive", headers=headers)

    # 再次為同 machine_id 建立新循環
    resp_new = phase31_client.post(
        "/api/cycles",
        headers=headers,
        json={"command_id": uuid.uuid4().hex, "machine_id": m_id},
    )
    assert resp_new.status_code == 201


def test_archive_does_not_delete_files(phase31_app, phase31_client):
    """Test 10: 封存不刪除 DATA_DIR/cycles/{id}/ 任何檔案 (D-31-29)。"""
    store = phase31_app.case_store
    cid, draft, _ = _setup_confirmed_cycle(phase31_app, phase31_client)

    c_dir = Path(phase31_app.config["DATA_DIR"]) / "cycles" / cid
    c_dir.mkdir(parents=True, exist_ok=True)
    f1 = c_dir / "full.wav"
    f1.write_bytes(b"dummy_full_wav")
    f2 = c_dir / "transcript.txt"
    f2.write_text("dummy transcript", encoding="utf-8")

    conn = store._connect()
    with conn:
        conn.execute("UPDATE soap_drafts SET state = 'pushed' WHERE draft_id = ?", (draft.draft_id,))
    conn.close()

    headers = {"X-API-Key": "valid-key-123"}
    phase31_client.post(f"/api/cycles/{cid}/archive", headers=headers)

    assert f1.exists()
    assert f2.exists()
