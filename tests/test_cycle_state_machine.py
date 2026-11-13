"""Phase 31 Plan 05 Task 1: 循環狀態機純函式與 Schema 測試。"""

from __future__ import annotations

import sqlite3
import pytest

from elc_audit_engine.case_store.db import get_connection, init_schema
from elc_audit_engine.cycles.states import (
    STATE_ABANDONED,
    STATE_ARCHIVE_FAILED,
    STATE_ARCHIVED,
    STATE_CONFIRMED,
    STATE_RECORDING,
    _CYCLE_TRANSITIONS,
    assert_cycle_transition,
    display_state,
    IllegalCycleTransitionError,
    UnknownCycleStateError,
)
from tests.phase31_support import load_contract


def test_contract_transitions_match_states_transitions():
    """Test 1: 契約 fixture 的 transitions 與 states._CYCLE_TRANSITIONS 完全相同。"""
    contract = load_contract()
    c_transitions = contract["transitions"]

    assert set(c_transitions.keys()) == set(_CYCLE_TRANSITIONS.keys())
    for src, tgts in c_transitions.items():
        assert tuple(tgts) == _CYCLE_TRANSITIONS[src]


def test_transitions_allowed_and_illegal():
    """Test 2: 合法轉換全數通過；非法轉換與未知狀態拋出對應例外。"""
    for src, tgts in _CYCLE_TRANSITIONS.items():
        for tgt in tgts:
            assert_cycle_transition(src, tgt)

    # 非法轉換
    with pytest.raises(IllegalCycleTransitionError):
        assert_cycle_transition(STATE_RECORDING, STATE_CONFIRMED)

    with pytest.raises(IllegalCycleTransitionError):
        assert_cycle_transition(STATE_ARCHIVED, STATE_RECORDING)

    with pytest.raises(IllegalCycleTransitionError):
        assert_cycle_transition(STATE_ABANDONED, STATE_RECORDING)

    # 未知狀態
    with pytest.raises(UnknownCycleStateError):
        assert_cycle_transition("NON_EXISTENT", STATE_RECORDING)

    with pytest.raises(UnknownCycleStateError):
        assert_cycle_transition(STATE_RECORDING, "INVALID_TARGET")


def test_display_state_rules():
    """Test 3: display_state 計算五種狀態規則與離線優先原則。"""
    # 離線優先
    assert display_state(cycle_state=STATE_RECORDING, online=False) == "離線"
    assert display_state(cycle_state=None, last_cycle_state="ARCHIVED", online=False) == "離線"

    # 在線時依規則
    assert display_state(cycle_state=STATE_RECORDING, online=True) == "錄音中"
    assert display_state(cycle_state=STATE_ARCHIVE_FAILED, online=True) == "待確認"
    assert display_state(cycle_state=None, last_cycle_state="ARCHIVED", online=True) == "已封存"
    assert display_state(cycle_state=STATE_ARCHIVED, last_cycle_state="ARCHIVED", online=True) == "已封存"
    assert display_state(cycle_state=None, last_cycle_state=None, online=True) == "待命"


def test_schema_tables_and_partial_unique_index(tmp_path):
    """Test 4: init_schema 後五張表存在；同 machine_id 未終結循環唯一，ARCHIVED 可並存。"""
    db_file = tmp_path / "cycle_test.sqlite3"
    init_schema(str(db_file))

    conn = get_connection(str(db_file))
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r["name"] for r in cur.fetchall()}
    assert {
        "recording_cycles",
        "cycle_events",
        "cycle_chunks",
        "cycle_confirmations",
        "client_presence",
    }.issubset(tables)

    # 測試部分唯一索引：machine_id WHERE state NOT IN ('ARCHIVED', 'ABANDONED')
    cur.execute(
        """
        INSERT INTO recording_cycles (
            cycle_id, machine_id, state, command_id, created_at, updated_at
        ) VALUES ('c1', 'm1', 'RECORDING', 'cmd1', '2026-11-12T00:00:00', '2026-11-12T00:00:00')
        """
    )
    conn.commit()

    # 同一 machine_id 再插入一筆 RECORDING 應因 unique index 拋 IntegrityError
    with pytest.raises(sqlite3.IntegrityError):
        cur.execute(
            """
            INSERT INTO recording_cycles (
                cycle_id, machine_id, state, command_id, created_at, updated_at
            ) VALUES ('c2', 'm1', 'RECORDING', 'cmd2', '2026-11-12T00:00:00', '2026-11-12T00:00:00')
            """
        )

    # 另一筆已終結的 ARCHIVED 可以與 m1 的 RECORDING 並存
    cur.execute(
        """
        INSERT INTO recording_cycles (
            cycle_id, machine_id, state, command_id, created_at, updated_at
        ) VALUES ('c3', 'm1', 'ARCHIVED', 'cmd3', '2026-11-12T00:00:00', '2026-11-12T00:00:00')
        """
    )
    conn.commit()
    conn.close()
