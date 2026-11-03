"""雲端與地端 Local Agent 橋接任務佇列（Phase 21-03，Phase 22-01 可靠性強化）。

任務（Job）以 CaseStore 的 kind='bridge' 紀錄保存（持久化、與案件庫同一交易來源），狀態機：

    PENDING ──claim──▶ SENDING ──SUCCESS（終態）
       ▲                  │
       │                  ├── 回報 FAILED，且 retry_count < max_retries ──▶ PENDING（重新排隊）
       │                  ├── 回報 FAILED，且 retry_count >= max_retries ──▶ FAILED_PERMANENT（終態）
       └── 租約逾時回收 ───┘（同上規則：未超過上限回 PENDING，超過上限為 FAILED_PERMANENT）

Phase 22-01 強化重點：
- 待送清單改在 SQL 層以 `json_extract(payload_json, '$.status')` 篩選與分頁，不再掃描最舊的
  1000 筆（P1-1）。歷史紀錄再多，較新的 PENDING 任務也不會被靜默丟棄。
- 進入 SENDING 時記錄 `lease_started_at` 與 `lease_timeout_sec`（預設 900 秒）。租約逾時的
  任務於下次輪詢時自動回收，讓重啟後的地端 Agent 能重新認領（P1-2）。
- `retry_count` 與 `max_retries`（預設 3）限制重試次數，超過上限即永久失敗，不再重複派發。
- 所有狀態變更皆為 Compare-And-Swap：比對 status 與 lease_started_at 未被改動才寫入，
  競態下只有一方成功，另一方收到 `BridgeConflictError`（對應 HTTP 409）（P1-2）。

本模組不呼叫健保 DLL；實際傳輸與簽章由地端 Agent 負責。
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

BRIDGE_KIND = "bridge"

# 健保作業種類代號（電子抽審.md §四）。
S_TYPE_CODES: dict[str, str] = {
    "15": "費用抽審 XML 批次上傳",
    "00": "專業審查病歷影像",
    "07": "醫療費用電子申復資料",
    "09": "申復預檢",
}

STATUS_PENDING = "PENDING"
STATUS_SENDING = "SENDING"
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
# 重試次數用盡後的終態；不再出現在待送清單中。
STATUS_FAILED_PERMANENT = "FAILED_PERMANENT"

# 租約預設 15 分鐘；超過即視為地端 Agent 已當機，任務可被回收重派。
DEFAULT_LEASE_TIMEOUT_SEC = 900
# 單一任務最多嘗試次數（含首次）上限的預設值，超過即永久失敗。
DEFAULT_MAX_RETRIES = 3

# 地端 Agent 可主動回報的轉換；PENDING→SENDING 為認領，SENDING→PENDING 僅能由系統回收。
_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_PENDING: frozenset({STATUS_SENDING}),
    STATUS_SENDING: frozenset({STATUS_SUCCESS, STATUS_FAILED}),
}

_NHI_STATUS_RE = re.compile(r"^[A-Z]\d{2}$")


class BridgeValidationError(ValueError):
    """任務參數不合規（作業代號、目標、NHI_Query 格式）→ 422。"""


class BridgeConflictError(ValueError):
    """狀態轉換不被允許，或 CAS 比對失敗（併發改動）→ 409。"""


def download_path(s_type_code: str, target_id: str) -> str:
    """地端 Agent 取得待送內容的 API 路徑（相對於本服務）。"""
    if s_type_code == "15":
        return "/api/sampling/export-batch-xml"
    if s_type_code == "00":
        return f"/api/sampling/cases/{target_id}/export-package"
    # 07 申復 XML 與 09 申復預檢共用同一份申復批次檔（預檢不改內容，僅於回報時區分）
    return "/api/appeal/export-batch-xml"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def enqueue_job(
    store,
    *,
    s_type_code: str,
    target_id: str,
    actor: str | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict:
    """建立待送任務。作業代號必須為 S_TYPE_CODES 之一；target_id 不得為空；max_retries 至少為 1。"""
    if s_type_code not in S_TYPE_CODES:
        raise BridgeValidationError(f"未知的作業代號：{s_type_code!r}（允許：{sorted(S_TYPE_CODES)}）")
    target = str(target_id or "").strip()
    if not target:
        raise BridgeValidationError("target_id 不得為空")
    if max_retries < 1:
        raise BridgeValidationError("max_retries 至少為 1")
    job_id = uuid.uuid4().hex
    payload = {
        "job_id": job_id,
        "s_type_code": s_type_code,
        "s_type_name": S_TYPE_CODES[s_type_code],
        "target_id": target,
        "status": STATUS_PENDING,
        "local_id": None,
        "nhi_id": None,
        "nhi_status": None,
        "download_path": download_path(s_type_code, target),
        "retry_count": 0,
        "max_retries": max_retries,
        "lease_started_at": None,
        "lease_timeout_sec": None,
        "last_error": None,
    }
    store.create(case_id=job_id, kind=BRIDGE_KIND, payload=payload, actor=actor)
    return payload


def get_job(store, job_id: str) -> dict:
    """讀取任務；非橋接紀錄一律視為查無（由呼叫端轉 404）。"""
    record = store.get(job_id)
    if record.kind != BRIDGE_KIND:
        raise LookupError(job_id)
    return dict(record.payload or {})


def _lease_expired(job: dict, now: datetime) -> bool:
    """SENDING 任務的租約是否已逾時。缺少 lease_started_at（舊資料）視為無法證明仍在傳送，故回收。"""
    started_raw = job.get("lease_started_at")
    if not started_raw:
        return True
    started = datetime.fromisoformat(started_raw)
    timeout = int(job.get("lease_timeout_sec") or DEFAULT_LEASE_TIMEOUT_SEC)
    return now >= started + timedelta(seconds=timeout)


def _requeue_or_fail(job: dict, *, reason: str) -> dict:
    """失敗或逾時的共用規則：遞增 retry_count，未達上限回 PENDING，達上限為 FAILED_PERMANENT。"""
    retries = int(job.get("retry_count") or 0) + 1
    max_retries = int(job.get("max_retries") or DEFAULT_MAX_RETRIES)
    status = STATUS_FAILED_PERMANENT if retries >= max_retries else STATUS_PENDING
    return {
        **job,
        "status": status,
        "retry_count": retries,
        "lease_started_at": None,
        "lease_timeout_sec": None,
        "last_error": reason,
    }


def _compare_and_swap(store, job_id: str, expected: dict, new_payload: dict) -> bool:
    """以 status 與 lease_started_at 作為期望值寫入；任一被併發改動即回傳 False。

    lease_started_at 一併比對，避免「舊的地端 Agent 在租約被回收後才回報」覆寫新的認領。
    """
    return store.cas_update_payload(
        job_id,
        new_payload,
        expect={
            "status": expected["status"],
            "lease_started_at": expected.get("lease_started_at"),
        },
    )


def reclaim_expired(store, *, now: datetime | None = None) -> int:
    """回收租約逾時的 SENDING 任務；回傳成功回收的筆數。

    每筆以 CAS 寫入，併發的其他回收或回報若已改動任務則略過，不會重複計數。
    """
    now = now or _utc_now()
    reclaimed = 0
    for record in store.list_bridge_jobs(status=STATUS_SENDING, limit=10_000):
        job = dict(record.payload or {})
        if not _lease_expired(job, now):
            continue
        new_payload = _requeue_or_fail(job, reason="租約逾時，任務已由系統回收")
        if _compare_and_swap(store, job["job_id"], job, new_payload):
            reclaimed += 1
    return reclaimed


def list_pending(
    store,
    *,
    s_type_code: str | None = None,
    limit: int = 100,
    now: datetime | None = None,
) -> list[dict]:
    """待送任務（依建立時間升冪）。先回收逾時租約，再於 SQL 層篩選。代號不合規拋 BridgeValidationError。"""
    if s_type_code is not None and s_type_code not in S_TYPE_CODES:
        raise BridgeValidationError(f"未知的作業代號：{s_type_code!r}")
    reclaim_expired(store, now=now)
    records = store.list_bridge_jobs(
        status=STATUS_PENDING, s_type_code=s_type_code, limit=limit
    )
    return [dict(record.payload or {}) for record in records]


def report_status(
    store,
    job_id: str,
    *,
    status: str,
    local_id: str | None = None,
    nhi_id: str | None = None,
    nhi_status: str | None = None,
    actor: str | None = None,
    expected_status: str | None = None,
    now: datetime | None = None,
) -> dict:
    """地端 Agent 回報狀態。

    - `expected_status`：可選。地端 Agent 若預期任務目前狀態，不符即回 409，避免依據過時資料回報。
    - 狀態轉換不合法、或 CAS 比對失敗（併發改動）皆拋 BridgeConflictError。
    - 回報 FAILED 會依 retry_count／max_retries 決定重新排隊或永久失敗。
    """
    job = get_job(store, job_id)
    current = job["status"]
    if expected_status is not None and expected_status != current:
        raise BridgeConflictError(
            f"任務目前為 {current}，與預期的 {expected_status} 不符，請重新讀取後再回報"
        )
    if status not in _TRANSITIONS.get(current, frozenset()):
        raise BridgeConflictError(f"任務狀態不可由 {current} 轉為 {status}")
    if nhi_status is not None and not _NHI_STATUS_RE.match(nhi_status):
        raise BridgeValidationError("nhi_status（NHI_Query 狀態）格式須為一個大寫英文字母加兩位數字，如 A12")

    now = now or _utc_now()
    if status == STATUS_SENDING:
        updated = {
            **job,
            "status": STATUS_SENDING,
            "lease_started_at": now.isoformat(),
            "lease_timeout_sec": DEFAULT_LEASE_TIMEOUT_SEC,
        }
    elif status == STATUS_FAILED:
        updated = _requeue_or_fail(
            job, reason=f"地端回報失敗（NHI_Query={nhi_status or '未提供'}）"
        )
    else:
        updated = {
            **job,
            "status": STATUS_SUCCESS,
            "lease_started_at": None,
            "lease_timeout_sec": None,
        }
    updated.update(
        {
            "local_id": local_id or job.get("local_id"),
            "nhi_id": nhi_id or job.get("nhi_id"),
            "nhi_status": nhi_status or job.get("nhi_status"),
        }
    )

    if not _compare_and_swap(store, job_id, job, updated):
        raise BridgeConflictError("任務已被其他程序更新，請重新讀取後再回報")
    return updated


__all__ = [
    "BRIDGE_KIND",
    "DEFAULT_LEASE_TIMEOUT_SEC",
    "DEFAULT_MAX_RETRIES",
    "STATUS_FAILED",
    "STATUS_FAILED_PERMANENT",
    "STATUS_PENDING",
    "STATUS_SENDING",
    "STATUS_SUCCESS",
    "S_TYPE_CODES",
    "BridgeConflictError",
    "BridgeValidationError",
    "enqueue_job",
    "get_job",
    "list_pending",
    "reclaim_expired",
    "report_status",
]
