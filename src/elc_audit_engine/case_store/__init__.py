"""案件狀態機與 SQLite 持久化子套件（純資料層）。

**不含任何 Flask／LLM 依賴**——本子套件只負責「案件在哪個狀態、如何合法
轉換、轉換歷史是什麼」，不處理 HTTP 請求也不呼叫語言模型。端點接線由
09-03（本 plan 刻意不動 `server.py`）負責，讓本 plan 可與 09-01（認證）
並行執行。

任務佇列採**同步版**：狀態欄位即佇列，以「查詢處於某狀態的案件」
（`CaseStore.list_by_state`）實現，不引入 Celery／Redis（單機部署，
09-CONTEXT.md 決策）。
"""

from elc_audit_engine.case_store.states import (
    ALL_STATES,
    STATE_APPEALED,
    STATE_FAILED,
    STATE_IMPORTED,
    STATE_PARSED,
    STATE_REVIEWED,
    STATE_REVIEWING,
    STATE_SUBMITTED,
    IllegalTransitionError,
    UnknownStateError,
    allowed_targets,
    assert_transition_allowed,
    can_transition,
    requires_reason,
)

__all__ = [
    "ALL_STATES",
    "STATE_IMPORTED",
    "STATE_PARSED",
    "STATE_REVIEWING",
    "STATE_REVIEWED",
    "STATE_APPEALED",
    "STATE_SUBMITTED",
    "STATE_FAILED",
    "IllegalTransitionError",
    "UnknownStateError",
    "allowed_targets",
    "can_transition",
    "assert_transition_allowed",
    "requires_reason",
]
