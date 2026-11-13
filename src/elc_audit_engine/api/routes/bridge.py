"""地端 Local Agent 橋接 API（Phase 21-03，NHI_EIIAPI 對應）。

- POST /api/bridge/jobs                    建立待送任務（雲端工作台或排程呼叫）
- GET  /api/bridge/jobs/pending            地端 Agent 輪詢待送任務，可用 sTypeCode 過濾
- POST /api/bridge/jobs/<job_id>/status    地端 Agent 回報 SENDING／SUCCESS／FAILED 與 sLocal_ID、sNHI_ID、NHI_Query 狀態
- GET  /api/bridge/jobs/<job_id>           雲端前端即時查詢送審進度

所有端點受全域 API Key 保護（security.before_request）；地端 Agent 須持有有效金鑰。
"""

from __future__ import annotations

import logging
import re

from flask import Blueprint, jsonify, request

from elc_audit_engine.bridge_queue import (
    BridgeConflictError,
    BridgeValidationError,
    enqueue_job,
    get_job,
    list_pending,
    report_status,
)
from elc_audit_engine.case_store import CaseNotFoundError, _UNSET_MACHINE

_MACHINE_ID_RE = re.compile(r"^[0-9a-zA-Z_-]{1,64}$")

from ..context import caller_id, case_store
from ..errors import ApiError

logger = logging.getLogger(__name__)

bp = Blueprint("bridge", __name__)


def _json_object() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("請求內容必須為 JSON 物件")
    return data


def _job_or_404(job_id: str) -> dict:
    try:
        return get_job(case_store(), job_id)
    except (CaseNotFoundError, LookupError):
        raise ApiError("查無此任務", status=404)


@bp.route("/api/bridge/jobs", methods=["POST"])
def create_bridge_job():
    """建立待送任務：{"s_type_code": "15"|"00"|"07"|"09", "target_id": 批次年月或案件 ID}。"""
    data = _json_object()
    try:
        job = enqueue_job(
            case_store(),
            s_type_code=str(data.get("s_type_code") or ""),
            target_id=str(data.get("target_id") or ""),
            actor=caller_id(),
        )
    except BridgeValidationError as exc:
        raise ApiError(str(exc), status=422)
    return jsonify({"status": "success", "job": job}), 201


@bp.route("/api/bridge/jobs/pending", methods=["GET"])
def list_pending_jobs():
    """地端 Agent 輪詢：回傳 PENDING 任務（含 download_path，Agent 以 API Key 下載）。"""
    s_type_code = request.args.get("sTypeCode") or None
    machine_id = request.args.get("machine_id") or None
    if machine_id:
        if not _MACHINE_ID_RE.match(machine_id):
            raise ApiError(f"不合法的 machine_id 格式：{machine_id!r}", status=422)

    if s_type_code == "HIS_PUSH":
        target_machine = machine_id if machine_id else None
    else:
        target_machine = _UNSET_MACHINE

    try:
        jobs = list_pending(case_store(), s_type_code=s_type_code, machine_id=target_machine)
    except BridgeValidationError as exc:
        raise ApiError(str(exc), status=422)
    return jsonify({"status": "success", "count": len(jobs), "jobs": jobs})


@bp.route("/api/bridge/jobs/<job_id>/status", methods=["POST"])
def report_bridge_job_status(job_id: str):
    """地端 Agent 回報狀態。

    請求：{"status": "SENDING"|"SUCCESS"|"FAILED", "sLocal_ID": ..., "sNHI_ID": ..., "NHI_Query": "A12"}
    狀態轉換不合法 409；NHI_Query 格式不符 422；任務不存在 404。
    """
    data = _json_object()
    current = _job_or_404(job_id)
    new_status = str(data.get("status") or "")
    req_machine_id = data.get("machine_id")

    # Phase 31 D-31-37：在同步草稿前先驗證 machine_id，不符直接 409
    job_machine_id = (current.get("extra_payload") or {}).get("machine_id")
    if job_machine_id:
        if not req_machine_id or req_machine_id != job_machine_id:
            raise ApiError(
                f"任務已綁定機器 {job_machine_id}，與請求機器 {req_machine_id} 不符",
                status=409,
            )

    # Phase 29 §8.5：HIS_PUSH 任務的草稿狀態須先於佇列回報同步。
    # 同步失敗時不標記任務成功（回 500），讓 Agent 重送；不得靜默吞掉例外（P1-1）。
    draft_id = None
    if current.get("s_type_code") == "HIS_PUSH":
        draft_id = (current.get("extra_payload") or {}).get("draft_id")
    if draft_id and new_status in ("SUCCESS", "FAILED"):
        _sync_draft_before_report(case_store(), draft_id, new_status, data)

    try:
        job = report_status(
            case_store(),
            job_id,
            status=new_status,
            local_id=data.get("sLocal_ID") or None,
            nhi_id=data.get("sNHI_ID") or None,
            nhi_status=data.get("NHI_Query") or data.get("nhi_status") or None,
            actor=caller_id(),
            expected_status=data.get("expected_status") or None,
            machine_id=req_machine_id,
        )
    except BridgeConflictError as exc:
        raise ApiError(str(exc), status=409)
    except BridgeValidationError as exc:
        raise ApiError(str(exc), status=422)

    return jsonify({"status": "success", "job": job})


def _sync_draft_before_report(store, draft_id: str, new_status: str, data: dict) -> None:
    """HIS_PUSH 回報前同步草稿：SUCCESS → pushed；FAILED → failed。已處於目標狀態者略過（重送冪等）。"""
    try:
        draft = store.get_soap_draft(draft_id)
    except Exception as exc:  # 草稿不存在或讀取失敗：不得假裝已同步
        logger.error("HIS_PUSH 草稿讀取失敗 draft_id=%s: %s", draft_id, type(exc).__name__)
        raise ApiError("草稿狀態同步失敗（草稿不存在或讀取失敗），任務未標記成功", status=500)
    target = "pushed" if new_status == "SUCCESS" else "failed"
    if draft.state == target:
        return
    try:
        if target == "pushed":
            store.update_soap_draft_state(draft_id, "pushed", agent_id=caller_id())
        else:
            reason = str(data.get("reason") or data.get("failure_reason") or "bridge_failed")
            store.update_soap_draft_state(draft_id, "failed", failure_reason=reason)
    except Exception as exc:
        logger.error("HIS_PUSH 草稿狀態同步失敗 draft_id=%s target=%s: %s", draft_id, target, type(exc).__name__)
        raise ApiError("草稿狀態同步失敗，任務未標記成功，請稍後重送回報", status=500)


@bp.route("/api/bridge/jobs/<job_id>", methods=["GET"])
def get_bridge_job(job_id: str):
    """單一任務進度（雲端前端即時查詢）。"""
    return jsonify({"status": "success", "job": _job_or_404(job_id)})
