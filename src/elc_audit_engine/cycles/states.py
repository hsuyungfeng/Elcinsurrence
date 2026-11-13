"""Phase 31: 循環狀態機純函式與轉換檢查 (契約 §4, §5).

注意：本模組為純函式與常數定義，不依賴 Flask、資料庫或任何 I/O。
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Optional, Tuple

STATE_RECORDING = "RECORDING"
STATE_AWAITING_DRAFT = "AWAITING_DRAFT"
STATE_AWAITING_CONFIRM = "AWAITING_CONFIRM"
STATE_DRAFT_UNUSABLE = "DRAFT_UNUSABLE"
STATE_CONFIRMED = "CONFIRMED"
STATE_ARCHIVING = "ARCHIVING"
STATE_ARCHIVE_FAILED = "ARCHIVE_FAILED"
STATE_ARCHIVED = "ARCHIVED"
STATE_ABANDONED = "ABANDONED"

ALL_CYCLE_STATES: Tuple[str, ...] = (
    STATE_RECORDING,
    STATE_AWAITING_DRAFT,
    STATE_AWAITING_CONFIRM,
    STATE_DRAFT_UNUSABLE,
    STATE_CONFIRMED,
    STATE_ARCHIVING,
    STATE_ARCHIVE_FAILED,
    STATE_ARCHIVED,
    STATE_ABANDONED,
)

TERMINAL_STATES: FrozenSet[str] = frozenset({STATE_ARCHIVED, STATE_ABANDONED})
ACTIVE_STATES: FrozenSet[str] = frozenset(set(ALL_CYCLE_STATES) - TERMINAL_STATES)

_CYCLE_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    STATE_RECORDING: (STATE_AWAITING_DRAFT, STATE_ABANDONED),
    STATE_AWAITING_DRAFT: (STATE_AWAITING_CONFIRM, STATE_DRAFT_UNUSABLE, STATE_ABANDONED),
    STATE_AWAITING_CONFIRM: (STATE_CONFIRMED, STATE_DRAFT_UNUSABLE, STATE_ABANDONED),
    STATE_DRAFT_UNUSABLE: (STATE_AWAITING_CONFIRM, STATE_CONFIRMED, STATE_ABANDONED),
    STATE_CONFIRMED: (STATE_ARCHIVING, STATE_ARCHIVED, STATE_ARCHIVE_FAILED),
    STATE_ARCHIVING: (STATE_ARCHIVING, STATE_ARCHIVED, STATE_ARCHIVE_FAILED),
    STATE_ARCHIVE_FAILED: (STATE_ARCHIVING, STATE_ARCHIVED),
    STATE_ARCHIVED: (),
    STATE_ABANDONED: (),
}


class CycleStateError(Exception):
    """循環狀態錯誤基底。"""


class UnknownCycleStateError(CycleStateError):
    """傳入未定義的循環狀態名稱。"""

    def __init__(self, state: str):
        super().__init__(f"未知的循環狀態：{state!r}")
        self.state = state


class IllegalCycleTransitionError(CycleStateError):
    """嘗試執行不合法的循環狀態轉換。"""

    def __init__(self, from_state: str, to_state: str):
        super().__init__(f"不合法的循環狀態轉換：{from_state} -> {to_state}")
        self.from_state = from_state
        self.to_state = to_state


def assert_cycle_transition(from_state: str, to_state: str) -> None:
    """斷言循環狀態轉換合法性；若非法則拋出例外。"""
    if from_state not in ALL_CYCLE_STATES:
        raise UnknownCycleStateError(from_state)
    if to_state not in ALL_CYCLE_STATES:
        raise UnknownCycleStateError(to_state)
    allowed = _CYCLE_TRANSITIONS.get(from_state, ())
    if to_state not in allowed:
        raise IllegalCycleTransitionError(from_state, to_state)


def display_state(
    cycle_state: Optional[str] = None,
    last_cycle_state: Optional[str] = None,
    online: bool = True,
) -> str:
    """計算監控顯示狀態（契約 §5，中文）。

    判定順序：
    1. 離線優先：not online → "離線"
    2. RECORDING → "錄音中"
    3. AWAITING_DRAFT / AWAITING_CONFIRM / DRAFT_UNUSABLE / CONFIRMED / ARCHIVING / ARCHIVE_FAILED → "待確認"
    4. 無未終結循環且最近一個循環為 ARCHIVED → "已封存"
    5. 其他 → "待命"
    """
    if not online:
        return "離線"

    if cycle_state == STATE_RECORDING:
        return "錄音中"

    if cycle_state in (
        STATE_AWAITING_DRAFT,
        STATE_AWAITING_CONFIRM,
        STATE_DRAFT_UNUSABLE,
        STATE_CONFIRMED,
        STATE_ARCHIVING,
        STATE_ARCHIVE_FAILED,
    ):
        return "待確認"

    if (cycle_state is None or cycle_state in TERMINAL_STATES) and last_cycle_state == STATE_ARCHIVED:
        return "已封存"

    return "待命"
