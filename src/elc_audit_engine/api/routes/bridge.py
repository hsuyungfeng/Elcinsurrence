"""地端 Local Agent 橋接 API（Phase 21-03，NHI_EIIAPI 對應）。

- POST /api/bridge/jobs                    建立待送任務（雲端工作台或排程呼叫）
- GET  /api/bridge/jobs/pending            地端 Agent 輪詢待送任務，可用 sTypeCode 過濾
- POST /api/bridge/jobs/<job_id>/status    地端 Agent 回報 SENDING／SUCCESS／FAILED 與 sLocal_ID、sNHI_ID、NHI_Query 狀態
- GET  /api/bridge/jobs/<job_id>           雲端前端即時查詢送審進度

所有端點受全域 API Key 保護（security.before_request）；地端 Agent 須持有有效金鑰。
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from elc_audit_engine.bridge_queue import (
    BridgeConflictError,
    BridgeValidationError,
    enqueue_job,
    get_job,
    list_pending,
    report_status,
)
from elc_audit_engine.case_store import CaseNotFoundError

from ..context import caller_id, case_store
from ..errors import ApiError

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
    try:
        jobs = list_pending(case_store(), s_type_code=s_type_code)
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
    _job_or_404(job_id)
    try:
        job = report_status(
            case_store(),
            job_id,
            status=str(data.get("status") or ""),
            local_id=data.get("sLocal_ID") or None,
            nhi_id=data.get("sNHI_ID") or None,
            nhi_status=data.get("NHI_Query") or data.get("nhi_status") or None,
            actor=caller_id(),
            expected_status=data.get("expected_status") or None,
        )
    except BridgeConflictError as exc:
        raise ApiError(str(exc), status=409)
    except BridgeValidationError as exc:
        raise ApiError(str(exc), status=422)
    return jsonify({"status": "success", "job": job})


@bp.route("/api/bridge/jobs/<job_id>", methods=["GET"])
def get_bridge_job(job_id: str):
    """單一任務進度（雲端前端即時查詢）。"""
    return jsonify({"status": "success", "job": _job_or_404(job_id)})
