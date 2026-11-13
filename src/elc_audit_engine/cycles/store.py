"""Phase 31: 循環 (Recording Cycle) 資料存取與生命週期管理。

注意：本模組依據 D-31-29 規範，嚴禁包含任何刪除檔案的操作。
"""

from __future__ import annotations

import datetime
from pathlib import Path
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Tuple

from config import settings
from elc_audit_engine.cycles.states import (
    STATE_ARCHIVED,
    STATE_RECORDING,
    assert_cycle_transition,
    IllegalCycleTransitionError,
)

_WHITELISTED_FIELDS = frozenset({
    "stop_command_id",
    "session_id",
    "draft_id",
    "total_chunks",
    "audio_sha256",
    "upload_complete",
    "audio_path",
    "transcript_path",
    "extras_json",
    "last_error",
    "archived_at",
})


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class ActiveCycleExistsError(Exception):
    """該 machine_id 尚有未終結的循環。"""

    def __init__(self, active_cycle_id: str):
        super().__init__(f"工作站已有進行中的循環：{active_cycle_id}")
        self.active_cycle_id = active_cycle_id


def cycle_dir(cycle_id: str) -> Path:
    """計算特定循環之檔案存放目錄（不執行實體建立或刪除）。"""
    return Path(settings.DATA_DIR) / "cycles" / cycle_id


def cycle_view(store, row: sqlite3.Row) -> Dict[str, Any]:
    """將 recording_cycles 資料表列轉換為符合契約 §3 之 cycle 物件（無 PHI）。"""
    conn = store._connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM cycle_chunks WHERE cycle_id = ?", (row["cycle_id"],))
        chunk_row = cur.fetchone()
        chunks_received = chunk_row["cnt"] if chunk_row else 0
    finally:
        conn.close()

    draft_state = None
    his_state = None
    if row["draft_id"]:
        try:
            d = store.get_soap_draft(row["draft_id"])
            draft_state = d.state
            if draft_state in ("approved", "queued"):
                his_state = "pending"
            elif draft_state == "pushed":
                his_state = "pushed"
            elif draft_state == "failed":
                his_state = "failed"
            else:
                his_state = None
        except Exception:
            draft_state = None
            his_state = None

    return {
        "cycle_id": row["cycle_id"],
        "machine_id": row["machine_id"],
        "room_id": row["room_id"],
        "state": row["state"],
        "draft_id": row["draft_id"],
        "draft_state": draft_state,
        "chunks_received": chunks_received,
        "total_chunks": row["total_chunks"],
        "upload_complete": bool(row["upload_complete"]),
        "his_state": his_state,
        "last_error": row["last_error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "archived_at": row["archived_at"],
    }


def create_cycle(
    store,
    *,
    command_id: str,
    machine_id: str,
    room_id: Optional[str] = None,
    actor: Optional[str] = None,
) -> Tuple[Dict[str, Any], bool]:
    """建立新循環（以 command_id 冪等）。

    回傳：(cycle_dict, created_bool)。
    若同一 machine_id 已有未終結循環且 command_id 不同，拋 ActiveCycleExistsError。
    """
    now = _now_iso()
    conn = store._connect()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.cursor()

            # 1. 冪等檢查：同一 command_id 已存在則直接回傳
            cur.execute("SELECT * FROM recording_cycles WHERE command_id = ?", (command_id,))
            existing = cur.fetchone()
            if existing:
                return cycle_view(store, existing), False

            # 2. 活躍循環檢查：同 machine_id 是否有未終結循環
            cur.execute(
                "SELECT cycle_id FROM recording_cycles "
                "WHERE machine_id = ? AND state NOT IN ('ARCHIVED', 'ABANDONED')",
                (machine_id,),
            )
            active = cur.fetchone()
            if active:
                raise ActiveCycleExistsError(active["cycle_id"])

            # 3. 建立新循環
            cycle_id = uuid.uuid4().hex
            cur.execute(
                """
                INSERT INTO recording_cycles (
                    cycle_id, machine_id, room_id, state, command_id,
                    created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cycle_id,
                    machine_id,
                    room_id,
                    STATE_RECORDING,
                    command_id,
                    actor,
                    now,
                    now,
                ),
            )
            cur.execute(
                """
                INSERT INTO cycle_events (
                    cycle_id, from_state, to_state, actor, reason_code, created_at
                ) VALUES (?, NULL, ?, ?, NULL, ?)
                """,
                (cycle_id, STATE_RECORDING, actor, now),
            )

            cur.execute("SELECT * FROM recording_cycles WHERE cycle_id = ?", (cycle_id,))
            new_row = cur.fetchone()
            return cycle_view(store, new_row), True
    finally:
        conn.close()


def get_cycle(store, cycle_id: str) -> Optional[Dict[str, Any]]:
    """依 cycle_id 查詢單一循環。"""
    conn = store._connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM recording_cycles WHERE cycle_id = ?", (cycle_id,))
        row = cur.fetchone()
        return cycle_view(store, row) if row else None
    finally:
        conn.close()


def get_active_cycle(store, machine_id: str) -> Optional[Dict[str, Any]]:
    """取得特定工作站目前未終結之循環。"""
    conn = store._connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM recording_cycles "
            "WHERE machine_id = ? AND state NOT IN ('ARCHIVED', 'ABANDONED')",
            (machine_id,),
        )
        row = cur.fetchone()
        return cycle_view(store, row) if row else None
    finally:
        conn.close()


def get_last_cycle(store, machine_id: str) -> Optional[Dict[str, Any]]:
    """取得特定工作站最近建立之循環（含已終結者）。"""
    conn = store._connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM recording_cycles WHERE machine_id = ? ORDER BY created_at DESC LIMIT 1",
            (machine_id,),
        )
        row = cur.fetchone()
        return cycle_view(store, row) if row else None
    finally:
        conn.close()


def transition_cycle(
    store,
    cycle_id: str,
    to_state: str,
    *,
    actor: Optional[str] = None,
    reason_code: Optional[str] = None,
    expect_from: Optional[Any] = None,
    fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """推進循環狀態並記錄 event（在單一交易內完成）。"""
    now = _now_iso()
    conn = store._connect()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.cursor()
            cur.execute("SELECT * FROM recording_cycles WHERE cycle_id = ?", (cycle_id,))
            row = cur.fetchone()
            if not row:
                raise LookupError(f"Cycle not found: {cycle_id}")

            from_state = row["state"]
            if expect_from is not None:
                expected_set = {expect_from} if isinstance(expect_from, str) else set(expect_from)
                if from_state not in expected_set:
                    raise IllegalCycleTransitionError(from_state, to_state)

            assert_cycle_transition(from_state, to_state)

            set_clauses = ["state = ?", "updated_at = ?"]
            params: List[Any] = [to_state, now]

            if fields:
                for k, v in fields.items():
                    if k in _WHITELISTED_FIELDS:
                        set_clauses.append(f"{k} = ?")
                        params.append(v)

            if to_state == STATE_ARCHIVED and (not fields or "archived_at" not in fields):
                set_clauses.append("archived_at = ?")
                params.append(now)

            params.append(cycle_id)
            sql = f"UPDATE recording_cycles SET {', '.join(set_clauses)} WHERE cycle_id = ?"
            cur.execute(sql, tuple(params))

            cur.execute(
                """
                INSERT INTO cycle_events (
                    cycle_id, from_state, to_state, actor, reason_code, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (cycle_id, from_state, to_state, actor, reason_code, now),
            )

            cur.execute("SELECT * FROM recording_cycles WHERE cycle_id = ?", (cycle_id,))
            updated_row = cur.fetchone()
            return cycle_view(store, updated_row)
    finally:
        conn.close()
