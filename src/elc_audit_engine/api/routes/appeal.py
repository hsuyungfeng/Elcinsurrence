"""核減事後申復 API：案件清單、申復草稿生成、核減明細匯入。"""

from __future__ import annotations

import json
import os

from flask import Blueprint, current_app, jsonify, request

from elc_audit_engine import attachment_store
from elc_audit_engine.case_store import CaseNotFoundError, IllegalTransitionError
from elc_audit_engine.generators import build_appeal_draft, render_appeal_json
from elc_audit_engine.ingest import MediaExtractError, detect_media_type, extract_text
from elc_audit_engine.parsers.deduction import DeductionFileError, parse_deduction_file
from elc_audit_engine.parsers.models import DeductionRecord
from elc_audit_engine.rule_repository import get_rule
from elc_audit_engine.rule_repository.errors import RuleRepositoryError

from ..cases import persist_cases, to_appeal_case
from ..context import caller_id, case_store
from ..demo_data import DEMO_APPEAL_CASES
from ..errors import ApiError
from ..records import degraded_reason, records_provider, resolve_records_source, resolve_visit_date
from ..uploads import import_error_message, save_upload
from ..validation import MAX_SOAP_CHARS, clean_str, json_body
from ._lists import case_list_response

bp = Blueprint("appeal", __name__)


@bp.route("/api/appeal/cases", methods=["GET"])
def get_appeal_cases():
    """核減申復案件清單（CaseStore 為單一真實來源；未匯入時回示範資料）。"""
    return case_list_response("appeal", DEMO_APPEAL_CASES)


def _opt_int(data: dict, key: str) -> int | None:
    value = data.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(f"欄位 {key} 必須為整數")
    if value < 0:
        raise ApiError(f"欄位 {key} 不得為負數")
    return value


def _advance_to_appealed(case_id: str, draft) -> str | None:
    """A-CR-09：草稿驗證未過（如申覆未填點數、點數超過上界）不得推進 appealed。"""
    if not case_id:
        return None
    if draft.validation_errors:
        return "skipped"
    try:
        case_store().transition(case_id, "appealed", actor=caller_id())
        return "ok"
    except CaseNotFoundError:
        current_app.logger.warning("appeal case_id=%s 不存在，未推進狀態", case_id)
        return "not_found"
    except IllegalTransitionError as exc:
        current_app.logger.warning("appeal case_id=%s 狀態轉換至 appealed 失敗：%s", case_id, exc)
        return "conflict"


@bp.route("/api/appeal/generate", methods=["POST"])
def generate_appeal_draft():
    """生成 D10 四段式申復理由草稿（接 build_appeal_draft）。

    規則全文一律來自規則庫 get_rule，查無則誠實標示查無（P0-1：原實作曾為
    任何醫令捏造法規依據）。
    """
    data = json_body(request)
    case_seq = clean_str(data, "case_seq", required=True)
    order_code = clean_str(data, "order_code", required=True)
    deduction_reason = clean_str(data, "deduction_reason", max_len=MAX_SOAP_CHARS)
    case_id = clean_str(data, "case_id")
    # 病歷號＝LocalFileProvider 的 patient_id（選填；有值才查病史）。
    record_no = clean_str(data, "record_no")
    # 透傳 order_seq（欄 10 醫令序號）→ render_appeal_json p1_order_seq。
    order_seq = clean_str(data, "order_seq")

    is_appealing = data.get("is_appealing", True)
    if not isinstance(is_appealing, bool):
        raise ApiError("欄位 is_appealing 必須為布林值")
    # D-15：申復點數不得超過不予核銷金額，由 build_appeal_draft 硬檢查。
    deduct_amount = _opt_int(data, "deduct_amount")
    claimed_points = _opt_int(data, "claimed_points")

    record = DeductionRecord(
        case_seq=case_seq,
        order_code=order_code,
        deduction_reason=deduction_reason or None,
        non_reimbursed_amount=deduct_amount,
        order_seq=order_seq or None,  # 缺省 None、不捏造
    )

    rule_text = rule_location = None
    try:
        rule = get_rule(order_code)
    except RuleRepositoryError as exc:
        current_app.logger.error("rule repository failure during appeal: %s", exc)
        raise ApiError("規則庫暫時無法查詢，請稍後再試或聯繫系統管理員", status=503)
    if rule.found:
        rule_text = rule.article_full_text or rule.payment_text
        rule_location = rule.article_location

    # 醫師採用的補強敘述（Phase 6 審核軌跡），前端未提供時為空。
    evidence = data.get("evidence", [])
    evidence = [e for e in evidence if isinstance(e, str)] if isinstance(evidence, list) else []

    # p7 附件旗標（A-CR-03）：呼叫方明示優先（須為布林，字串 "false" 會被當真）；
    # 否則以 case_id 查附件——不以流水號查，避免別案附件讓本案 p7=Y。
    if "has_attachment" in data:
        has_attachment = data["has_attachment"]
        if not isinstance(has_attachment, bool):
            raise ApiError("欄位 has_attachment 必須為布林值")
    elif case_id:
        has_attachment = attachment_store.has_attachment(case_id, order_seq or None)
    else:
        has_attachment = False

    visit_date = resolve_visit_date(case_store(), data, case_id)
    timeline, records_source = resolve_records_source(records_provider(), record_no, visit_date)

    draft = build_appeal_draft(
        record,
        is_appealing=is_appealing,
        claimed_points=claimed_points,
        timeline=timeline,
        rule_text=rule_text,
        rule_location=rule_location,
        evidence=evidence,
        has_attachment=has_attachment,
    )
    state_transition = _advance_to_appealed(case_id, draft)

    # W4 契約橋（D-03）：回應主體為 render_appeal_json 標準契約（單一契約）。
    payload = json.loads(render_appeal_json(draft))
    # A-CR-04：通過驗證的草稿寫回 CaseStore，供佐證包列印讀取。
    if state_transition == "ok":
        case_store().set_artifact(case_id, "appeal_draft", payload)
    payload["status"] = "success"
    payload["case_id"] = case_id or None
    payload["state_transition"] = state_transition
    payload["rule_found"] = rule.found
    payload["records_degraded"] = timeline is None
    payload["records_source"] = records_source
    payload["records_window_anchor"] = "visit_date" if visit_date else "today"
    payload["records_degraded_reason"] = degraded_reason(records_source, timeline is None)
    return jsonify(payload)


@bp.route("/api/appeal/import", methods=["POST"])
def import_appeal_cases():
    """批次匯入核減刪減醫令清單。

    CSV：D-14d 18 欄 parser。PDF／影像：**誠實降級**——18 欄結構無法由 OCR
    可靠重建，只回提取文字供參考並提示改用 CSV（錯誤的資料比沒有資料更危險）。
    """
    file = request.files.get("file")
    if file is None or not (file.filename or "").strip():
        raise ApiError("缺少上傳檔案（multipart 欄位名 file）")
    path, filename = save_upload(file, current_app.config["ELC_RAW_DIR"])

    try:
        media_type = detect_media_type(filename)
        if media_type != "csv":
            text, tool = extract_text(path, media_type=media_type)
            return jsonify({
                "status": "partial",
                "media_type": media_type,
                "tool": tool,
                "imported": 0,
                "message": "紙本核減清單（PDF／影像）無法自動結構化為 18 欄，請以 CSV 匯出後上傳，或改用逐筆新增。",
                "extracted_text_preview": text[:500],
            })
        result = parse_deduction_file(path)
    except (MediaExtractError, DeductionFileError) as exc:
        current_app.logger.warning("appeal import failed: %s", exc)
        raise ApiError(import_error_message(exc))
    finally:
        if os.path.exists(path):
            os.remove(path)  # 暫存檔即時清除（PHI 最小化）

    cases = [to_appeal_case(i, rec) for i, rec in enumerate(result.records, start=1)]
    rejected = [
        {"row": r.row_number, "line": r.line_number, "reason": r.reason, "raw": list(r.raw)}
        for r in result.rejected
    ]
    if not cases:
        return jsonify({
            "status": "error",
            "media_type": "csv",
            "imported": 0,
            "rejected": len(rejected),
            "rejected_rows": rejected,
            "message": "未匯入任何案件（請檢查核減明細欄位數是否為 18 欄）。",
        }), 400

    persisted, conflicts = persist_cases(case_store(), "appeal", cases, caller_id())
    return jsonify({
        "status": "success",
        "media_type": "csv",
        "source": "csv",
        "imported": len(cases),
        "rejected": len(rejected),
        "rejected_rows": rejected,
        "case_store_persisted": persisted,
        "case_store_conflicts": conflicts,
    })
