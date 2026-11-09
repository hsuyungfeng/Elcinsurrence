"""SOAP 草稿狀態機與內容雜湊（Phase 29）。

狀態機設計（29-DESIGN.md §4）：
    draft ──validate(pass)──▶ validated ──compare(advisory)──▶ validated
      │                          │
      │                          ├── physician approve ──▶ approved ──enqueue HIS_PUSH──▶ queued ──agent ok──▶ pushed（終態）
      │                          │                                                        └──agent fail──▶ failed（可重試）
      │                          └── physician reject ──▶ rejected（終態）
      └── validate(fail) ──▶ quality_failed（終態／重生成）

原則（與 states.py 同源）：
- 未知狀態拋 UnknownDraftStateError，絕不靜默略過。
- 非法轉換拋 IllegalDraftTransitionError，不得靜默忽略。
- content_hash 為正規化 S/O/A/P 文字之 SHA-256，用以鎖定審核版本與防竄改。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

STATE_DRAFT = "draft"
STATE_VALIDATED = "validated"
STATE_QUALITY_FAILED = "quality_failed"
STATE_APPROVED = "approved"
STATE_QUEUED = "queued"
STATE_PUSHED = "pushed"
STATE_REJECTED = "rejected"
STATE_FAILED = "failed"

ALL_DRAFT_STATES: frozenset[str] = frozenset(
    {
        STATE_DRAFT,
        STATE_VALIDATED,
        STATE_QUALITY_FAILED,
        STATE_APPROVED,
        STATE_QUEUED,
        STATE_PUSHED,
        STATE_REJECTED,
        STATE_FAILED,
    }
)

TERMINAL_DRAFT_STATES: frozenset[str] = frozenset(
    {
        STATE_PUSHED,
        STATE_REJECTED,
        STATE_QUALITY_FAILED,
    }
)

_DRAFT_TRANSITIONS: dict[str, frozenset[str]] = {
    STATE_DRAFT: frozenset({STATE_VALIDATED, STATE_QUALITY_FAILED}),
    # validated 可經醫師審核 approve／reject，或經 edit 重新檢核留在 validated 或降為 quality_failed
    STATE_VALIDATED: frozenset({STATE_APPROVED, STATE_REJECTED, STATE_VALIDATED, STATE_QUALITY_FAILED}),
    # approved 後排入 HIS_PUSH 任務進入 queued；醫師亦可撤回/退回
    STATE_APPROVED: frozenset({STATE_QUEUED, STATE_REJECTED}),
    # queued 待 Agent 寫入，成功達 pushed，失敗達 failed
    STATE_QUEUED: frozenset({STATE_PUSHED, STATE_FAILED}),
    # failed 允許重試（重新排隊 queued 或由醫師重新核准/退回）
    STATE_FAILED: frozenset({STATE_QUEUED, STATE_APPROVED, STATE_REJECTED}),
    # 終態不可轉出
    STATE_PUSHED: frozenset(),
    STATE_REJECTED: frozenset(),
    STATE_QUALITY_FAILED: frozenset(),
}


class SoapDraftStateError(Exception):
    """SOAP 草稿狀態例外基底類別。"""


class UnknownDraftStateError(SoapDraftStateError):
    """未知的 SOAP 草稿狀態。"""

    def __init__(self, state: str):
        super().__init__(f"未知的 SOAP 草稿狀態：{state!r}（允許狀態：{sorted(ALL_DRAFT_STATES)}）")
        self.state = state


class IllegalDraftTransitionError(SoapDraftStateError):
    """不允許的 SOAP 草稿狀態轉換。"""

    def __init__(self, from_state: str, to_state: str):
        super().__init__(f"不合法的 SOAP 草稿狀態轉換：{from_state!r} -> {to_state!r}")
        self.from_state = from_state
        self.to_state = to_state


def is_transition_allowed(from_state: str, to_state: str) -> bool:
    """檢查狀態轉換是否合法。"""
    if from_state not in ALL_DRAFT_STATES:
        raise UnknownDraftStateError(from_state)
    if to_state not in ALL_DRAFT_STATES:
        raise UnknownDraftStateError(to_state)
    return to_state in _DRAFT_TRANSITIONS[from_state]


def assert_draft_transition_allowed(from_state: str, to_state: str) -> None:
    """斷言狀態轉換合法，否則拋出例外。"""
    if not is_transition_allowed(from_state, to_state):
        raise IllegalDraftTransitionError(from_state, to_state)


def canonical_soap_text(soap_dict: Any) -> str:
    """將 S/O/A/P 字典正規化為確定性字串，用於雜湊計算與一致性比對。
    
    規格：
    - 鍵為 's', 'o', 'a', 'p'
    - 各欄位統一換行符（\\r\\n -> \\n）並去除首尾空白
    - 固定順序輸出
    """
    if not isinstance(soap_dict, dict):
        return ""
    s = str(soap_dict.get("s") or "").replace("\r\n", "\n").strip()
    o = str(soap_dict.get("o") or "").replace("\r\n", "\n").strip()
    a = str(soap_dict.get("a") or "").replace("\r\n", "\n").strip()
    p = str(soap_dict.get("p") or "").replace("\r\n", "\n").strip()
    return f"S:\n{s}\nO:\n{o}\nA:\n{a}\nP:\n{p}"


def compute_soap_content_hash(soap_dict: Any) -> str:
    """計算正規化 SOAP 內容的 SHA-256 雜湊字串（十六進制 64 碼）。"""
    canonical = canonical_soap_text(soap_dict)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
