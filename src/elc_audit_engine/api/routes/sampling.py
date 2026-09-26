"""抽樣事前預審 API：案件清單、預審（三方比對）、批次匯入。"""

from __future__ import annotations

import dataclasses
import os

from flask import Blueprint, current_app, jsonify, request

from elc_audit_engine.case_store import CaseNotFoundError, IllegalTransitionError
from elc_audit_engine.ingest import (
    MediaExtractError,
    SamplingImportError,
    detect_media_type,
    extract_text,
    parse_image_tables,
    parse_pdf_tables,
    parse_sampling_csv,
    parse_sampling_ocr_text,
)
from elc_audit_engine.parsers import parse_soap_text
from elc_audit_engine.parsers.models import OrderRecord, SubmissionCase
from elc_audit_engine.pipeline import run_presubmission_check
from elc_audit_engine.rule_repository.errors import RuleRepositoryError

from ..cases import persist_cases, to_sampling_case
from ..context import caller_id, case_store
from ..demo_data import DEMO_SAMPLING_CASES
from ..errors import ApiError
from ..records import degraded_reason, records_provider, resolve_records_source, resolve_visit_date
from ..uploads import import_error_message, save_upload
from ..validation import MAX_SOAP_CHARS, clean_str, json_body
from ._lists import case_list_response

bp = Blueprint("sampling", __name__)

_SAMPLING_REVIEW_PATH = ("parsed", "reviewing", "reviewed")


@bp.route("/api/sampling/cases", methods=["GET"])
def get_sampling_cases():
    """抽樣預審案件清單（CaseStore 為單一真實來源；未匯入時回示範資料）。"""
    return case_list_response("sampling", DEMO_SAMPLING_CASES)


def advance_sampling_case(case_id: str, *, failed_reason: str | None) -> str | None:
    """推進抽樣案件狀態，回傳結果供回應揭露（不只寫 warning 靜默吞掉）。

    Returns:
        None（未帶 case_id）／"ok"／"failed"（已轉入 failed）／
        "skipped"（已在 reviewed 或之後，重複預審不回退狀態）／
        "not_found"／"conflict"（並行請求改動了狀態）。
    """
    if not case_id:
        return None
    store = case_store()
    actor = caller_id()
    try:
        current = store.get(case_id).state
        if failed_reason:
            store.transition(case_id, "failed", reason=failed_reason, actor=actor)
            return "failed"
        if current in ("imported", "failed"):
            steps = _SAMPLING_REVIEW_PATH
        elif current in _SAMPLING_REVIEW_PATH:
            steps = _SAMPLING_REVIEW_PATH[_SAMPLING_REVIEW_PATH.index(current) + 1:]
        else:
            steps = ()
        if not steps:
            return "skipped"
        store.advance(case_id, steps, actor=actor)
        return "ok"
    except CaseNotFoundError:
        current_app.logger.warning("sampling case_id=%s 不存在，未推進狀態", case_id)
        return "not_found"
    except IllegalTransitionError as exc:
        current_app.logger.warning("sampling case_id=%s 狀態轉換衝突：%s", case_id, exc)
        return "conflict"


def _advice(oj) -> str:
    if not oj.rule_found:
        return "查無此醫令的規則依據，建議人工查核後再送件。"
    if oj.support_level is None:
        return "系統未能完成判定（判定服務異常），請人工複核後再送件。"
    if oj.narratives:
        return "\n".join(f"- {n.text}" for n in oj.narratives)
    if oj.support_level == "充分":
        return "病歷記載足以支撐本醫令，可逕行送出抽審。"
    if oj.narrative_error:
        # 薄弱／裸奔但補強建議生成失敗：不得說成「足以支撐」
        return "病歷記載不足，但補強建議生成失敗（判定服務異常），請人工補強後再送件。"
    return "病歷記載不足以支撐本醫令，請人工補強後再送件。"


@bp.route("/api/sampling/audit", methods=["POST"])
def audit_sampling_case():
    """事前預審支持度評估與病歷補強建議（接 run_presubmission_check）。

    查規則庫 → LLM 逐檢核項判定 → 三級分類 → 缺口候選補強。判定失敗時回傳
    support_level=null（待判定），呼叫端不得顯示為「裸奔」（P1-1）。
    """
    data = json_body(request)
    order_code = clean_str(data, "order_code", required=True)
    order_name = clean_str(data, "order_name")
    soap_text = clean_str(data, "soap_text", max_len=MAX_SOAP_CHARS)
    record_no = clean_str(data, "record_no")
    case_id = clean_str(data, "case_id")
    store = case_store()

    if case_id:
        try:
            if store.get(case_id).kind != "sampling":
                raise ApiError(f"案件 '{case_id}' 不是抽樣預審案件", status=409)
        except CaseNotFoundError:
            pass  # 查無案件不阻斷預審（向後相容），state_transition 會標 not_found

    case = SubmissionCase(record_no=record_no, orders=(OrderRecord(code=order_code),))
    soap_doc = parse_soap_text(soap_text) if soap_text else None

    try:
        # RecordProviderError（infra 故障）不在此捕捉，穿透至統一 500（P0-2）；
        # PatientRecordsNotFound 由 build_timeline 內捕為 degraded（C5）。
        visit_date = resolve_visit_date(store, data, case_id)
        timeline, records_source = resolve_records_source(records_provider(), record_no, visit_date)
        if visit_date is not None:
            # 供比對器檢查規則在就醫日是否生效（B-WR-07）
            case = dataclasses.replace(case, visit_date=visit_date.isoformat())
        result = run_presubmission_check(case, soap_doc, timeline)
    except RuleRepositoryError as exc:
        # D-06/P0-2：規則庫故障不得偽裝成「查無規則」或「裸奔」。
        current_app.logger.error("rule repository failure during presubmission: %s", exc)
        raise ApiError("規則庫暫時無法查詢，請稍後再試或聯繫系統管理員", status=503)

    judgments = result.comparison.order_judgments
    if not judgments:
        raise ApiError("無有效醫令可預審")
    oj = judgments[0]

    # A-CR-09：狀態轉換放在判定完成之後——判定服務異常轉 failed，不得記成
    # 「已完成預審」（P1-1）；多步轉換單一交易。
    state_transition = advance_sampling_case(
        case_id,
        failed_reason=(
            "LLM 判定服務異常，未完成預審" if oj.support_level is None and oj.rule_found else None
        ),
    )

    return jsonify({
        "status": "success",
        "case_id": case_id or None,
        "state_transition": state_transition,
        "order_code": order_code,
        "order_name": order_name,
        # support_level=null 代表「待判定」，前端須與「裸奔」分開呈現（P1-1）。
        "support_level": oj.support_level,
        "rule_found": oj.rule_found,
        "undetermined": oj.support_level is None and oj.rule_found,
        "verdict": oj.judgment.verdict if oj.judgment else None,
        "quote": oj.judgment.quote if oj.judgment else "",
        "rule_location": oj.check_item.rule_location if oj.check_item else None,
        "reinforcement_advice": _advice(oj),
        "candidates": [
            {"text": n.text, "rule_location": n.rule_location, "prompt_only": n.prompt_only}
            for n in oj.narratives
        ],
        "records_degraded": result.comparison.records_degraded,
        "records_source": records_source,
        "records_window_anchor": "visit_date" if visit_date else "today",
        "records_degraded_reason": degraded_reason(
            records_source, result.comparison.records_degraded
        ),
    })


@bp.route("/api/sampling/import", methods=["POST"])
def import_sampling_cases():
    """批次匯入抽樣清單：CSV（digital）／PDF／JPEG 影像（paper→OCR）。

    PDF／影像經本機系統工具（D2 不出本機）提取文字後以 OCR 行解析——僅結構化
    醫令代碼＋名稱，其餘欄位留空供人工補齊（OCR 猜欄位比留空更危險）。
    """
    file = request.files.get("file")
    if file is None or not (file.filename or "").strip():
        raise ApiError("缺少上傳檔案（multipart 欄位名 file）")
    path, filename = save_upload(file, current_app.config["ELC_RAW_DIR"])

    try:
        media_type = detect_media_type(filename)
        if media_type == "csv":
            with open(path, "rb") as f:
                result = parse_sampling_csv(f.read())
            source = "csv"
        elif media_type == "pdf":
            # 優先 pdftotext；掃描型 PDF（無文字層）→ 再試 PP-StructureV3 表格結構化
            text, tool = extract_text(path, media_type=media_type)
            result = parse_sampling_ocr_text(text)
            source = "ocr"
            if tool != "pdftotext":
                t_result = parse_pdf_tables(path)
                if t_result is not None:
                    result, source = t_result, "paddle"
        else:
            t_result = parse_image_tables(path)
            if t_result is not None:
                result, source = t_result, "paddle"
            else:
                text, _tool = extract_text(path, media_type=media_type)
                result = parse_sampling_ocr_text(text)
                source = "ocr"
    except (MediaExtractError, SamplingImportError) as exc:
        current_app.logger.warning("sampling import failed: %s", exc)
        raise ApiError(import_error_message(exc))
    finally:
        os.remove(path)  # 暫存檔即時清除（PHI 最小化）

    cases = [to_sampling_case(i, rec) for i, rec in enumerate(result.records, start=1)]
    rejected = [
        {"row": r.row_number, "reason": r.reason, "raw": list(r.raw)} for r in result.rejected
    ]
    if not cases:
        return jsonify({
            "status": "error",
            "media_type": media_type,
            "imported": 0,
            "rejected": len(rejected),
            "rejected_rows": rejected,
            "message": (
                "未匯入任何案件：找不到可識別的醫令代碼（OCR 品質不足，請改以 CSV 匯出後上傳）。"
                if source == "ocr"
                else "未匯入任何案件（請檢查 CSV 欄位契約：需含「醫令代碼」）。"
            ),
        }), 400

    persisted, conflicts = persist_cases(case_store(), "sampling", cases, caller_id())
    return jsonify({
        "status": "success",
        "media_type": media_type,
        "source": source,
        "imported": len(cases),
        "rejected": len(rejected),
        "rejected_rows": rejected,
        "case_store_persisted": persisted,
        "case_store_conflicts": conflicts,
    })
