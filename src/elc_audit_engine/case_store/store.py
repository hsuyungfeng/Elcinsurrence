"""CaseStore：案件建立／查詢／狀態轉換／歷史／同步佇列取件。

狀態與轉換歷史於**單一 SQLite 交易**內原子寫入（`with conn:`）——非法
轉換或寫入中途失敗都不可留下「狀態改了但歷史沒寫」或反過來的半套結果
（T-09-09 mitigation）。

`list_by_state` 即為同步版任務佇列的取件介面：狀態欄位即佇列，不引入
外部訊息佇列 broker（09-CONTEXT.md 決策，單機部署）。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from config.settings import CASES_DB_PATH
from elc_audit_engine.case_store import db as case_db
from elc_audit_engine.case_store.states import (
    ALL_STATES,
    STATE_IMPORTED,
    UnknownStateError,
    assert_transition_allowed,
    requires_reason,
)
from elc_audit_engine.safe_paths import safe_filename

_VALID_KINDS = {"sampling", "appeal"}


@dataclass(frozen=True)
class CaseRecord:
    """對應 `cases` 表一列。"""

    case_id: str
    kind: str
    state: str
    case_seq: str | None
    order_code: str | None
    payload: dict | None
    created_at: str
    updated_at: str
    failure_reason: str | None


@dataclass(frozen=True)
class TransitionRecord:
    """對應 `case_transitions` 表一列。"""

    case_id: str
    from_state: str | None
    to_state: str
    reason: str | None
    actor: str | None
    created_at: str


class CaseStoreError(Exception):
    """案件狀態存放區操作的基底例外。"""


class DuplicateCaseError(CaseStoreError):
    """同一 case_id 已存在——不得覆寫既有狀態與歷史。"""


class CaseNotFoundError(CaseStoreError):
    """查無此 case_id（**不回 None**——None 會讓「查無案件」與「案件存在但
    無資料」混淆，此為 P0-2 同源原則的延伸）。"""


class MissingFailureReasonError(CaseStoreError):
    """轉入 failed 狀態但未附失敗原因。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_case_record(row: sqlite3.Row) -> CaseRecord:
    payload_json = row["payload_json"]
    payload = json.loads(payload_json) if payload_json is not None else None
    return CaseRecord(
        case_id=row["case_id"],
        kind=row["kind"],
        state=row["state"],
        case_seq=row["case_seq"],
        order_code=row["order_code"],
        payload=payload,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        failure_reason=row["failure_reason"],
    )


def _row_to_transition_record(row: sqlite3.Row) -> TransitionRecord:
    return TransitionRecord(
        case_id=row["case_id"],
        from_state=row["from_state"],
        to_state=row["to_state"],
        reason=row["reason"],
        actor=row["actor"],
        created_at=row["created_at"],
    )


class CaseStore:
    """案件狀態機的 SQLite 持久化存放區。"""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path if db_path is not None else CASES_DB_PATH
        case_db.init_schema(self.db_path)

    def _connect(self) -> sqlite3.Connection:
        return case_db.get_connection(self.db_path)

    def create(
        self,
        *,
        case_id: str,
        kind: str,
        case_seq: str | None = None,
        order_code: str | None = None,
        payload: dict | None = None,
        actor: str | None = None,
    ) -> CaseRecord:
        """建立新案件，初始狀態固定為 `imported`。

        Raises:
            UnsafeIdentifierError: `case_id` 含路徑成分或不允許的字元
                （校驗後拒絕，不清洗——case_id 會出現在日誌與後續檔名）。
            CaseStoreError: `kind` 不是 `"sampling"` 或 `"appeal"`。
            DuplicateCaseError: 同一 `case_id` 已存在——不得覆寫既有
                狀態與歷史，覆寫等於靜默丟失可追溯性。
        """
        validated_case_id = safe_filename(case_id, "case_id")
        if kind not in _VALID_KINDS:
            raise CaseStoreError(
                f"kind 必須為 {sorted(_VALID_KINDS)} 其中之一，收到：{kind!r}"
            )

        now = _now_iso()
        payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else None

        conn = self._connect()
        try:
            with conn:
                existing = conn.execute(
                    "SELECT case_id FROM cases WHERE case_id = ?", (validated_case_id,)
                ).fetchone()
                if existing is not None:
                    raise DuplicateCaseError(
                        f"案件已存在，拒絕覆寫：case_id={validated_case_id!r}"
                    )
                conn.execute(
                    "INSERT INTO cases "
                    "(case_id, kind, state, case_seq, order_code, payload_json, "
                    "created_at, updated_at, failure_reason) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                    (
                        validated_case_id,
                        kind,
                        STATE_IMPORTED,
                        case_seq,
                        order_code,
                        payload_json,
                        now,
                        now,
                    ),
                )
                conn.execute(
                    "INSERT INTO case_transitions "
                    "(case_id, from_state, to_state, reason, actor, created_at) "
                    "VALUES (?, NULL, ?, NULL, ?, ?)",
                    (validated_case_id, STATE_IMPORTED, actor, now),
                )
        finally:
            conn.close()

        return self.get(validated_case_id)

    def get(self, case_id: str) -> CaseRecord:
        """依 case_id 查詢單一案件目前狀態。

        Raises:
            CaseNotFoundError: 查無此案件（不回 None）。
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise CaseNotFoundError(f"查無案件：case_id={case_id!r}")
        return _row_to_case_record(row)

    def transition(
        self,
        case_id: str,
        to_state: str,
        *,
        reason: str | None = None,
        actor: str | None = None,
    ) -> CaseRecord:
        """將案件由目前狀態轉換至 `to_state`。

        狀態更新與轉換歷史寫入在**同一交易**內完成（`with conn:`），
        確保原子性——非法轉換或寫入失敗不會留下部分寫入的狀態。

        Raises:
            CaseNotFoundError: 案件不存在。
            IllegalTransitionError: 轉換不在顯式轉換表允許的邊內。
            UnknownStateError: `to_state` 不是已知狀態。
            MissingFailureReasonError: 轉入 `failed` 但未附 `reason`。
        """
        current = self.get(case_id)
        assert_transition_allowed(current.state, to_state)

        if requires_reason(to_state) and not reason:
            raise MissingFailureReasonError(
                f"轉入 {to_state} 必須附失敗原因：case_id={case_id!r}"
            )

        now = _now_iso()
        # 非 failed 狀態時 failure_reason 寫回 NULL，避免舊失敗原因黏在
        # 之後的成功狀態上（例：failed → parsed 後不應仍顯示舊的失敗原因）。
        new_failure_reason = reason if to_state == "failed" else None

        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "UPDATE cases SET state = ?, updated_at = ?, failure_reason = ? "
                    "WHERE case_id = ?",
                    (to_state, now, new_failure_reason, case_id),
                )
                self._insert_transition(
                    conn,
                    case_id=case_id,
                    from_state=current.state,
                    to_state=to_state,
                    reason=reason,
                    actor=actor,
                    created_at=now,
                )
        finally:
            conn.close()

        return self.get(case_id)

    def _insert_transition(
        self,
        conn: sqlite3.Connection,
        *,
        case_id: str,
        from_state: str | None,
        to_state: str,
        reason: str | None,
        actor: str | None,
        created_at: str,
    ) -> None:
        """寫入一列 case_transitions（私有方法，供測試 monkeypatch 模擬寫入失敗）。"""
        conn.execute(
            "INSERT INTO case_transitions "
            "(case_id, from_state, to_state, reason, actor, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (case_id, from_state, to_state, reason, actor, created_at),
        )

    def history(self, case_id: str) -> tuple[TransitionRecord, ...]:
        """依 `id` 升冪回傳案件的完整轉換歷史。

        Raises:
            CaseNotFoundError: 案件不存在。
        """
        # 先確認案件存在（不存在時拋 CaseNotFoundError，而非回傳空 tuple）
        self.get(case_id)
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM case_transitions WHERE case_id = ? ORDER BY id ASC",
                (case_id,),
            ).fetchall()
        finally:
            conn.close()
        return tuple(_row_to_transition_record(row) for row in rows)

    def list_by_state(
        self, state: str, *, kind: str | None = None, limit: int = 100
    ) -> tuple[CaseRecord, ...]:
        """同步版任務佇列的取件介面：查詢處於 `state` 的案件。

        狀態欄位即佇列——目前為同步取件，呼叫端自行處理後續轉換；
        不引入外部訊息佇列 broker（09-CONTEXT.md 決策，單機部署）。

        依 `created_at` 升冪回傳（FIFO）。

        Raises:
            UnknownStateError: `state` 不在 `ALL_STATES` 內。
        """
        if state not in ALL_STATES:
            raise UnknownStateError(f"未知狀態：{state!r}（允許：{sorted(ALL_STATES)}）")

        conn = self._connect()
        try:
            if kind is not None:
                rows = conn.execute(
                    "SELECT * FROM cases WHERE state = ? AND kind = ? "
                    "ORDER BY created_at ASC LIMIT ?",
                    (state, kind, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM cases WHERE state = ? ORDER BY created_at ASC LIMIT ?",
                    (state, limit),
                ).fetchall()
        finally:
            conn.close()
        return tuple(_row_to_case_record(row) for row in rows)

    def list_all(self, *, kind: str | None = None, limit: int = 1000) -> tuple[CaseRecord, ...]:
        """回傳所有案件（供 GET 案例清單端點使用），依 `created_at` 升冪。"""
        conn = self._connect()
        try:
            if kind is not None:
                rows = conn.execute(
                    "SELECT * FROM cases WHERE kind = ? ORDER BY created_at ASC LIMIT ?",
                    (kind, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM cases ORDER BY created_at ASC LIMIT ?", (limit,)
                ).fetchall()
        finally:
            conn.close()
        return tuple(_row_to_case_record(row) for row in rows)

    def counts_by_state(self, *, kind: str | None = None) -> dict[str, int]:
        """回傳各狀態筆數，供佇列深度觀測。"""
        conn = self._connect()
        try:
            if kind is not None:
                rows = conn.execute(
                    "SELECT state, COUNT(*) AS n FROM cases WHERE kind = ? GROUP BY state",
                    (kind,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT state, COUNT(*) AS n FROM cases GROUP BY state"
                ).fetchall()
        finally:
            conn.close()
        return {row["state"]: row["n"] for row in rows}
