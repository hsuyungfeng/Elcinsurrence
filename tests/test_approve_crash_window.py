"""Phase 31 Plan 02: 核准流程崩潰窗口與可恢復性測試 (D-31-38, D-31-07)."""

from __future__ import annotations

import sqlite3

from elc_audit_engine.case_store.soap_draft_states import (
    STATE_APPROVED,
    STATE_FAILED,
    STATE_QUEUED,
    STATE_VALIDATED,
)
from tests.phase31_support import phase31_app, phase31_client  # noqa: F401

KEY = {"X-API-Key": "valid-key-123"}

SOAP_OK = {
    "s": "Patient presents with a three day history of sore throat, low grade fever, and runny nose.",
    "o": "Temperature 37.8 C, pharyngeal hyperemia, tender bilateral cervical lymphadenopathy.",
    "a": "Acute pharyngitis, most consistent with viral etiology, primary diagnosis coded J02.9.",
    "p": "Advise rest, warm fluids, and symptomatic relief; follow up in five days if fever persists.",
}


def _get_his_push_jobs_for_draft(store, draft_id: str):
    """取得特定 draft_id 的 HIS_PUSH bridge jobs。"""
    jobs = store.list_bridge_jobs(s_type_code="HIS_PUSH")
    matched = []
    for j in jobs:
        payload = j.payload if isinstance(j.payload, dict) else {}
        extra = payload.get("extra_payload") or {}
        if extra.get("draft_id") == draft_id:
            matched.append(j)
    return matched


def _create_validated_draft(store, case_id: str = "CASE-CRASH-01"):
    store.create(case_id=case_id, kind="monthly", payload={"patient": "test"})
    draft = store.create_soap_draft(
        case_id=case_id,
        soap=SOAP_OK,
        state=STATE_VALIDATED,
    )
    return draft


def test_crash_after_approved_and_retry(phase31_app, phase31_client, monkeypatch):
    """Test 1: 第一步 (approved) 成功後在 enqueue 崩潰，重試核准可收斂至 queued 且恰有一筆任務。"""
    store = phase31_app.case_store
    draft = _create_validated_draft(store, "C-CRASH-01")
    draft_id = draft.draft_id
    content_hash = draft.content_hash

    from elc_audit_engine.api.routes import soap_review

    original_ensure = soap_review.ensure_job
    call_count = 0

    def mock_ensure(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Simulated crash right after state=approved")
        return original_ensure(*args, **kwargs)

    monkeypatch.setattr(soap_review, "ensure_job", mock_ensure)

    # 第一次核准：因 enqueue 拋錯回 500
    res1 = phase31_client.post(
        f"/api/soap/drafts/{draft_id}/approve",
        json={"content_hash": content_hash},
        headers=KEY,
    )
    assert res1.status_code == 500

    # 此時草稿應停在 approved，且尚未有 job
    d_after_crash = store.get_soap_draft(draft_id)
    assert d_after_crash.state == STATE_APPROVED
    assert len(_get_his_push_jobs_for_draft(store, draft_id)) == 0

    # 恢復正常的 ensure
    monkeypatch.setattr(soap_review, "ensure_job", original_ensure)

    # 第二次核准（重試）：必須成功回 200，草稿變 queued，恰有一筆 HIS_PUSH 任務
    res2 = phase31_client.post(
        f"/api/soap/drafts/{draft_id}/approve",
        json={"content_hash": content_hash},
        headers=KEY,
    )
    assert res2.status_code == 200

    d_final = store.get_soap_draft(draft_id)
    assert d_final.state == STATE_QUEUED
    jobs = _get_his_push_jobs_for_draft(store, draft_id)
    assert len(jobs) == 1
    assert jobs[0].payload["extra_payload"]["draft_id"] == draft_id


def test_crash_after_enqueue_and_retry(phase31_app, phase31_client, monkeypatch):
    """Test 2: enqueue 成功後在轉 queued 步驟崩潰，重試核准不會建立第二筆任務。"""
    store = phase31_app.case_store
    draft = _create_validated_draft(store, "C-CRASH-02")
    draft_id = draft.draft_id
    content_hash = draft.content_hash

    original_update = store.update_soap_draft_state
    call_count = 0

    def mock_update(d_id, to_state, *args, **kwargs):
        nonlocal call_count
        if d_id == draft_id and to_state == STATE_QUEUED:
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Simulated crash right after enqueue_job")
        return original_update(d_id, to_state, *args, **kwargs)

    monkeypatch.setattr(store, "update_soap_draft_state", mock_update)

    res1 = phase31_client.post(
        f"/api/soap/drafts/{draft_id}/approve",
        json={"content_hash": content_hash},
        headers=KEY,
    )
    assert res1.status_code == 500

    # 恢復正常的 update_soap_draft_state
    monkeypatch.setattr(store, "update_soap_draft_state", original_update)

    # 重試核准
    res2 = phase31_client.post(
        f"/api/soap/drafts/{draft_id}/approve",
        json={"content_hash": content_hash},
        headers=KEY,
    )
    assert res2.status_code == 200

    d_final = store.get_soap_draft(draft_id)
    assert d_final.state == STATE_QUEUED
    jobs = _get_his_push_jobs_for_draft(store, draft_id)
    assert len(jobs) == 1


def test_recover_stuck_approved_sweep(phase31_app):
    """Test 3: recover_stuck_approved(store) 掃描並修復卡在 approved 狀態的草稿。"""
    store = phase31_app.case_store
    draft = _create_validated_draft(store, "C-CRASH-03")
    draft_id = draft.draft_id

    # 模擬卡在 approved（直接轉為 approved 且無 job）
    store.update_soap_draft_state(
        draft_id,
        STATE_APPROVED,
        reviewer_id="rev-03",
        decision="approved",
    )
    assert store.get_soap_draft(draft_id).state == STATE_APPROVED
    assert len(_get_his_push_jobs_for_draft(store, draft_id)) == 0

    from elc_audit_engine.api.routes.soap_review import recover_stuck_approved

    fixed_count = recover_stuck_approved(store)
    assert fixed_count == 1

    d_final = store.get_soap_draft(draft_id)
    assert d_final.state == STATE_QUEUED
    jobs = _get_his_push_jobs_for_draft(store, draft_id)
    assert len(jobs) == 1

    # 再次執行應回傳 0
    assert recover_stuck_approved(store) == 0


def test_failed_retry_generates_new_job(phase31_app, phase31_client):
    """Test 4: 草稿 failed 之後重試核准，產生新的 HIS_PUSH 任務，舊任務不被覆寫。"""
    store = phase31_app.case_store
    draft = _create_validated_draft(store, "C-CRASH-04")
    draft_id = draft.draft_id
    content_hash = draft.content_hash

    # 第一次正常核准
    res1 = phase31_client.post(
        f"/api/soap/drafts/{draft_id}/approve",
        json={"content_hash": content_hash},
        headers=KEY,
    )
    assert res1.status_code == 200
    jobs1 = _get_his_push_jobs_for_draft(store, draft_id)
    assert len(jobs1) == 1
    job1_id = jobs1[0].case_id

    # 模擬 agent 回報 failed
    store.update_soap_draft_state(
        draft_id,
        STATE_FAILED,
        agent_id="agent-01",
        failure_reason="HIS timeout",
    )
    assert store.get_soap_draft(draft_id).state == STATE_FAILED

    # 再次核准
    res2 = phase31_client.post(
        f"/api/soap/drafts/{draft_id}/approve",
        json={"content_hash": content_hash},
        headers=KEY,
    )
    assert res2.status_code == 200
    jobs2 = _get_his_push_jobs_for_draft(store, draft_id)
    assert len(jobs2) == 2
    job_ids = {j.case_id for j in jobs2}
    assert job1_id in job_ids


def test_batch_approve_crash_recovery(phase31_app, phase31_client, monkeypatch):
    """Test 5: approve_batch 中途崩潰的草稿，再次 approve_batch 可恢復且任務不重複。"""
    store = phase31_app.case_store
    batch_id = "BATCH-CRASH-01"
    d1 = _create_validated_draft(store, "C-B-01")
    d2 = _create_validated_draft(store, "C-B-02")

    from elc_audit_engine.api.routes import soap_review

    original_ensure = soap_review.ensure_job
    call_count = 0

    def mock_ensure(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # 第二個草稿在 ensure 崩潰
        if call_count == 2:
            raise RuntimeError("Crash on d2")
        return original_ensure(*args, **kwargs)

    monkeypatch.setattr(soap_review, "ensure_job", mock_ensure)

    items = [
        {"draft_id": d1.draft_id, "content_hash": d1.content_hash},
        {"draft_id": d2.draft_id, "content_hash": d2.content_hash},
    ]

    res1 = phase31_client.post(
        f"/api/soap/batches/{batch_id}/approve",
        json={"items": items},
        headers=KEY,
    )
    assert res1.status_code == 200
    # d1 成功，d2 出錯停在 approved
    assert store.get_soap_draft(d1.draft_id).state == STATE_QUEUED
    assert store.get_soap_draft(d2.draft_id).state == STATE_APPROVED

    monkeypatch.setattr(soap_review, "ensure_job", original_ensure)

    # 再次批次核准
    res2 = phase31_client.post(
        f"/api/soap/batches/{batch_id}/approve",
        json={"items": items},
        headers=KEY,
    )
    assert res2.status_code == 200

    assert store.get_soap_draft(d2.draft_id).state == STATE_QUEUED
    assert len(_get_his_push_jobs_for_draft(store, d1.draft_id)) == 1
    assert len(_get_his_push_jobs_for_draft(store, d2.draft_id)) == 1


def test_schema_migration_backward_compatible(tmp_path):
    """Test 6: 舊版本 schema（無 his_job_id 欄位）開啟後自動補欄位，資料不流失。"""
    db_file = tmp_path / "old_cases.sqlite3"
    conn = sqlite3.connect(str(db_file))
    # 建立舊版最小 schema
    conn.execute(
        """
        CREATE TABLE soap_drafts (
            draft_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            order_code TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            state TEXT NOT NULL,
            soap_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            quality_score INTEGER,
            quality_issues_json TEXT,
            comparison_json TEXT,
            reviewer_id TEXT,
            review_decision TEXT,
            review_reason TEXT,
            reviewed_at TEXT,
            pushed_at TEXT,
            agent_id TEXT,
            failure_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO soap_drafts (
            draft_id, case_id, version, state, soap_json, content_hash, created_at, updated_at
        ) VALUES (
            'old-draft-1', 'C-OLD-1', 1, 'validated', '{}', 'hash123', '2026-11-12T00:00:00', '2026-11-12T00:00:00'
        )
        """
    )
    conn.commit()
    conn.close()

    from elc_audit_engine.case_store import CaseStore
    store = CaseStore(str(db_file))
    draft = store.get_soap_draft("old-draft-1")
    assert draft is not None
    assert getattr(draft, "his_job_id", None) is None
    assert getattr(draft, "his_machine_id", None) is None
