"""案件狀態機轉換表純函式測試（合法／非法／failed 旁支）。

鎖定核心原則：非法轉換與未知狀態皆拋例外，**不得**靜默回傳 `False`
或允許非法轉換通過（P1-1／P0-2 同源：系統故障必須與業務結論可區分）。
"""

import pytest

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
    _TRANSITIONS,
    allowed_targets,
    assert_transition_allowed,
    can_transition,
    requires_reason,
)

_MAIN_LINE = [
    (STATE_IMPORTED, STATE_PARSED),
    (STATE_PARSED, STATE_REVIEWING),
    (STATE_REVIEWING, STATE_REVIEWED),
    (STATE_REVIEWED, STATE_APPEALED),
    (STATE_APPEALED, STATE_SUBMITTED),
]


def test_all_states_has_exactly_seven_values():
    assert len(ALL_STATES) == 7
    assert ALL_STATES == {
        STATE_IMPORTED,
        STATE_PARSED,
        STATE_REVIEWING,
        STATE_REVIEWED,
        STATE_APPEALED,
        STATE_SUBMITTED,
        STATE_FAILED,
    }


def test_transitions_keys_equal_all_states():
    """遍歷斷言：任何新增狀態若忘記加入轉換表，本測試會直接抓到。"""
    assert set(_TRANSITIONS.keys()) == ALL_STATES


def test_transitions_targets_all_within_all_states():
    """轉換表所有目標值皆屬 ALL_STATES（無指向未定義狀態的邊）。"""
    for from_state, targets in _TRANSITIONS.items():
        assert targets.issubset(ALL_STATES), f"{from_state} 轉換表含未定義目標：{targets - ALL_STATES}"


@pytest.mark.parametrize("from_state,to_state", _MAIN_LINE)
def test_main_line_transitions_are_legal(from_state, to_state):
    assert can_transition(from_state, to_state) is True


@pytest.mark.parametrize("state", sorted(ALL_STATES - {STATE_SUBMITTED, STATE_FAILED}))
def test_every_non_submitted_state_can_transition_to_failed(state):
    """遍歷斷言：每個非 submitted、非 failed 本身的狀態都能轉入 failed。"""
    assert can_transition(state, STATE_FAILED) is True


def test_submitted_to_imported_raises_illegal_transition():
    """CONTEXT 明示的具體案例：submitted → imported 不可。"""
    with pytest.raises(IllegalTransitionError):
        assert_transition_allowed(STATE_SUBMITTED, STATE_IMPORTED)


@pytest.mark.parametrize("to_state", sorted(ALL_STATES - {STATE_SUBMITTED}))
def test_submitted_to_any_other_state_raises_illegal_transition(to_state):
    """遍歷斷言終態封閉：submitted 不可轉往任何其他狀態。"""
    with pytest.raises(IllegalTransitionError):
        assert_transition_allowed(STATE_SUBMITTED, to_state)


def test_imported_to_submitted_raises_illegal_transition():
    """不可跳級：imported 不可直接轉為 submitted。"""
    with pytest.raises(IllegalTransitionError):
        assert_transition_allowed(STATE_IMPORTED, STATE_SUBMITTED)


def test_failed_to_submitted_raises_illegal_transition():
    """failed 不可直接宣告完成，必須先回到主線再走到 submitted。"""
    with pytest.raises(IllegalTransitionError):
        assert_transition_allowed(STATE_FAILED, STATE_SUBMITTED)


def test_can_transition_unknown_from_state_raises_unknown_state_error():
    """未知狀態必須拋例外，不是回 False。"""
    with pytest.raises(UnknownStateError):
        can_transition("bogus", STATE_PARSED)


def test_can_transition_unknown_to_state_raises_unknown_state_error():
    with pytest.raises(UnknownStateError):
        can_transition(STATE_IMPORTED, "bogus")


def test_allowed_targets_unknown_state_raises_unknown_state_error():
    with pytest.raises(UnknownStateError):
        allowed_targets("bogus")


def test_requires_reason_true_only_for_failed():
    assert requires_reason(STATE_FAILED) is True
    for state in ALL_STATES - {STATE_FAILED}:
        assert requires_reason(state) is False
