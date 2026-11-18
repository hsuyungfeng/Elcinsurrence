"""Phase 29 檢查補強（Claude 檢查）：補上設計文件 §12 中 hermes 測試未明確涵蓋的 A5、A6。

- A5：Agent 認領後離線（租約逾時）→ 任務由佇列回收，可重新認領；超過重試上限則永久失敗。
- A6：草稿建立、審核與寫入流程不改變 Stage 2（sampling）案件的狀態。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from elc_audit_engine.bridge_queue import (
    STATUS_SENDING,
    enqueue_job,
    get_job,
    report_status,
    reclaim_expired,
)
from elc_audit_engine.case_store import CaseStore


@pytest.fixture
def store(tmp_path):
    return CaseStore(db_path=str(tmp_path / "cases.sqlite3"))


def _his_job(store, *, max_retries: int = 2) -> str:
    job = enqueue_job(
        store,
        s_type_code="HIS_PUSH",
        target_id="SAMP-A5-1",
        max_retries=max_retries,
    )
    return job["job_id"]


def test_a5_lease_expired_job_is_needs_review_and_never_redispatched(store):
    """WR-09：租約逾時 → NEEDS_REVIEW（不重新排隊、不可再認領，避免重複寫入 HIS）。"""
    from elc_audit_engine.bridge_queue import BridgeConflictError, STATUS_NEEDS_REVIEW

    job_id = _his_job(store, max_retries=3)
    report_status(store, job_id, status=STATUS_SENDING)
    job = get_job(store, job_id)
    from datetime import datetime

    later = datetime.fromisoformat(job["lease_started_at"]) + timedelta(seconds=job["lease_timeout_sec"] + 1)
    assert reclaim_expired(store, now=later) == 1
    job = get_job(store, job_id)
    assert job["status"] == STATUS_NEEDS_REVIEW
    with pytest.raises(BridgeConflictError):
        report_status(store, job_id, status=STATUS_SENDING)


def test_a6_draft_lifecycle_does_not_change_stage2_case_state(store):
    store.create(case_id="SAMP-A6-1", kind="sampling", payload={"id": "SAMP-A6-1"})
    before = store.get("SAMP-A6-1").state

    draft = store.create_soap_draft(
        case_id="SAMP-A6-1",
        soap={"s": "a", "o": "b", "a": "c", "p": "d"},
        state="validated",
        quality_score=95,
    )
    assert store.get("SAMP-A6-1").state == before

    # 醫師核准的狀態推進也不得改動 Stage 2 狀態
    from elc_audit_engine.case_store.soap_draft_states import STATE_APPROVED

    store.update_soap_draft_state(draft.draft_id, STATE_APPROVED, reviewer_id="dr-test")
    assert store.get("SAMP-A6-1").state == before
