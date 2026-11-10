"""CaseStore：案件建立／查詢／狀態轉換／歷史／同步佇列取件。

狀態與轉換歷史於**單一 SQLite 交易**內原子寫入（`with conn:`）——非法
轉換或寫入中途失敗都不可留下「狀態改了但歷史沒寫」或反過來的半套結果
（T-09-09 mitigation）。

`list_by_state` 即為同步版任務佇列的取件介面：狀態欄位即佇列，不引入
外部訊息佇列 broker（09-CONTEXT.md 決策，單機部署）。
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

try:
    from config.settings import CASES_DB_PATH
except ImportError:
    CASES_DB_PATH = "data/db/cases.sqlite3"
from elc_audit_engine.case_store import db as case_db
from elc_audit_engine.case_store.soap_draft_states import (
    ALL_DRAFT_STATES,
    STATE_APPROVED,
    STATE_DRAFT,
    STATE_FAILED,
    STATE_PUSHED,
    STATE_QUALITY_FAILED,
    STATE_QUEUED,
    STATE_REJECTED,
    STATE_VALIDATED,
    TERMINAL_DRAFT_STATES,
    UnknownDraftStateError,
    assert_draft_transition_allowed,
    compute_soap_content_hash,
)
from elc_audit_engine.case_store.states import (
    ALL_STATES,
    STATE_IMPORTED,
    UnknownStateError,
    assert_transition_allowed,
    requires_reason,
)
from elc_audit_engine.safe_paths import safe_filename

_VALID_KINDS = {"sampling", "appeal", "monthly", "his", "bridge"}


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


@dataclass(frozen=True)
class SoapDraftRecord:
    """對應 `soap_drafts` 表一列（Phase 29）。"""

    draft_id: str
    case_id: str
    order_code: str | None
    version: int
    state: str
    soap: dict
    content_hash: str
    quality_score: int | None
    quality_issues: list[dict]
    comparison: dict | None
    reviewer_id: str | None
    review_decision: str | None
    review_reason: str | None
    reviewed_at: str | None
    pushed_at: str | None
    agent_id: str | None
    failure_reason: str | None
    created_at: str
    updated_at: str


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
    return datetime.now(UTC).isoformat()


# cas_update_payload 的期望鍵會嵌入 JSON 路徑，僅允許小寫英文與底線。
_JSON_KEY_RE = re.compile(r"[a-z_]+")


def _template_key(order_code: str, primary_diagnosis: str | None) -> tuple[str, str]:
    """範本鍵正規化：醫令代碼與診斷碼皆去空白、轉大寫。診斷可為空字串（代表通用範本）；醫令代碼必填。"""
    code = (order_code or "").strip().upper()
    dx = (primary_diagnosis or "").strip().upper()
    if not code:
        raise CaseStoreError("範本鍵缺漏：醫令代碼必填")
    return code, dx


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


def _row_to_soap_draft_record(row: sqlite3.Row) -> SoapDraftRecord:
    soap_json = row["soap_json"]
    soap = json.loads(soap_json) if soap_json is not None else {}
    issues_raw = row["quality_issues_json"]
    issues = json.loads(issues_raw) if issues_raw is not None else []
    comp_raw = row["comparison_json"]
    comp = json.loads(comp_raw) if comp_raw is not None else None
    return SoapDraftRecord(
        draft_id=row["draft_id"],
        case_id=row["case_id"],
        order_code=row["order_code"],
        version=row["version"],
        state=row["state"],
        soap=soap,
        content_hash=row["content_hash"],
        quality_score=row["quality_score"],
        quality_issues=issues,
        comparison=comp,
        reviewer_id=row["reviewer_id"],
        review_decision=row["review_decision"],
        review_reason=row["review_reason"],
        reviewed_at=row["reviewed_at"],
        pushed_at=row["pushed_at"],
        agent_id=row["agent_id"],
        failure_reason=row["failure_reason"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
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
            CaseStoreError: `kind` 不是 `"sampling"`、`"appeal"` 或 `"monthly"`。
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
                # BEGIN IMMEDIATE：SELECT 與 INSERT 在同一寫鎖內，併發建案時
                # 不會兩邊都通過存在檢查（A-WR-01）。
                conn.execute("BEGIN IMMEDIATE")
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
        except sqlite3.IntegrityError as exc:
            # 保底：主鍵衝突一律以業務例外呈現，不以 500 穿透 _persist_cases
            raise DuplicateCaseError(
                f"案件已存在，拒絕覆寫：case_id={validated_case_id!r}"
            ) from exc
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
        """將案件由目前狀態轉換至 `to_state`（單步版 `advance`）。

        Raises:
            CaseNotFoundError: 案件不存在。
            IllegalTransitionError: 轉換不在顯式轉換表允許的邊內。
            UnknownStateError: `to_state` 不是已知狀態。
            MissingFailureReasonError: 轉入 `failed` 但未附 `reason`。
        """
        return self.advance(case_id, [to_state], reason=reason, actor=actor)

    def advance(
        self,
        case_id: str,
        to_states: list[str] | tuple[str, ...],
        *,
        reason: str | None = None,
        actor: str | None = None,
    ) -> CaseRecord:
        """依序走完多步轉換，全部在**同一個 IMMEDIATE 交易**內完成。

        目前狀態的讀取與寫入在同一交易（BEGIN IMMEDIATE 取得寫鎖），
        避免兩個請求同時讀到舊狀態各自寫入（TOCTOU）；任一步不合法或
        寫入失敗則整批回滾，不會卡在中間狀態（A-CR-09）。

        Raises:
            CaseNotFoundError / IllegalTransitionError / UnknownStateError /
            MissingFailureReasonError：同 `transition`。
        """
        if not to_states:
            return self.get(case_id)
        for to_state in to_states:
            if requires_reason(to_state) and not reason:
                raise MissingFailureReasonError(
                    f"轉入 {to_state} 必須附失敗原因：case_id={case_id!r}"
                )

        conn = self._connect()
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT state FROM cases WHERE case_id = ?", (case_id,)
                ).fetchone()
                if row is None:
                    raise CaseNotFoundError(f"查無案件：case_id={case_id!r}")
                from_state = row["state"]
                for to_state in to_states:
                    assert_transition_allowed(from_state, to_state)
                    now = _now_iso()
                    # 非 failed 狀態時 failure_reason 寫回 NULL，避免舊失敗原因黏在
                    # 之後的成功狀態上（例：failed → parsed 後不應仍顯示舊的失敗原因）。
                    new_failure_reason = reason if to_state == "failed" else None
                    conn.execute(
                        "UPDATE cases SET state = ?, updated_at = ?, failure_reason = ? "
                        "WHERE case_id = ?",
                        (to_state, now, new_failure_reason, case_id),
                    )
                    self._insert_transition(
                        conn,
                        case_id=case_id,
                        from_state=from_state,
                        to_state=to_state,
                        reason=reason,
                        actor=actor,
                        created_at=now,
                    )
                    from_state = to_state
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

    def set_artifact(self, case_id: str, name: str, content: dict) -> None:
        """寫入（覆寫）案件衍生產物，例如 `appeal_draft`。

        Raises:
            CaseNotFoundError: 案件不存在（不替不存在的案件留孤兒資料）。
        """
        self.get(case_id)
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO case_artifacts (case_id, name, content_json, updated_at) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(case_id, name) DO UPDATE SET "
                    "content_json = excluded.content_json, updated_at = excluded.updated_at",
                    (case_id, name, json.dumps(content, ensure_ascii=False), _now_iso()),
                )
        finally:
            conn.close()

    def get_artifact(self, case_id: str, name: str) -> dict | None:
        """讀取案件衍生產物；尚未產生時回 None（呼叫端決定如何誠實呈現）。"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT content_json FROM case_artifacts WHERE case_id = ? AND name = ?",
                (case_id, name),
            ).fetchone()
        finally:
            conn.close()
        return json.loads(row["content_json"]) if row is not None else None

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

    def list_all(
        self, *, kind: str | None = None, limit: int = 1000, offset: int = 0
    ) -> tuple[CaseRecord, ...]:
        """回傳案件（供 GET 案例清單端點使用），依 `created_at` 升冪，支援分頁。

        呼叫端應以 `count` 取得總數並揭露給使用者，避免超過 limit 時靜默截斷（A-WR-12）。
        """
        conn = self._connect()
        try:
            if kind is not None:
                rows = conn.execute(
                    "SELECT * FROM cases WHERE kind = ? ORDER BY created_at ASC, case_id ASC "
                    "LIMIT ? OFFSET ?",
                    (kind, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM cases ORDER BY created_at ASC, case_id ASC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
        finally:
            conn.close()
        return tuple(_row_to_case_record(row) for row in rows)

    def list_by_batch(
        self, batch: str, *, limit: int = 1000, offset: int = 0
    ) -> tuple[CaseRecord, ...]:
        """依申報批次（`payload.batch`，如 `MONTHLY-202307`）列出當月申報案件。

        走 `idx_cases_batch` 表達式索引；依 `created_at`、`case_id` 升冪排序，
        支援分頁。批次內案件數請以 `count_by_batch` 取得總數。
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM cases "
                "WHERE kind = 'monthly' AND json_extract(payload_json, '$.batch') = ? "
                "ORDER BY created_at ASC, case_id ASC LIMIT ? OFFSET ?",
                (batch, limit, offset),
            ).fetchall()
        finally:
            conn.close()
        return tuple(_row_to_case_record(row) for row in rows)

    def count_by_batch(self, batch: str) -> int:
        """申報批次內的案件總數（與 `list_by_batch` 同一篩選條件）。"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM cases "
                "WHERE kind = 'monthly' AND json_extract(payload_json, '$.batch') = ?",
                (batch,),
            ).fetchone()
        finally:
            conn.close()
        return row["n"]

    def get_soap_template(
        self, order_code: str, primary_diagnosis: str, *, fallback_general: bool = True
    ) -> dict | None:
        """讀取範本：先查 (醫令, 診斷)；未命中且 `fallback_general` 時回退查 (醫令, '') 通用範本。

        回傳的 `scope` 為 "specific"（指定診斷）或 "general"（通用範本）；皆未命中回 None。
        """
        code, dx = _template_key(order_code, primary_diagnosis)
        keys = [(code, dx)]
        if dx and fallback_general:
            keys.append((code, ""))
        conn = self._connect()
        try:
            for key in keys:
                row = conn.execute(
                    "SELECT soap_json, source, quality_score, created_at FROM soap_templates "
                    "WHERE order_code = ? AND primary_diagnosis = ?",
                    key,
                ).fetchone()
                if row is not None:
                    return {
                        "soap": json.loads(row["soap_json"]),
                        "source": row["source"],
                        "quality_score": row["quality_score"],
                        "created_at": row["created_at"],
                        "scope": "specific" if key[1] == dx and dx else "general",
                    }
        finally:
            conn.close()
        return None

    def put_soap_template(
        self,
        order_code: str,
        primary_diagnosis: str,
        soap: dict,
        *,
        source: str,
        quality_score: int | None,
    ) -> None:
        """寫入（覆寫）通用範本。`source` 為 llm_validated 或 physician_edited。"""
        key = _template_key(order_code, primary_diagnosis)
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO soap_templates "
                    "(order_code, primary_diagnosis, soap_json, source, quality_score, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(order_code, primary_diagnosis) DO UPDATE SET "
                    "soap_json = excluded.soap_json, source = excluded.source, "
                    "quality_score = excluded.quality_score, created_at = excluded.created_at",
                    (*key, json.dumps(soap, ensure_ascii=False), source, quality_score, _now_iso()),
                )
        finally:
            conn.close()

    def update_payload(self, case_id: str, payload: dict) -> CaseRecord:
        """覆寫案件 payload 快照（不改變狀態與歷史）。案件不存在拋 CaseNotFoundError。"""
        self.get(case_id)
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "UPDATE cases SET payload_json = ?, updated_at = ? WHERE case_id = ?",
                    (json.dumps(payload, ensure_ascii=False), _now_iso(), case_id),
                )
        finally:
            conn.close()
        return self.get(case_id)

    def cas_update_payload(self, case_id: str, payload: dict, *, expect: dict) -> bool:
        """條件式覆寫（Compare-And-Swap）：僅當 payload 中每個 `expect` 鍵的目前值相等時才寫入。

        比對以 `IS` 進行，因此 None 可與 SQL NULL 比對。整個比對與寫入在 BEGIN IMMEDIATE
        寫鎖內完成，併發的兩個寫入者只有一個會成功。回傳 True 表示寫入成功，False 表示
        期望值不符（呼叫端應視為衝突）。案件不存在時亦回傳 False。

        `expect` 的鍵只允許小寫英文與底線（會直接嵌入 JSON 路徑，故需白名單式驗證）。
        """
        if not expect:
            raise ValueError("cas_update_payload 需要至少一個期望條件")
        where_parts: list[str] = []
        params: list = []
        for key, value in expect.items():
            if not _JSON_KEY_RE.fullmatch(key):
                raise ValueError(f"非法的 payload 鍵：{key!r}")
            where_parts.append(f"json_extract(payload_json, '$.{key}') IS ?")
            params.append(value)
        sql = (
            "UPDATE cases SET payload_json = ?, updated_at = ? WHERE case_id = ? AND "
            + " AND ".join(where_parts)
        )
        conn = self._connect()
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.execute(
                    sql,
                    (json.dumps(payload, ensure_ascii=False), _now_iso(), case_id, *params),
                )
                return cursor.rowcount == 1
        finally:
            conn.close()

    def list_bridge_jobs(
        self,
        *,
        status: str | None = None,
        s_type_code: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[CaseRecord, ...]:
        """地端橋接任務（kind='bridge'）的 SQL 層篩選與分頁，依 `created_at`、`case_id` 升冪。

        篩選直接在資料庫以 `json_extract(payload_json, '$.status')` 等進行，不在 Python 端掃描，
        因此即使歷史紀錄遠超過 limit，較新的符合條件任務仍會被查出。
        """
        conditions = ["kind = 'bridge'"]
        params: list = []
        if status is not None:
            conditions.append("json_extract(payload_json, '$.status') = ?")
            params.append(status)
        if s_type_code is not None:
            conditions.append("json_extract(payload_json, '$.s_type_code') = ?")
            params.append(s_type_code)
        params.extend([limit, offset])
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM cases WHERE " + " AND ".join(conditions)
                + " ORDER BY created_at ASC, case_id ASC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        finally:
            conn.close()
        return tuple(_row_to_case_record(row) for row in rows)

    def list_batches(self) -> tuple[tuple[str, int], ...]:
        """所有當月申報批次及其案件數，依批次名升冪（`(batch, count)`）。"""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT json_extract(payload_json, '$.batch') AS batch, COUNT(*) AS n "
                "FROM cases WHERE kind = 'monthly' "
                "GROUP BY batch HAVING batch IS NOT NULL ORDER BY batch ASC"
            ).fetchall()
        finally:
            conn.close()
        return tuple((row["batch"], row["n"]) for row in rows)

    def count(self, *, kind: str | None = None) -> int:
        """案件總數（分頁用）。"""
        conn = self._connect()
        try:
            if kind is not None:
                row = conn.execute("SELECT COUNT(*) AS n FROM cases WHERE kind = ?", (kind,)).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS n FROM cases").fetchone()
        finally:
            conn.close()
        return row["n"]

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

    def delete_by_kind(self, kind: str) -> int:
        """依 kind 批次刪除案件，回傳刪除筆數。"""
        conn = self._connect()
        try:
            cur = conn.execute("DELETE FROM cases WHERE kind = ?", (kind,))
            deleted = cur.rowcount
            conn.commit()
            return deleted
        finally:
            conn.close()

    def delete_by_batch(self, batch: str) -> int:
        """依申報批次刪除當月申報案件，回傳刪除筆數。"""
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM cases WHERE kind = 'monthly' AND json_extract(payload_json, '$.batch') = ?",
                (batch,),
            )
            deleted = cur.rowcount
            conn.commit()
            return deleted
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Phase 29: SOAP 草稿、審核與 Windows Agent 心跳
    # ------------------------------------------------------------------

    def create_soap_draft(
        self,
        *,
        case_id: str,
        soap: dict,
        order_code: str | None = None,
        state: str = STATE_DRAFT,
        quality_score: int | None = None,
        quality_issues: list[dict] | None = None,
        comparison: dict | None = None,
        draft_id: str | None = None,
    ) -> SoapDraftRecord:
        """建立一筆新 SOAP 草稿（單一交易內寫入草稿與初始歷史）。"""
        if state not in ALL_DRAFT_STATES:
            raise UnknownDraftStateError(state)
        d_id = draft_id or uuid.uuid4().hex
        now = _now_iso()
        content_hash = compute_soap_content_hash(soap)
        soap_json = json.dumps(soap, ensure_ascii=False)
        issues_json = json.dumps(quality_issues or [], ensure_ascii=False)
        comp_json = json.dumps(comparison, ensure_ascii=False) if comparison is not None else None

        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO soap_drafts ("
                    "draft_id, case_id, order_code, version, state, soap_json, content_hash, "
                    "quality_score, quality_issues_json, comparison_json, created_at, updated_at"
                    ") VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        d_id,
                        case_id,
                        order_code,
                        state,
                        soap_json,
                        content_hash,
                        quality_score,
                        issues_json,
                        comp_json,
                        now,
                        now,
                    ),
                )
                conn.execute(
                    "INSERT INTO soap_draft_history ("
                    "draft_id, version, state, soap_json, content_hash, reviewer_id, review_decision, review_reason, created_at"
                    ") VALUES (?, 1, ?, ?, ?, NULL, 'create', NULL, ?)",
                    (d_id, state, soap_json, content_hash, now),
                )
        finally:
            conn.close()

        return self.get_soap_draft(d_id)

    def get_soap_draft(self, draft_id: str) -> SoapDraftRecord:
        """依 draft_id 讀取草稿；查無紀錄拋 CaseNotFoundError。"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM soap_drafts WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
            if row is None:
                raise CaseNotFoundError(f"查無 SOAP 草稿：{draft_id}")
            return _row_to_soap_draft_record(row)
        finally:
            conn.close()

    def list_soap_drafts(
        self,
        *,
        case_id: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[SoapDraftRecord]:
        """查詢 SOAP 草稿列表。"""
        sql = "SELECT * FROM soap_drafts"
        params: list[Any] = []
        clauses: list[str] = []
        if case_id is not None:
            clauses.append("case_id = ?")
            params.append(case_id)
        if state is not None:
            clauses.append("state = ?")
            params.append(state)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        conn = self._connect()
        try:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [_row_to_soap_draft_record(r) for r in rows]
        finally:
            conn.close()

    def update_soap_draft_state(
        self,
        draft_id: str,
        to_state: str,
        *,
        reviewer_id: str | None = None,
        decision: str | None = None,
        reason: str | None = None,
        agent_id: str | None = None,
        failure_reason: str | None = None,
    ) -> SoapDraftRecord:
        """更新草稿狀態（原子交易檢查顯式狀態轉換與寫入歷史）。"""
        conn = self._connect()
        try:
            with conn:
                row = conn.execute(
                    "SELECT * FROM soap_drafts WHERE draft_id = ?",
                    (draft_id,),
                ).fetchone()
                if row is None:
                    raise CaseNotFoundError(f"查無 SOAP 草稿：{draft_id}")
                current = _row_to_soap_draft_record(row)

                assert_draft_transition_allowed(current.state, to_state)

                now = _now_iso()
                pushed_at = now if to_state == STATE_PUSHED else current.pushed_at
                reviewed_at = (
                    now
                    if to_state in (STATE_APPROVED, STATE_REJECTED)
                    else current.reviewed_at
                )
                eff_reviewer = reviewer_id or current.reviewer_id
                eff_decision = decision or (
                    "approved"
                    if to_state == STATE_APPROVED
                    else ("rejected" if to_state == STATE_REJECTED else current.review_decision)
                )
                eff_reason = reason or current.review_reason
                eff_agent = agent_id or current.agent_id
                eff_failure = failure_reason or (reason if to_state == STATE_FAILED else current.failure_reason)

                conn.execute(
                    "UPDATE soap_drafts SET "
                    "state = ?, reviewer_id = ?, review_decision = ?, review_reason = ?, "
                    "reviewed_at = ?, pushed_at = ?, agent_id = ?, failure_reason = ?, updated_at = ? "
                    "WHERE draft_id = ?",
                    (
                        to_state,
                        eff_reviewer,
                        eff_decision,
                        eff_reason,
                        reviewed_at,
                        pushed_at,
                        eff_agent,
                        eff_failure,
                        now,
                        draft_id,
                    ),
                )
                conn.execute(
                    "INSERT INTO soap_draft_history ("
                    "draft_id, version, state, soap_json, content_hash, reviewer_id, review_decision, review_reason, created_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        draft_id,
                        current.version,
                        to_state,
                        row["soap_json"],
                        current.content_hash,
                        eff_reviewer,
                        eff_decision,
                        eff_reason,
                        now,
                    ),
                )
        finally:
            conn.close()

        return self.get_soap_draft(draft_id)

    def edit_soap_draft(
        self,
        draft_id: str,
        new_soap: dict,
        *,
        reviewer_id: str | None = None,
        quality_score: int | None = None,
        quality_issues: list[dict] | None = None,
        comparison: dict | None = None,
        is_quality_pass: bool = True,
    ) -> SoapDraftRecord:
        """醫師編修草稿：版本遞增、重新計算雜湊，狀態重回 validated（若品質檢核通過）或 quality_failed。"""
        conn = self._connect()
        try:
            with conn:
                row = conn.execute(
                    "SELECT * FROM soap_drafts WHERE draft_id = ?",
                    (draft_id,),
                ).fetchone()
                if row is None:
                    raise CaseNotFoundError(f"查無 SOAP 草稿：{draft_id}")
                current = _row_to_soap_draft_record(row)

                target_state = STATE_VALIDATED if is_quality_pass else STATE_QUALITY_FAILED
                assert_draft_transition_allowed(current.state, target_state)

                new_version = current.version + 1
                new_hash = compute_soap_content_hash(new_soap)
                now = _now_iso()
                soap_json = json.dumps(new_soap, ensure_ascii=False)
                issues_json = json.dumps(quality_issues or [], ensure_ascii=False)
                comp_json = json.dumps(comparison, ensure_ascii=False) if comparison is not None else None

                conn.execute(
                    "UPDATE soap_drafts SET "
                    "version = ?, state = ?, soap_json = ?, content_hash = ?, "
                    "quality_score = ?, quality_issues_json = ?, comparison_json = ?, "
                    "reviewer_id = ?, review_decision = 'edit', updated_at = ? "
                    "WHERE draft_id = ?",
                    (
                        new_version,
                        target_state,
                        soap_json,
                        new_hash,
                        quality_score,
                        issues_json,
                        comp_json,
                        reviewer_id or current.reviewer_id,
                        now,
                        draft_id,
                    ),
                )
                conn.execute(
                    "INSERT INTO soap_draft_history ("
                    "draft_id, version, state, soap_json, content_hash, reviewer_id, review_decision, review_reason, created_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, 'edit', NULL, ?)",
                    (
                        draft_id,
                        new_version,
                        target_state,
                        soap_json,
                        new_hash,
                        reviewer_id or current.reviewer_id,
                        now,
                    ),
                )
        finally:
            conn.close()

        return self.get_soap_draft(draft_id)

    def find_pushed_soap_draft(self, case_id: str, content_hash: str) -> SoapDraftRecord | None:
        """依 case_id 與 content_hash 檢查是否曾成功 pushed（冪等防重寫入）。"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM soap_drafts WHERE case_id = ? AND content_hash = ? AND state = ? LIMIT 1",
                (case_id, content_hash, STATE_PUSHED),
            ).fetchone()
            if row is None:
                return None
            return _row_to_soap_draft_record(row)
        finally:
            conn.close()

    def record_agent_heartbeat(
        self,
        agent_id: str,
        *,
        version: str = "",
        his_status: str = "",
        client_timestamp: str = "",
    ) -> None:
        """紀錄 Windows Agent 心跳。"""
        now = _now_iso()
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO agent_heartbeats ("
                    "agent_id, version, his_status, client_timestamp, last_heartbeat_at"
                    ") VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(agent_id) DO UPDATE SET "
                    "version = excluded.version, "
                    "his_status = excluded.his_status, "
                    "client_timestamp = excluded.client_timestamp, "
                    "last_heartbeat_at = excluded.last_heartbeat_at",
                    (agent_id, version, his_status, client_timestamp, now),
                )
        finally:
            conn.close()

    def list_agent_heartbeats(self) -> list[dict[str, Any]]:
        """列出所有 Agent 心跳，並計算 is_online（30 分鐘無心跳標記離線）。"""
        conn = self._connect()
        now = datetime.now(UTC)
        try:
            rows = conn.execute(
                "SELECT * FROM agent_heartbeats ORDER BY last_heartbeat_at DESC"
            ).fetchall()
            results: list[dict[str, Any]] = []
            for r in rows:
                last_dt = datetime.fromisoformat(r["last_heartbeat_at"])
                diff_sec = (now - last_dt).total_seconds()
                is_online = diff_sec < 1800  # 30 mins
                results.append(
                    {
                        "agent_id": r["agent_id"],
                        "version": r["version"],
                        "his_status": r["his_status"],
                        "client_timestamp": r["client_timestamp"],
                        "last_heartbeat_at": r["last_heartbeat_at"],
                        "is_online": is_online,
                    }
                )
            return results
        finally:
            conn.close()

    def get_recording_session(self, session_id: str) -> dict | None:
        """Lookup recording session by session_id for idempotency (Phase 30)."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT session_id, draft_id, caller, created_at FROM soap_recording_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return dict(row)
        finally:
            conn.close()

    def put_recording_session(self, session_id: str, draft_id: str, caller: str | None = None) -> None:
        """Record recording session mapping (session_id -> draft_id) (Phase 30)."""
        now = _now_iso()
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO soap_recording_sessions (session_id, draft_id, caller, created_at) VALUES (?, ?, ?, ?)",
                    (session_id, draft_id, caller, now),
                )
        finally:
            conn.close()

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        """Read a configuration value from soap_settings (Phase 30)."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT value FROM soap_settings WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return default
            return row["value"]
        finally:
            conn.close()

    def list_soap_drafts_by_state(self, state: str, limit: int = 50) -> list[SoapDraftRecord]:
        """Query soap_drafts by state ordered by created_at ASC (Phase 30)."""
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT * FROM soap_drafts WHERE state = ? ORDER BY created_at ASC LIMIT ?",
                (state, max(1, min(limit, 50))),
            )
            rows = cur.fetchall()
            return [_row_to_soap_draft_record(r) for r in rows]
        finally:
            conn.close()

    def set_setting(self, key: str, value: str, updated_by: str | None = None) -> None:
        """Upsert a configuration value into soap_settings (Phase 30)."""
        now = _now_iso()
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO soap_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET "
                    "value = excluded.value, updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                    (key, value, now, updated_by),
                )
        finally:
            conn.close()
