"""醫師審核 API 路由（Phase 29 §6）。

提供端點：
- GET  /api/soap/drafts/<draft_id>         讀取草稿內容、版本、品質分數、比對摘要
- POST /api/soap/drafts/<draft_id>/approve 醫師核准草稿並排入 HIS_PUSH 任務（冪等檢查）
- POST /api/soap/drafts/<draft_id>/edit    醫師編修草稿（版本遞增、重新檢核與比對）
- POST /api/soap/drafts/<draft_id>/reject  醫師退回草稿（記錄原因，不含病患資料）
- POST /api/soap/drafts                    建立 SOAP 草稿（供預生成或測試使用）

限制規範：
- 日誌與審計紀錄一律嚴禁包含 SOAP 內文（個資與病歷隱私保全）。
- 不得改動 Stage 2 案件狀態。
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from elc_audit_engine import audit_log
from elc_audit_engine.bridge_queue import enqueue_job
from elc_audit_engine.case_store import CaseNotFoundError
from elc_audit_engine.case_store.soap_draft_states import (
    STATE_APPROVED,
    STATE_FAILED,
    STATE_PUSHED,
    STATE_QUALITY_FAILED,
    STATE_QUEUED,
    STATE_REJECTED,
    STATE_VALIDATED,
    IllegalDraftTransitionError,
)
from elc_audit_engine.comparator.soap_advice import validate_soap_quality
from elc_audit_engine.comparator.soap_comparison import compare_soap_with_template

from ..context import caller_id, case_store
from ..errors import ApiError

logger = logging.getLogger(__name__)
bp = Blueprint("soap_review", __name__)


def _json_object() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("請求內容必須為 JSON 物件")
    return data


def _draft_or_404(draft_id: str):
    try:
        return case_store().get_soap_draft(draft_id)
    except CaseNotFoundError:
        raise ApiError(f"查無 SOAP 草稿：{draft_id}", status=404)


@bp.route("/api/soap/drafts", methods=["POST"])
def create_draft():
    """建立新 SOAP 草稿並自動執行品質檢核與標準範本比對。"""
    data = _json_object()
    case_id = str(data.get("case_id") or "").strip()
    if not case_id:
        raise ApiError("缺少 case_id", status=422)
    soap = data.get("soap")
    if not isinstance(soap, dict):
        raise ApiError("缺少 soap 物件", status=422)
    order_code = data.get("order_code")

    store = case_store()

    # 品質檢核
    q_res = validate_soap_quality(soap)
    initial_state = STATE_VALIDATED if q_res.get("pass") else STATE_QUALITY_FAILED

    # 標準範本比對（advisory，來源為現有 soap_templates，見 29-DESIGN.md §5, §11）
    comparison: dict[str, Any] | None = None
    if order_code:
        case = store.get(case_id)
        primary_dx = case.primary_diagnosis if case and getattr(case, "primary_diagnosis", None) else ""
        tmpl = store.get_soap_template(order_code, primary_dx)
        if tmpl and tmpl.get("soap"):
            comparison = compare_soap_with_template(soap, tmpl["soap"])

    draft = store.create_soap_draft(
        case_id=case_id,
        order_code=order_code,
        soap=soap,
        state=initial_state,
        quality_score=q_res.get("quality_score"),
        quality_issues=q_res.get("issues"),
        comparison=comparison,
    )

    # 審計紀錄（不記錄 SOAP 內文）
    try:
        audit_log.record_access(
            caller_id=caller_id() or "anonymous",
            method="POST",
            path=request.path,
            status=201,
            detail={"action": "soap_draft_create", "draft_id": draft.draft_id},
        )
    except Exception as exc:
        current_app.logger.warning("寫入審計日誌失敗：%s", exc)

    return jsonify({"status": "success", "draft": _draft_to_dict(draft)}), 201


@bp.route("/api/soap/drafts/<draft_id>", methods=["GET"])
def get_draft(draft_id: str):
    """讀取草稿內容與審核狀態。"""
    draft = _draft_or_404(draft_id)
    return jsonify({"status": "success", "draft": _draft_to_dict(draft)})


@bp.route("/api/soap/drafts/<draft_id>/approve", methods=["POST"])
def approve_draft(draft_id: str):
    """醫師審核核准：核對 content_hash、執行冪等檢查，成功後排入 HIS_PUSH 任務。"""
    data = _json_object()
    draft = _draft_or_404(draft_id)

    # 1. 驗證 content_hash（防止審核舊版）
    presented_hash = data.get("content_hash")
    if not presented_hash or presented_hash != draft.content_hash:
        raise ApiError(
            "審核失敗：content_hash 與目前草稿版本不符（草稿可能已被更新或已被編修）",
            status=409,
        )

    # 2. 狀態檢查：僅 validated 或 failed（重試）可核准
    if draft.state not in (STATE_VALIDATED, STATE_FAILED):
        raise ApiError(
            f"草稿狀態為 {draft.state}，不允許執行核准",
            status=409,
        )

    eff_reviewer = str(data.get("reviewer_id") or caller_id() or "unknown_reviewer")
    store = case_store()

    # 3. 冪等檢查（§8.6）：同一 case_id 與 content_hash 若已 pushed，不重複寫入
    already_pushed = store.find_pushed_soap_draft(draft.case_id, draft.content_hash)
    if already_pushed is not None:
        return jsonify(
            {
                "status": "already_pushed",
                "message": "同一案件與內容先前已成功寫入 HIS，略過重複寫入",
                "draft_id": draft.draft_id,
                "pushed_draft_id": already_pushed.draft_id,
            }
        ), 200

    # 4. 狀態轉換：validated/failed -> approved -> queued
    try:
        draft = store.update_soap_draft_state(
            draft_id,
            STATE_APPROVED,
            reviewer_id=eff_reviewer,
            decision="approved",
        )
    except IllegalDraftTransitionError as exc:
        raise ApiError(str(exc), status=409)

    # 5. 排入 HIS_PUSH bridge 任務
    job = enqueue_job(
        store,
        s_type_code="HIS_PUSH",
        target_id=draft.case_id,
        actor=eff_reviewer,
        extra_payload={
            "draft_id": draft.draft_id,
            "case_id": draft.case_id,
            "order_code": draft.order_code,
            "version": draft.version,
            "content_hash": draft.content_hash,
            "soap": draft.soap,
        },
    )

    # 標記為 queued
    draft = store.update_soap_draft_state(draft_id, STATE_QUEUED)

    # 審計紀錄（絕不記錄 SOAP 內文）
    try:
        audit_log.record_access(
            caller_id=eff_reviewer,
            method="POST",
            path=request.path,
            status=200,
            detail={
                "action": "soap_review_approve",
                "draft_id": draft.draft_id,
                "content_hash": draft.content_hash,
            },
        )
    except Exception as exc:
        current_app.logger.warning("寫入審計日誌失敗：%s", exc)

    return jsonify({"status": "success", "draft": _draft_to_dict(draft), "job": job}), 200


@bp.route("/api/soap/batches/<batch_id>/approve", methods=["POST"])
def approve_batch(batch_id: str):
    """批次核准：對批次內指定的 validated 草稿，逐案以各自 content_hash 核准。

    body: {
        "items": [{"draft_id": "...", "content_hash": "..."}, ...],
        "reviewer_id": "..." (選填)
    }
    若未傳入 items，則自動找出所有目前處於 validated 狀態的草稿進行核准。
    回傳每案核准結果，content_hash 已變動者標記為 skipped 不予核准。
    """
    data = _json_object()
    eff_reviewer = str(data.get("reviewer_id") or caller_id() or "unknown_reviewer")
    store = case_store()
    items = data.get("items")

    targets: list[tuple[str, str | None]] = []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict) and "draft_id" in it:
                targets.append((str(it["draft_id"]), it.get("content_hash")))
    else:
        # 自動查找所有 validated 草稿
        all_validated = store.list_soap_drafts(state=STATE_VALIDATED, limit=500)
        targets = [(d.draft_id, d.content_hash) for d in all_validated]

    results = []
    approved_count = 0
    for draft_id, expected_hash in targets:
        try:
            draft = store.get_soap_draft(draft_id)
        except CaseNotFoundError:
            draft = None
        if not draft:
            # 單筆查無不應使整批失敗：標記該筆錯誤，其餘照常處理
            results.append({"draft_id": draft_id, "status": "error", "message": "草稿不存在"})
            continue

        if expected_hash and draft.content_hash != expected_hash:
            results.append({
                "draft_id": draft_id,
                "status": "skipped",
                "message": "content_hash 與當前版本不符（草稿已變動）",
            })
            continue

        if draft.state not in (STATE_VALIDATED, STATE_FAILED):
            results.append({
                "draft_id": draft_id,
                "status": "skipped",
                "message": f"草稿狀態為 {draft.state}，非待審核狀態",
            })
            continue

        already_pushed = store.find_pushed_soap_draft(draft.case_id, draft.content_hash)
        if already_pushed is not None:
            results.append({
                "draft_id": draft_id,
                "status": "already_pushed",
                "message": "同一案件與內容先前已寫入 HIS",
            })
            continue

        try:
            store.update_soap_draft_state(
                draft_id,
                STATE_APPROVED,
                reviewer_id=eff_reviewer,
                decision="approved",
            )
            job = enqueue_job(
                store,
                s_type_code="HIS_PUSH",
                target_id=draft.case_id,
                actor=eff_reviewer,
                extra_payload={
                    "draft_id": draft.draft_id,
                    "case_id": draft.case_id,
                    "order_code": draft.order_code,
                    "version": draft.version,
                    "content_hash": draft.content_hash,
                    "soap": draft.soap,
                },
            )
            store.update_soap_draft_state(draft_id, STATE_QUEUED)
            results.append({
                "draft_id": draft_id,
                "status": "approved",
                "job_id": job.get("job_id"),
            })
            approved_count += 1
        except Exception as exc:
            results.append({"draft_id": draft_id, "status": "error", "message": str(exc)})

    return jsonify({
        "status": "success",
        "batch_id": batch_id,
        "total_targets": len(targets),
        "approved_count": approved_count,
        "results": results,
    }), 200


@bp.route("/api/soap/drafts/<draft_id>/edit", methods=["POST"])
def edit_draft(draft_id: str):
    """醫師修改 S/O/A/P：版本遞增、重新檢核與比對。"""
    data = _json_object()
    draft = _draft_or_404(draft_id)

    if draft.state in (STATE_PUSHED, STATE_QUEUED):
        raise ApiError(f"草稿狀態為 {draft.state}，已進入寫入流程或已完成，不允許直接編修", status=409)

    new_soap = data.get("soap")
    if not isinstance(new_soap, dict):
        raise ApiError("缺少新的 soap 物件", status=422)

    eff_reviewer = str(data.get("reviewer_id") or caller_id() or "unknown_reviewer")
    store = case_store()

    # 重新檢核品質
    q_res = validate_soap_quality(new_soap)
    is_pass = bool(q_res.get("pass"))

    # 重新比對標準範本（現有 soap_templates）
    comparison: dict[str, Any] | None = None
    if draft.order_code:
        case = store.get(draft.case_id)
        primary_dx = case.primary_diagnosis if case and getattr(case, "primary_diagnosis", None) else ""
        tmpl = store.get_soap_template(draft.order_code, primary_dx)
        if tmpl and tmpl.get("soap"):
            comparison = compare_soap_with_template(new_soap, tmpl["soap"])

    try:
        updated = store.edit_soap_draft(
            draft_id,
            new_soap,
            reviewer_id=eff_reviewer,
            quality_score=q_res.get("quality_score"),
            quality_issues=q_res.get("issues"),
            comparison=comparison,
            is_quality_pass=is_pass,
        )
    except IllegalDraftTransitionError as exc:
        raise ApiError(str(exc), status=409)

    # 審計紀錄（絕不記錄 SOAP 內文）
    try:
        audit_log.record_access(
            caller_id=eff_reviewer,
            method="POST",
            path=request.path,
            status=200,
            detail={
                "action": "soap_review_edit",
                "draft_id": draft.draft_id,
                "version": str(updated.version),
            },
        )
    except Exception as exc:
        current_app.logger.warning("寫入審計日誌失敗：%s", exc)

    return jsonify({"status": "success", "draft": _draft_to_dict(updated)}), 200


@bp.route("/api/soap/drafts/<draft_id>/reject", methods=["POST"])
def reject_draft(draft_id: str):
    """醫師退回草稿：記錄退回原因（代碼＋說明，不含病患資料），狀態為 rejected（終態）。"""
    data = _json_object()
    draft = _draft_or_404(draft_id)

    if draft.state in (STATE_PUSHED, STATE_REJECTED):
        raise ApiError(f"草稿狀態為 {draft.state}，不允許退回", status=409)

    reason = str(data.get("reason") or "").strip()
    reason_code = str(data.get("reason_code") or "").strip()
    if not reason and not reason_code:
        raise ApiError("退回時必須附帶原因說明或原因代碼", status=422)

    eff_reason = f"[{reason_code}] {reason}".strip() if reason_code else reason
    eff_reviewer = str(data.get("reviewer_id") or caller_id() or "unknown_reviewer")

    try:
        updated = case_store().update_soap_draft_state(
            draft_id,
            STATE_REJECTED,
            reviewer_id=eff_reviewer,
            decision="rejected",
            reason=eff_reason,
        )
    except IllegalDraftTransitionError as exc:
        raise ApiError(str(exc), status=409)

    # 審計紀錄（不記錄 PHI）
    try:
        audit_log.record_access(
            caller_id=eff_reviewer,
            method="POST",
            path=request.path,
            status=200,
            detail={
                "action": "soap_review_reject",
                "draft_id": draft.draft_id,
                "reason_code": reason_code[:50] if reason_code else "",
            },
        )
    except Exception as exc:
        current_app.logger.warning("寫入審計日誌失敗：%s", exc)

    return jsonify({"status": "success", "draft": _draft_to_dict(updated)}), 200


def _draft_to_dict(draft) -> dict[str, Any]:
    return {
        "draft_id": draft.draft_id,
        "case_id": draft.case_id,
        "order_code": draft.order_code,
        "version": draft.version,
        "state": draft.state,
        "soap": draft.soap,
        "content_hash": draft.content_hash,
        "quality_score": draft.quality_score,
        "quality_issues": draft.quality_issues,
        "comparison": draft.comparison,
        "reviewer_id": draft.reviewer_id,
        "review_decision": draft.review_decision,
        "review_reason": draft.review_reason,
        "reviewed_at": draft.reviewed_at,
        "pushed_at": draft.pushed_at,
        "agent_id": draft.agent_id,
        "failure_reason": draft.failure_reason,
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
    }
