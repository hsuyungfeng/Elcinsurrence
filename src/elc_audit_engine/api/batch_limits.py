"""批次讀取上限與截斷揭露（Phase 22-02，P1-10）。

CaseStore.list_all 單次最多讀取 BATCH_READ_LIMIT 筆。若直接使用，超過上限的案件會被靜默丟棄，
呼叫端會誤以為資料庫只有這麼多筆。本模組統一做法：

- JSON 批次端點：回傳 total／returned／truncated／limit，讓呼叫端知道結果是否不完整。
- 非 JSON 產出（送審 XML、HTML 報告）：若截斷則直接拒絕（409），因為不完整的送審檔或報告
  比沒有更危險，必須明確告知分批處理。
"""

from __future__ import annotations

from .errors import ApiError

from elc_audit_engine.services.batch_reads import BATCH_READ_LIMIT, read_batch  # noqa: E402,F401


def refuse_if_truncated(meta: dict, *, what: str) -> None:
    """非 JSON 產出遇截斷即拒絕（409），訊息點出實際筆數與上限。"""
    if meta["truncated"]:
        raise ApiError(
            f"{what}共 {meta['total']} 筆，超過單次上限 {meta['limit']} 筆；"
            "為避免產出不完整的檔案或報告，已拒絕執行，請分批處理。",
            status=409,
        )
