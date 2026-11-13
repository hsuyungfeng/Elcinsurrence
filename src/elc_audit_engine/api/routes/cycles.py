"""Phase 31: 循環管理 API 路由 (POST /api/cycles, GET, stop, abandon, draft).

限制規範：
- 受全域 API Key 保護（非 Agent 專用 key；Agent 金鑰 403）。
- 審計紀錄嚴禁包含任何 SOAP 或病歷內容。
- 放棄循環（abandon）絕不刪除任何檔案（D-31-29）。
- 循環草稿送出需 upload_complete=1，以 session_id 冪等。
"""

from __future__ import annotations

import logging
import re

from flask import Blueprint, current_app, jsonify, request

from elc_audit_engine import audit_log
from elc_audit_engine.api.context import caller_id, case_store
from elc_audit_engine.api.errors import ApiError
from elc_audit_engine.cycles.states import (
    STATE_ABANDONED,
    STATE_AWAITING_CONFIRM,
    STATE_AWAITING_DRAFT,
    STATE_DRAFT_UNUSABLE,
    STATE_RECORDING,
    IllegalCycleTransitionError,
)
from elc_audit_engine.cycles.store import (
    ActiveCycleExistsError,
    create_cycle,
    get_active_cycle,
    get_cycle,
    transition_cycle,
)

logger = logging.getLogger(__name__)

bp = Blueprint("cycles", __name__)

_CYCLE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_COMMAND_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_MACHINE_ID_RE = re.compile(r"^[0-9a-zA-Z_-]{1,64}$")
_ROOM_ID_RE = re.compile(r"^[\w\-]{1,32}$", re.UNICODE)


def _json_object() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("請求內文必須為 JSON 物件", status=400)
    return data


@bp.route("/api/cycles", methods=["POST"])
def create_new_cycle():
    """建立新循環（快捷列紅燈觸發）。以 command_id 冪等。"""
    data = _json_object()
    command_id = str(data.get("command_id") or "")
    machine_id = str(data.get("machine_id") or "")
    room_id = data.get("room_id")

    if not _COMMAND_ID_RE.match(command_id):
        raise ApiError(f"不合法的 command_id 格式：{command_id!r}", status=422)
    if not _MACHINE_ID_RE.match(machine_id):
        raise ApiError(f"不合法的 machine_id 格式：{machine_id!r}", status=422)
    if room_id is not None:
        room_id = str(room_id)
        if not _ROOM_ID_RE.match(room_id):
            raise ApiError(f"不合法的 room_id 格式：{room_id!r}", status=422)

    store = case_store()
    try:
        cycle, created = create_cycle(
            store,
            command_id=command_id,
            machine_id=machine_id,
            room_id=room_id,
            actor=caller_id(),
        )
    except ActiveCycleExistsError as exc:
        return jsonify({
            "error": "active_cycle_exists",
            "active_cycle_id": exc.active_cycle_id,
            "message": "該工作站已有進行中的循環",
        }), 409

    status_code = 201 if created else 200
    try:
        audit_log.record_access(
            caller_id=caller_id(),
            method="POST",
            path=request.path,
            status=status_code,
            detail={
                "action": "cycle_create",
                "cycle_id": cycle["cycle_id"],
                "machine_id": machine_id,
                "command_id": command_id,
                "created": created,
            },
        )
    except Exception as exc:
        current_app.logger.warning("寫入審計日誌失敗：%s", exc)

    return jsonify({"status": "success", "cycle": cycle}), status_code


@bp.route("/api/cycles", methods=["GET"])
def query_cycles():
    """依 machine_id 查詢該機目前未終結之循環。"""
    machine_id = request.args.get("machine_id")
    if not machine_id:
        raise ApiError("缺少必要的 query 參數 machine_id", status=422)
    if not _MACHINE_ID_RE.match(machine_id):
        raise ApiError(f"不合法的 machine_id 格式：{machine_id!r}", status=422)

    cycle = get_active_cycle(case_store(), machine_id)
    return jsonify({"status": "success", "cycle": cycle}), 200


@bp.route("/api/cycles/<cycle_id>", methods=["GET"])
def get_cycle_by_id(cycle_id: str):
    """依 cycle_id 查詢循環進度與狀態。"""
    if not _CYCLE_ID_RE.match(cycle_id):
        raise ApiError("查無此循環", status=404)

    cycle = get_cycle(case_store(), cycle_id)
    if not cycle:
        raise ApiError("查無此循環", status=404)

    return jsonify({"status": "success", "cycle": cycle}), 200


@bp.route("/api/cycles/<cycle_id>/stop", methods=["POST"])
def stop_recording_cycle(cycle_id: str):
    """結束錄音：將循環由 RECORDING 推進至 AWAITING_DRAFT。以 command_id 冪等。"""
    if not _CYCLE_ID_RE.match(cycle_id):
        raise ApiError("查無此循環", status=404)

    data = _json_object()
    command_id = str(data.get("command_id") or "")
    if not _COMMAND_ID_RE.match(command_id):
        raise ApiError(f"不合法的 command_id 格式：{command_id!r}", status=422)

    store = case_store()
    current = get_cycle(store, cycle_id)
    if not current:
        raise ApiError("查無此循環", status=404)

    conn = store._connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT stop_command_id FROM recording_cycles WHERE cycle_id = ?", (cycle_id,))
        row = cur.fetchone()
        if row and row["stop_command_id"] == command_id:
            return jsonify({"status": "success", "cycle": current}), 200
    finally:
        conn.close()

    if current["state"] != STATE_RECORDING:
        raise ApiError(f"狀態為 {current['state']}，非錄音中無法結束錄音", status=409)

    try:
        cycle = transition_cycle(
            store,
            cycle_id,
            STATE_AWAITING_DRAFT,
            actor=caller_id(),
            expect_from=STATE_RECORDING,
            fields={"stop_command_id": command_id},
        )
    except IllegalCycleTransitionError as exc:
        raise ApiError(str(exc), status=409)

    try:
        audit_log.record_access(
            caller_id=caller_id(),
            method="POST",
            path=request.path,
            status=200,
            detail={
                "action": "cycle_stop",
                "cycle_id": cycle_id,
                "command_id": command_id,
            },
        )
    except Exception as exc:
        current_app.logger.warning("寫入審計日誌失敗：%s", exc)

    return jsonify({"status": "success", "cycle": cycle}), 200


@bp.route("/api/cycles/<cycle_id>/abandon", methods=["POST"])
def abandon_cycle(cycle_id: str):
    """放棄循環：將循環標記為終態 ABANDONED。不刪除任何既有檔案 (D-31-29)。"""
    if not _CYCLE_ID_RE.match(cycle_id):
        raise ApiError("查無此循環", status=404)

    data = _json_object()
    reason_code = str(data.get("reason_code") or "user_abandon")

    store = case_store()
    current = get_cycle(store, cycle_id)
    if not current:
        raise ApiError("查無此循環", status=404)

    allowed_states = {
        STATE_RECORDING,
        STATE_AWAITING_DRAFT,
        STATE_AWAITING_CONFIRM,
        STATE_DRAFT_UNUSABLE,
    }
    if current["state"] not in allowed_states:
        raise ApiError(f"狀態為 {current['state']}，不允許放棄循環", status=409)

    try:
        cycle = transition_cycle(
            store,
            cycle_id,
            STATE_ABANDONED,
            actor=caller_id(),
            reason_code=reason_code,
        )
    except IllegalCycleTransitionError as exc:
        raise ApiError(str(exc), status=409)

    try:
        audit_log.record_access(
            caller_id=caller_id(),
            method="POST",
            path=request.path,
            status=200,
            detail={
                "action": "cycle_abandon",
                "cycle_id": cycle_id,
                "reason_code": reason_code,
            },
        )
    except Exception as exc:
        current_app.logger.warning("寫入審計日誌失敗：%s", exc)

    return jsonify({"status": "success", "cycle": cycle}), 200


@bp.route("/api/cycles/<cycle_id>/draft", methods=["POST"])
def submit_draft(cycle_id: str):
    """送出 SoapVoice 產出之草稿與逐字稿至循環（以 session_id 冪等）。"""
    if not _CYCLE_ID_RE.match(cycle_id):
        raise ApiError("查無此循環", status=404)

    data = _json_object()
    store = case_store()

    from elc_audit_engine.cycles.drafts import submit_cycle_draft, validate_draft_payload
    try:
        validate_draft_payload(data)
    except ValueError as exc:
        raise ApiError(str(exc), status=422)

    try:
        cycle, draft_id, created = submit_cycle_draft(
            store,
            cycle_id=cycle_id,
            payload=data,
            actor=caller_id(),
        )
    except LookupError as exc:
        raise ApiError(str(exc), status=404)
    except ValueError as exc:
        raise ApiError(str(exc), status=409)

    status_code = 201 if created else 200
    try:
        audit_log.record_access(
            caller_id=caller_id(),
            method="POST",
            path=request.path,
            status=status_code,
            detail={
                "action": "submit_cycle_draft",
                "cycle_id": cycle_id,
                "draft_id": draft_id,
            },
        )
    except Exception as exc:
        current_app.logger.warning("寫入審計日誌失敗：%s", exc)

    return jsonify({
        "status": "success",
        "cycle": cycle,
        "draft_id": draft_id,
        "draft_state": cycle.get("draft_state"),
    }), status_code


@bp.route("/api/cycles/<cycle_id>/draft", methods=["GET"])
def get_cycle_draft(cycle_id: str):
    """讀取特定循環綁定之草稿、建議與逐字稿（契約 §3）。"""
    if not _CYCLE_ID_RE.match(cycle_id):
        raise ApiError("查無此循環", status=404)

    include_transcript = request.args.get("include_transcript") in ("1", "true", "yes")
    store = case_store()

    from elc_audit_engine.cycles.drafts import cycle_draft_view
    try:
        view = cycle_draft_view(store, cycle_id, include_transcript=include_transcript)
    except LookupError as exc:
        raise ApiError(str(exc), status=404)

    return jsonify(view), 200


@bp.route("/api/cycles/<cycle_id>/confirm", methods=["POST"])
def confirm_cycle_route(cycle_id: str):
    """醫師在確認視窗確認草稿並存檔（契約 §3）。"""
    if not _CYCLE_ID_RE.match(cycle_id):
        raise ApiError("查無此循環", status=404)

    data = _json_object()
    content_hash = data.get("content_hash")
    if not content_hash or not isinstance(content_hash, str):
        raise ApiError("缺少 content_hash", status=422)

    soap = data.get("soap")
    if soap is not None and not isinstance(soap, dict):
        raise ApiError("soap 必須為物件", status=422)

    reviewer = data.get("reviewer_id") or caller_id()
    store = case_store()

    from elc_audit_engine.cycles.archive import confirm_cycle
    result = confirm_cycle(
        store,
        cycle_id=cycle_id,
        content_hash=content_hash,
        soap=soap,
        reviewer_id=reviewer,
    )
    return jsonify(result), 200


@bp.route("/api/cycles/<cycle_id>/archive", methods=["POST"])
def archive_cycle_route(cycle_id: str):
    """黃燈封存與 HIS 寫入完成檢查（契約 §3）。"""
    if not _CYCLE_ID_RE.match(cycle_id):
        raise ApiError("查無此循環", status=404)

    actor = caller_id()
    store = case_store()

    from elc_audit_engine.cycles.archive import archive_cycle
    status_code, body = archive_cycle(store, cycle_id=cycle_id, actor=actor)
    return jsonify(body), status_code

