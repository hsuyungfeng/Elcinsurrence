"""Phase 31: 循環確認存檔與黃燈封存 (契約 §3, D-31-05 ~ D-31-08, D-31-25, D-31-26, D-31-37, D-31-38).

核心函式：
- confirm_cycle: 醫師確認草稿存入 cycle_confirmations 並排入 HIS_PUSH 任務
- archive_cycle: 檢查伺服器存檔與 HIS pushed 條件，達成時完成封存
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Tuple

from elc_audit_engine import audit_log
from elc_audit_engine.api.errors import ApiError
from elc_audit_engine.api.routes.soap_review import approve_and_enqueue
from elc_audit_engine.case_store.soap_draft_states import (
    STATE_APPROVED,
    STATE_FAILED,
    STATE_PUSHED,
    STATE_QUEUED,
    STATE_VALIDATED,
)
from elc_audit_engine.cycles.states import (
    STATE_ABANDONED,
    STATE_ARCHIVED,
    STATE_ARCHIVE_FAILED,
    STATE_ARCHIVING,
    STATE_AWAITING_CONFIRM,
    STATE_CONFIRMED,
    STATE_DRAFT_UNUSABLE,
    IllegalCycleTransitionError,
)
from elc_audit_engine.cycles.store import (
    _now_iso,
    get_cycle,
    transition_cycle,
)
from elc_audit_engine.comparator.soap_advice import validate_soap_quality

logger = logging.getLogger("cycles.archive")


def confirm_cycle(
    store,
    *,
    cycle_id: str,
    content_hash: str,
    soap: Optional[Dict[str, Any]] = None,
    reviewer_id: Optional[str] = None,
) -> Dict[str, Any]:
    """醫師確認草稿並存檔 (契約 §3, D-31-08, D-31-25, D-31-37).

    流程：
    1. 驗證循環狀態與 content_hash
    2. 若帶有修改後 soap，執行品質檢核；不合則轉 DRAFT_UNUSABLE 並回傳 422
    3. 若原為 DRAFT_UNUSABLE 且修改合格，建立新草稿並改綁定到循環
    4. 存入 cycle_confirmations（確認版快照，含 full extras）
    5. 呼叫 approve_and_enqueue 排入綁定 machine_id 的 HIS_PUSH
    6. 循環狀態推進至 CONFIRMED
    7. 記錄存取審計（零 PHI）
    """
    cycle = get_cycle(store, cycle_id)
    if not cycle:
        raise ApiError("找不到該循環", status=404)

    c_state = cycle["state"]
    if c_state == STATE_ARCHIVED:
        raise ApiError("循環已封存，不可重複確認", status=409)
    if c_state == STATE_ABANDONED:
        raise ApiError("循環已放棄，不可確認", status=409)

    eff_reviewer = reviewer_id or "system_reviewer"

    # 1. 冪等檢查：已 CONFIRMED 且相同 content_hash 重送 (Test 8)
    conn = store._connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM cycle_confirmations WHERE cycle_id = ?", (cycle_id,))
        existing_conf = cur.fetchone()
    finally:
        conn.close()

    if c_state == STATE_CONFIRMED and existing_conf:
        if existing_conf["content_hash"] == content_hash:
            return {
                "cycle": cycle,
                "draft_id": existing_conf["draft_id"],
                "content_hash": content_hash,
            }

    # 2. 取得當前草稿
    draft_id = cycle.get("draft_id")
    if not draft_id:
        raise ApiError("循環尚未綁定草稿", status=409)

    draft = store.get_soap_draft(draft_id)
    if not draft:
        raise ApiError("草稿不存在", status=404)

    # 3. DRAFT_UNUSABLE 必須提供修改後 soap (Test 7)
    if c_state == STATE_DRAFT_UNUSABLE and soap is None:
        raise ApiError("草稿需修改後才能存檔", status=422)

    # 4. content_hash 檢查
    if content_hash != draft.content_hash:
        raise ApiError("草稿版本已過期，請重新載入後再存檔", status=409)

    # 5. 處理修改後的 SOAP 或直接採用原草稿
    target_draft_id = draft.draft_id
    effective_soap = draft.soap
    effective_version = draft.version
    effective_hash = draft.content_hash

    if soap is not None:
        # 重新檢核品質 (Test 5)
        q_res = validate_soap_quality(soap)
        is_pass = bool(q_res.get("pass"))

        if not is_pass:
            # 修改後仍不合格 → 轉 DRAFT_UNUSABLE (若尚未是的話)，不排任務
            if c_state != STATE_DRAFT_UNUSABLE:
                transition_cycle(
                    store,
                    cycle_id,
                    STATE_DRAFT_UNUSABLE,
                    actor=eff_reviewer,
                    reason_code="quality_failed",
                )
            raise ApiError(
                "SOAP 品質檢核未通過",
                status=422,
                extra={
                    "quality_issues": q_res.get("issues", []),
                    "quality_score": q_res.get("quality_score"),
                },
            )

        if c_state == STATE_DRAFT_UNUSABLE:
            # Test 6: DRAFT_UNUSABLE 帶合格 soap → 建立新草稿改綁定，舊草稿不動
            new_draft = store.create_soap_draft(
                case_id=draft.case_id,
                soap=soap,
                order_code=draft.order_code,
                state=STATE_VALIDATED,
            )
            target_draft_id = new_draft.draft_id
            effective_soap = new_draft.soap
            effective_version = new_draft.version
            effective_hash = new_draft.content_hash

            # 更新 recording_cycles 的 draft_id
            conn_u = store._connect()
            try:
                with conn_u:
                    conn_u.execute(
                        "UPDATE recording_cycles SET draft_id = ?, updated_at = ? WHERE cycle_id = ?",
                        (target_draft_id, _now_iso(), cycle_id),
                    )
            finally:
                conn_u.close()
        else:
            # AWAITING_CONFIRM 正常修改版 → 更新草稿並遞增版本 (Test 4)
            updated_draft = store.edit_soap_draft(
                draft.draft_id,
                soap,
                reviewer_id=eff_reviewer,
                quality_score=q_res.get("quality_score"),
                quality_issues=q_res.get("issues"),
                is_quality_pass=True,
            )
            target_draft_id = updated_draft.draft_id
            effective_soap = updated_draft.soap
            effective_version = updated_draft.version
            effective_hash = updated_draft.content_hash

    # 6. 寫入 cycle_confirmations (先寫確認版)
    now_str = _now_iso()
    # 讀取完整 extras_json
    conn_ext = store._connect()
    try:
        cur = conn_ext.cursor()
        cur.execute("SELECT extras_json FROM recording_cycles WHERE cycle_id = ?", (cycle_id,))
        row_ext = cur.fetchone()
        extras_json = row_ext["extras_json"] if row_ext else None
    finally:
        conn_ext.close()

    conn_conf = store._connect()
    try:
        with conn_conf:
            cur = conn_conf.cursor()
            cur.execute(
                """
                INSERT INTO cycle_confirmations (
                    cycle_id, draft_id, version, content_hash, soap_json,
                    extras_json, reviewer_id, confirmed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cycle_id) DO UPDATE SET
                    draft_id = excluded.draft_id,
                    version = excluded.version,
                    content_hash = excluded.content_hash,
                    soap_json = excluded.soap_json,
                    extras_json = excluded.extras_json,
                    reviewer_id = excluded.reviewer_id,
                    confirmed_at = excluded.confirmed_at
                """,
                (
                    cycle_id,
                    target_draft_id,
                    effective_version,
                    effective_hash,
                    json.dumps(effective_soap, ensure_ascii=False),
                    extras_json,
                    eff_reviewer,
                    now_str,
                ),
            )
    finally:
        conn_conf.close()

    # 7. 排入 HIS_PUSH 任務 (綁定 machine_id)
    approve_and_enqueue(
        store,
        draft_id=target_draft_id,
        reviewer_id=eff_reviewer,
        machine_id=cycle.get("machine_id"),
    )

    # 8. 循環狀態推進至 CONFIRMED
    updated_cycle = transition_cycle(
        store,
        cycle_id,
        STATE_CONFIRMED,
        actor=eff_reviewer,
        expect_from=(STATE_AWAITING_CONFIRM, STATE_DRAFT_UNUSABLE, STATE_CONFIRMED),
        fields={"draft_id": target_draft_id},
    )

    # 9. 審計紀錄（只含識別碼，零 PHI，Test 10）
    try:
        audit_log.record_access(
            caller_id=eff_reviewer,
            method="POST",
            path=f"/api/cycles/{cycle_id}/confirm",
            status=200,
            detail={
                "action": "cycle_confirm",
                "cycle_id": cycle_id,
                "draft_id": target_draft_id,
                "content_hash": effective_hash,
            },
        )
    except Exception as exc:
        logger.warning("寫入存取審計日誌失敗: %s", exc)

    return {
        "status": "ok",
        "cycle": updated_cycle,
        "draft_id": target_draft_id,
        "content_hash": effective_hash,
    }


def archive_cycle(
    store,
    *,
    cycle_id: str,
    actor: Optional[str] = None,
) -> Tuple[int, Dict[str, Any]]:
    """黃燈封存檢查與收斂 (契約 §3, D-31-06, D-31-07, D-31-08, D-31-14).

    回傳：
        (status_code, body_dict)
        - 200: {"status": "archived"} 或 {"status": "already_archived"}
        - 202: {"status": "his_pending"} 或 {"status": "his_retry_queued"}
        - 409: {"status": "not_confirmed"} 或 {"status": "his_failed", "reason": ...}
    """
    cycle = get_cycle(store, cycle_id)
    if not cycle:
        return 404, {"status": "error", "message": "循環不存在"}

    c_state = cycle["state"]
    if c_state == STATE_ARCHIVED:
        return 200, {"status": "already_archived"}

    # 1. 檢查是否在允許封存之狀態 (CONFIRMED / ARCHIVING / ARCHIVE_FAILED)
    if c_state not in (STATE_CONFIRMED, STATE_ARCHIVING, STATE_ARCHIVE_FAILED):
        return 409, {"status": "not_confirmed", "message": "循環尚未確認存檔"}

    eff_actor = actor or "system"

    # 2. 檢查確認版是否存在 (Test 6)
    conn = store._connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM cycle_confirmations WHERE cycle_id = ?", (cycle_id,))
        conf_row = cur.fetchone()
    finally:
        conn.close()

    if not conf_row:
        if c_state != STATE_ARCHIVE_FAILED:
            transition_cycle(
                store,
                cycle_id,
                STATE_ARCHIVE_FAILED,
                actor=eff_actor,
                reason_code="confirmation_missing",
            )
        return 409, {"status": "his_failed", "reason": "confirmation_missing"}

    # 3. 取得草稿狀態
    draft_id = cycle.get("draft_id")
    if not draft_id:
        return 409, {"status": "not_confirmed", "message": "無綁定草稿"}

    draft = store.get_soap_draft(draft_id)
    if not draft:
        return 404, {"status": "error", "message": "草稿不存在"}

    # A. 草稿已 pushed → 完成封存！ (Test 3)
    if draft.state == STATE_PUSHED:
        try:
            transition_cycle(
                store,
                cycle_id,
                STATE_ARCHIVED,
                actor=eff_actor,
                reason_code="archived",
                expect_from=(STATE_CONFIRMED, STATE_ARCHIVING, STATE_ARCHIVE_FAILED),
            )
            # 審計紀錄
            try:
                audit_log.record_access(
                    caller_id=eff_actor,
                    method="POST",
                    path=f"/api/cycles/{cycle_id}/archive",
                    status=200,
                    detail={
                        "action": "cycle_archive",
                        "cycle_id": cycle_id,
                        "draft_id": draft_id,
                    },
                )
            except Exception as exc:
                logger.warning("寫入封存審計失敗: %s", exc)
            return 200, {"status": "archived"}
        except IllegalCycleTransitionError:
            # 併發競爭 CAS：重新檢查是否已為 ARCHIVED (Test 8)
            recheck = get_cycle(store, cycle_id)
            if recheck and recheck["state"] == STATE_ARCHIVED:
                return 200, {"status": "already_archived"}
            raise

    # B. 草稿進行中 (approved / queued)
    if draft.state in (STATE_APPROVED, STATE_QUEUED):
        # 若處於 approved 且卡住無任務，重入恢復 (Test 7)
        if draft.state == STATE_APPROVED:
            approve_and_enqueue(
                store,
                draft_id=draft.draft_id,
                reviewer_id=eff_actor,
                machine_id=cycle.get("machine_id"),
            )
        if c_state != STATE_ARCHIVING:
            transition_cycle(
                store,
                cycle_id,
                STATE_ARCHIVING,
                actor=eff_actor,
                reason_code="his_pending",
                expect_from=(STATE_CONFIRMED, STATE_ARCHIVING, STATE_ARCHIVE_FAILED),
            )
        return 202, {"status": "his_pending"}

    # C. 草稿失敗 (failed)
    if draft.state == STATE_FAILED:
        if c_state == STATE_ARCHIVE_FAILED:
            # Test 5 retry: 從 ARCHIVE_FAILED 再按黃燈重試 → 排入新任務
            approve_and_enqueue(
                store,
                draft_id=draft.draft_id,
                reviewer_id=eff_actor,
                machine_id=cycle.get("machine_id"),
            )
            transition_cycle(
                store,
                cycle_id,
                STATE_ARCHIVING,
                actor=eff_actor,
                reason_code="his_retry",
                expect_from=(STATE_ARCHIVE_FAILED,),
            )
            return 202, {"status": "his_retry_queued"}
        else:
            # 首次得知失敗 (Test 4)
            reason = draft.failure_reason or "HIS 寫入失敗"
            transition_cycle(
                store,
                cycle_id,
                STATE_ARCHIVE_FAILED,
                actor=eff_actor,
                reason_code="his_failed",
                expect_from=(STATE_CONFIRMED, STATE_ARCHIVING),
            )
            return 409, {"status": "his_failed", "reason": reason}

    # 其餘狀態（如尚未核准之 draft 等）
    return 409, {"status": "not_confirmed", "message": f"草稿尚未進入排程 (狀態: {draft.state})"}
