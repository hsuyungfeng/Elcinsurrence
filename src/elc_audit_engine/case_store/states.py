"""案件狀態機：狀態集合＋顯式轉換表＋非法轉換例外。

**採「顯式轉換表」而非「列舉方法（每個狀態一個 `advance_to_x()` 方法）」**：
轉換表可被測試直接遍歷（`_TRANSITIONS.keys() == ALL_STATES`），新增狀態時
若忘記把它加入轉換表，測試會直接抓到；列舉方法則要逐一檢查每個方法是否
涵蓋新狀態，容易漏網。

延續本專案核心原則（P1-1／P0-2／P1-3 同源）：**系統故障必須與業務結論
可區分，不得靜默產生看似正常的結果**。套用到狀態機：
- 未知狀態（不在 `ALL_STATES` 內）是系統性錯誤，必須拋例外，
  **絕不能回傳 `False`**——回 `False` 會讓「這個狀態根本不存在」偽裝成
  「業務上不允許這樣轉換」，兩者性質完全不同，混在一起會讓呼叫端無法
  正確處理（前者該當機停止，後者該回應使用者「操作不允許」）。
- 非法轉換必須拋 `IllegalTransitionError`，不得靜默允許或降級為忽略。
"""

from __future__ import annotations

# 七個狀態的字串值即為 SQLite 持久化值，**不可日後改動**——改動會讓既有
# 資料庫內已寫入的歷史紀錄與新程式碼的狀態常數對不上，等同於一次隱性
# 資料損毀。若日後需要調整顯示名稱，另建對照表，不要動這裡的字串值。
STATE_IMPORTED = "imported"
STATE_PARSED = "parsed"
STATE_REVIEWING = "reviewing"
STATE_REVIEWED = "reviewed"
STATE_APPEALED = "appealed"
STATE_SUBMITTED = "submitted"
# 旁支：任一主線狀態皆可轉入 failed（系統性故障），與業務結論分開記錄
# （失敗原因存於 case_store.db 的 `cases.failure_reason` 欄，而非本模組
# 關心的範圍——本模組只管「狀態轉換是否合法」）。
STATE_FAILED = "failed"

ALL_STATES: frozenset[str] = frozenset(
    {
        STATE_IMPORTED,
        STATE_PARSED,
        STATE_REVIEWING,
        STATE_REVIEWED,
        STATE_APPEALED,
        STATE_SUBMITTED,
        STATE_FAILED,
    }
)

# 顯式轉換表：鍵為來源狀態，值為該狀態可合法轉入的目標狀態集合。
# 鍵集合必須恰為 ALL_STATES（測試以遍歷斷言鎖定，見 test_case_states.py）。
_TRANSITIONS: dict[str, frozenset[str]] = {
    # D-01：appeal 案件生成申復草稿即視為完成申復——imported 案件可直接達 appealed。
    # 此邊唯一的 server 呼叫點在 /api/appeal/generate（transition(case_id, "appealed")），
    # sampling 案件走 parsed/reviewing/reviewed 邊、不觸發該呼叫，故不污染預審流語義。
    STATE_IMPORTED: frozenset({STATE_PARSED, STATE_FAILED, STATE_APPEALED}),
    STATE_PARSED: frozenset({STATE_REVIEWING, STATE_FAILED}),
    STATE_REVIEWING: frozenset({STATE_REVIEWED, STATE_FAILED}),
    # reviewed 為預審流程終點；若進入申復流程則續行至 appealed。
    STATE_REVIEWED: frozenset({STATE_APPEALED, STATE_FAILED}),
    STATE_APPEALED: frozenset({STATE_SUBMITTED, STATE_FAILED}),
    # submitted 為封閉終態，**不可再轉出**——含不可回 imported（CONTEXT
    # 明示的具體反例：申報後不可假裝「重新匯入」抹掉既有申報事實）。
    STATE_SUBMITTED: frozenset(),
    # 允許人工排除故障後重試，回到失敗前所在的階段；**不含 submitted**——
    # 已上傳的案件不可由 failed 狀態直接「宣告完成」，必須走正常主線。
    STATE_FAILED: frozenset(
        {
            STATE_IMPORTED,
            STATE_PARSED,
            STATE_REVIEWING,
            STATE_REVIEWED,
            STATE_APPEALED,
        }
    ),
}


class IllegalTransitionError(ValueError):
    """狀態轉換不在顯式轉換表允許的邊內。"""

    def __init__(self, from_state: str, to_state: str, allowed: frozenset[str]):
        self.from_state = from_state
        self.to_state = to_state
        self.allowed = allowed
        super().__init__(
            f"非法狀態轉換：{from_state} → {to_state}（允許：{sorted(allowed)}）"
        )


class UnknownStateError(ValueError):
    """狀態值不在 ALL_STATES 內——系統性錯誤，非「業務上不允許」。"""


def allowed_targets(from_state: str) -> frozenset[str]:
    """回傳 `from_state` 可合法轉入的目標狀態集合。

    Raises:
        UnknownStateError: `from_state` 不在 `ALL_STATES` 內。
    """
    if from_state not in ALL_STATES:
        raise UnknownStateError(f"未知狀態：{from_state!r}（允許：{sorted(ALL_STATES)}）")
    return _TRANSITIONS[from_state]


def can_transition(from_state: str, to_state: str) -> bool:
    """判斷 `from_state` → `to_state` 是否為合法轉換。

    兩端狀態只要有一個不在 `ALL_STATES` 內，一律拋 `UnknownStateError`，
    **不得回傳 `False`**——未知狀態是系統性故障，回 `False` 會讓它偽裝成
    「業務上不允許」，正是本專案反覆踩到、必須避免的坑（P1-1／P0-2 同源）。
    """
    if to_state not in ALL_STATES:
        raise UnknownStateError(f"未知狀態：{to_state!r}（允許：{sorted(ALL_STATES)}）")
    # allowed_targets 已對 from_state 做未知狀態檢查
    return to_state in allowed_targets(from_state)


def assert_transition_allowed(from_state: str, to_state: str) -> None:
    """`from_state` → `to_state` 非法時拋 `IllegalTransitionError`。

    Raises:
        UnknownStateError: 任一端狀態不在 `ALL_STATES` 內。
        IllegalTransitionError: 轉換不在允許的邊內。
    """
    if not can_transition(from_state, to_state):
        raise IllegalTransitionError(from_state, to_state, allowed_targets(from_state))


def requires_reason(to_state: str) -> bool:
    """僅轉入 `STATE_FAILED` 時回傳 True——轉入 failed 必須附失敗原因。"""
    return to_state == STATE_FAILED
