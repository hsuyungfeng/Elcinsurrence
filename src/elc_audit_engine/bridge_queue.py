"""雲端與地端 Local Agent 橋接任務佇列（Phase 21-03）。

任務（Job）以 CaseStore 的 kind='bridge' 紀錄保存（持久化、與案件庫同一交易來源），狀態機：
    PENDING → SENDING → SUCCESS | FAILED

地端 Agent 輪詢 pending、下載 download_path 指向的檔案，呼叫 NHI_SendA／NHI_SendB 後回報
sLocal_ID、sNHI_ID 與 NHI_Query 狀態（如 A12 檔案已就緒、A99 已傳送完成）。
本模組不呼叫健保 DLL；實際傳輸與簽章由地端 Agent 負責。
"""

from __future__ import annotations

import re
import uuid

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

_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_PENDING: frozenset({STATUS_SENDING}),
    STATUS_SENDING: frozenset({STATUS_SUCCESS, STATUS_FAILED}),
}

_NHI_STATUS_RE = re.compile(r"^[A-Z]\d{2}$")


class BridgeValidationError(ValueError):
    """任務參數不合規（作業代號、目標、NHI_Query 格式）→ 422。"""


class BridgeConflictError(ValueError):
    """狀態轉換不被允許（例如已完成的任務再回報 SENDING）→ 409。"""


def download_path(s_type_code: str, target_id: str) -> str:
    """地端 Agent 取得待送內容的 API 路徑（相對於本服務）。"""
    if s_type_code == "15":
        return "/api/sampling/export-batch-xml"
    if s_type_code == "00":
        return f"/api/sampling/cases/{target_id}/export-package"
    # 07 申復 XML 與 09 申復預檢共用同一份申復批次檔（預檢不改內容，僅於回報時區分）
    return "/api/appeal/export-batch-xml"


def enqueue_job(store, *, s_type_code: str, target_id: str, actor: str | None = None) -> dict:
    """建立待送任務。作業代號必須為 S_TYPE_CODES 之一；target_id 不得為空。"""
    if s_type_code not in S_TYPE_CODES:
        raise BridgeValidationError(f"未知的作業代號：{s_type_code!r}（允許：{sorted(S_TYPE_CODES)}）")
    target = str(target_id or "").strip()
    if not target:
        raise BridgeValidationError("target_id 不得為空")
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
    }
    store.create(case_id=job_id, kind=BRIDGE_KIND, payload=payload, actor=actor)
    return payload


def get_job(store, job_id: str) -> dict:
    """讀取任務；非橋接紀錄一律視為查無（由呼叫端轉 404）。"""
    record = store.get(job_id)
    if record.kind != BRIDGE_KIND:
        raise LookupError(job_id)
    return dict(record.payload or {})


def list_pending(store, *, s_type_code: str | None = None, limit: int = 100) -> list[dict]:
    """待送任務（依建立時間升冪）。可依作業代號過濾；代號不合規拋 BridgeValidationError。"""
    if s_type_code is not None and s_type_code not in S_TYPE_CODES:
        raise BridgeValidationError(f"未知的作業代號：{s_type_code!r}")
    jobs = []
    for record in store.list_all(kind=BRIDGE_KIND, limit=1000):
        payload = dict(record.payload or {})
        if payload.get("status") != STATUS_PENDING:
            continue
        if s_type_code is not None and payload.get("s_type_code") != s_type_code:
            continue
        jobs.append(payload)
        if len(jobs) >= limit:
            break
    return jobs


def report_status(
    store,
    job_id: str,
    *,
    status: str,
    local_id: str | None = None,
    nhi_id: str | None = None,
    nhi_status: str | None = None,
    actor: str | None = None,
) -> dict:
    """地端 Agent 回報狀態。檢查狀態轉換與 NHI_Query 格式，欄位僅覆寫有值者。"""
    job = get_job(store, job_id)
    current = job["status"]
    if status not in _TRANSITIONS.get(current, frozenset()):
        raise BridgeConflictError(f"任務狀態不可由 {current} 轉為 {status}")
    if nhi_status is not None and not _NHI_STATUS_RE.match(nhi_status):
        raise BridgeValidationError("nhi_status（NHI_Query 狀態）格式須為一個大寫英文字母加兩位數字，如 A12")
    updated = {
        **job,
        "status": status,
        "local_id": local_id or job.get("local_id"),
        "nhi_id": nhi_id or job.get("nhi_id"),
        "nhi_status": nhi_status or job.get("nhi_status"),
    }
    store.update_payload(job_id, updated)
    return updated


__all__ = [
    "BRIDGE_KIND",
    "STATUS_FAILED",
    "STATUS_PENDING",
    "STATUS_SENDING",
    "STATUS_SUCCESS",
    "S_TYPE_CODES",
    "BridgeConflictError",
    "BridgeValidationError",
    "enqueue_job",
    "get_job",
    "list_pending",
    "report_status",
]
