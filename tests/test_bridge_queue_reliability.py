"""Phase 22-01 測試：橋接佇列 SQL 分頁過濾（P1-1）、租約逾時回收與重試上限、CAS 條件更新（P1-2）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from elc_audit_engine.bridge_queue import (
    DEFAULT_LEASE_TIMEOUT_SEC,
    STATUS_FAILED_PERMANENT,
    STATUS_PENDING,
    STATUS_SENDING,
    STATUS_SUCCESS,
    BridgeConflictError,
    enqueue_job,
    get_job,
    list_pending,
    reclaim_expired,
    report_status,
)
from elc_audit_engine.case_store import CaseStore

T0 = datetime(2026, 11, 3, 9, 0, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    return CaseStore(db_path=str(tmp_path / "bridge.sqlite3"))


def _job(store, code="15", target="MONTHLY-202307", **kwargs):
    return enqueue_job(store, s_type_code=code, target_id=target, **kwargs)


# ---------------------------------------------------------------- P1-1：SQL 層分頁過濾


def test_pending_job_beyond_old_1000_window_is_still_listed(store):
    """歷史紀錄超過 1000 筆時，較新的 PENDING 任務仍須被查出（舊實作會靜默丟件）。"""
    first_ids = [_job(store)["job_id"] for _ in range(1199)]
    for job_id in first_ids:
        report_status(store, job_id, status=STATUS_SENDING)
        report_status(store, job_id, status=STATUS_SUCCESS)
    target = _job(store)["job_id"]
    for _ in range(300):
        _job(store)

    pending = list_pending(store, limit=10_000, now=T0)
    ids = [job["job_id"] for job in pending]
    assert target in ids
    assert len(pending) == 301
    assert all(job["status"] == STATUS_PENDING for job in pending)


def test_list_pending_respects_limit_and_fifo_order(store):
    ids = [_job(store)["job_id"] for _ in range(5)]
    got = [job["job_id"] for job in list_pending(store, limit=3, now=T0)]
    assert got == ids[:3]


def test_list_pending_filters_by_s_type_code_in_sql(store):
    _job(store, "15", "M1")
    target = _job(store, "07", "APL-1")["job_id"]
    got = list_pending(store, s_type_code="07", now=T0)
    assert [job["job_id"] for job in got] == [target]


def test_pending_result_excludes_non_pending_jobs(store):
    job_id = _job(store)["job_id"]
    report_status(store, job_id, status=STATUS_SENDING, now=T0)
    assert list_pending(store, now=T0) == []


# ---------------------------------------------------------------- P1-2：租約與逾時回收


def test_claim_records_lease_start_and_timeout(store):
    job_id = _job(store)["job_id"]
    job = report_status(store, job_id, status=STATUS_SENDING, now=T0)
    assert job["lease_started_at"] == T0.isoformat()
    assert job["lease_timeout_sec"] == DEFAULT_LEASE_TIMEOUT_SEC == 900


def test_expired_sending_job_is_reclaimed_to_pending(store):
    job_id = _job(store)["job_id"]
    report_status(store, job_id, status=STATUS_SENDING, now=T0)

    # 未逾時：不回收
    assert reclaim_expired(store, now=T0 + timedelta(seconds=899)) == 0
    assert get_job(store, job_id)["status"] == STATUS_SENDING

    # 逾時：回收為 PENDING，遞增 retry_count，清空租約
    assert reclaim_expired(store, now=T0 + timedelta(seconds=900)) == 1
    job = get_job(store, job_id)
    assert job["status"] == STATUS_PENDING
    assert job["retry_count"] == 1
    assert job["lease_started_at"] is None
    assert "租約逾時" in job["last_error"]


def test_list_pending_reclaims_expired_lease_so_restarted_agent_can_claim(store):
    job_id = _job(store)["job_id"]
    report_status(store, job_id, status=STATUS_SENDING, now=T0)
    later = T0 + timedelta(seconds=DEFAULT_LEASE_TIMEOUT_SEC + 1)
    pending = list_pending(store, now=later)
    assert [job["job_id"] for job in pending] == [job_id]


def test_reclaimed_job_can_be_claimed_again(store):
    job_id = _job(store)["job_id"]
    report_status(store, job_id, status=STATUS_SENDING, now=T0)
    later = T0 + timedelta(seconds=1000)
    list_pending(store, now=later)  # 觸發回收
    job = report_status(store, job_id, status=STATUS_SENDING, now=later)
    assert job["status"] == STATUS_SENDING
    assert job["retry_count"] == 1


def test_sending_job_without_lease_is_treated_as_expired(store):
    """舊版資料沒有 lease_started_at，無法證明仍在傳送，應回收而非永久卡住。"""
    job_id = _job(store)["job_id"]
    payload = get_job(store, job_id)
    payload.update({"status": STATUS_SENDING, "lease_started_at": None})
    store.update_payload(job_id, payload)
    assert reclaim_expired(store, now=T0) == 1
    assert get_job(store, job_id)["status"] == STATUS_PENDING


# ---------------------------------------------------------------- P1-2：重試上限


def test_failed_report_requeues_until_max_retries_then_permanent(store):
    job_id = _job(store, max_retries=3)["job_id"]

    for attempt in range(1, 3):  # 第 1、2 次失敗：仍會重新排隊
        report_status(store, job_id, status=STATUS_SENDING, now=T0)
        job = report_status(store, job_id, status="FAILED", nhi_status="A12", now=T0)
        assert job["status"] == STATUS_PENDING
        assert job["retry_count"] == attempt
        assert job["nhi_status"] == "A12"

    # 第 3 次失敗：達上限，永久失敗
    report_status(store, job_id, status=STATUS_SENDING, now=T0)
    job = report_status(store, job_id, status="FAILED", now=T0)
    assert job["status"] == STATUS_FAILED_PERMANENT
    assert job["retry_count"] == 3


def test_permanently_failed_job_is_no_longer_dispatched(store):
    job_id = _job(store, max_retries=1)["job_id"]
    report_status(store, job_id, status=STATUS_SENDING, now=T0)
    report_status(store, job_id, status="FAILED", now=T0)
    assert get_job(store, job_id)["status"] == STATUS_FAILED_PERMANENT
    assert list_pending(store, now=T0 + timedelta(days=1)) == []


def test_expired_lease_counts_toward_max_retries(store):
    job_id = _job(store, max_retries=2)["job_id"]
    report_status(store, job_id, status=STATUS_SENDING, now=T0)
    reclaim_expired(store, now=T0 + timedelta(seconds=901))  # retry_count 1
    report_status(store, job_id, status=STATUS_SENDING, now=T0 + timedelta(seconds=902))
    reclaim_expired(store, now=T0 + timedelta(seconds=2000))  # retry_count 2 == max
    job = get_job(store, job_id)
    assert job["status"] == STATUS_FAILED_PERMANENT
    assert job["retry_count"] == 2


def test_max_retries_must_be_positive(store):
    from elc_audit_engine.bridge_queue import BridgeValidationError

    with pytest.raises(BridgeValidationError):
        _job(store, max_retries=0)


# ---------------------------------------------------------------- P1-2：CAS 條件更新


def test_second_claim_on_same_pending_job_conflicts(store):
    """兩個地端 Agent 同時看到 PENDING：先認領者成功，後者必須收到衝突。"""
    job_id = _job(store)["job_id"]
    snapshot = get_job(store, job_id)  # 後者讀到的舊快照
    report_status(store, job_id, status=STATUS_SENDING, now=T0)  # 先認領者

    with pytest.raises(BridgeConflictError):
        report_status(store, job_id, status=STATUS_SENDING, now=T0)
    assert snapshot["status"] == STATUS_PENDING  # 快照確實已過時


def test_expected_status_mismatch_is_conflict(store):
    job_id = _job(store)["job_id"]
    report_status(store, job_id, status=STATUS_SENDING, now=T0)
    with pytest.raises(BridgeConflictError):
        report_status(
            store, job_id, status=STATUS_SUCCESS, expected_status=STATUS_PENDING, now=T0
        )
    assert get_job(store, job_id)["status"] == STATUS_SENDING


def test_expected_status_match_allows_report(store):
    job_id = _job(store)["job_id"]
    report_status(store, job_id, status=STATUS_SENDING, now=T0)
    job = report_status(
        store, job_id, status=STATUS_SUCCESS, expected_status=STATUS_SENDING, now=T0
    )
    assert job["status"] == STATUS_SUCCESS


def test_stale_agent_cannot_overwrite_after_lease_was_reclaimed_and_reclaimed_again(store):
    """舊 Agent 的 lease 已被回收並由新 Agent 重新認領後，舊 Agent 的回報必須被拒絕（ABA 防護）。"""
    job_id = _job(store)["job_id"]
    report_status(store, job_id, status=STATUS_SENDING, now=T0)  # 舊 Agent 認領
    stale = get_job(store, job_id)

    later = T0 + timedelta(seconds=1000)
    list_pending(store, now=later)  # 回收
    report_status(store, job_id, status=STATUS_SENDING, now=later)  # 新 Agent 認領

    # 舊 Agent 依舊快照（status=SENDING、lease=T0）寫入 SUCCESS：status 雖相同，lease 已不同，必須失敗
    stale_success = {**stale, "status": STATUS_SUCCESS}
    assert store.cas_update_payload(
        job_id,
        stale_success,
        expect={"status": STATUS_SENDING, "lease_started_at": T0.isoformat()},
    ) is False
    current = get_job(store, job_id)
    assert current["status"] == STATUS_SENDING
    assert current["lease_started_at"] == later.isoformat()


def test_cas_update_payload_returns_false_on_mismatch_and_missing_case(store):
    job_id = _job(store)["job_id"]
    payload = get_job(store, job_id)
    assert store.cas_update_payload(job_id, {**payload, "local_id": "X"}, expect={"status": "SENDING"}) is False
    assert store.cas_update_payload("NO-SUCH-JOB", payload, expect={"status": "PENDING"}) is False
    assert store.cas_update_payload(job_id, {**payload, "local_id": "Y"}, expect={"status": "PENDING"}) is True
    assert get_job(store, job_id)["local_id"] == "Y"


def test_cas_update_payload_rejects_unsafe_key(store):
    job_id = _job(store)["job_id"]
    payload = get_job(store, job_id)
    with pytest.raises(ValueError):
        store.cas_update_payload(job_id, payload, expect={"status') OR 1=1 --": "x"})


def test_cas_update_payload_null_expectation_matches_sql_null(store):
    job_id = _job(store)["job_id"]
    payload = get_job(store, job_id)
    assert store.cas_update_payload(
        job_id, {**payload, "local_id": "Z"}, expect={"lease_started_at": None}
    ) is True

