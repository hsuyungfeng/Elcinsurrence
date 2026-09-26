"""列印 API：核減明細原格式 PDF（Phase 13）、申復佐證包 PDF（Phase 14）。"""

from __future__ import annotations

import dataclasses
import os
import uuid

from flask import Blueprint, current_app, jsonify, request

from config import settings
from elc_audit_engine import attachment_store
from elc_audit_engine.case_store import CaseNotFoundError
from elc_audit_engine.generators import deduction_print, evidence_packet
from elc_audit_engine.safe_paths import safe_filename

from ..context import case_store
from ..errors import ApiError
from ..validation import clean_str, json_body
from .misc import output_url

bp = Blueprint("printing", __name__)

MAX_PRINT_RECORDS = 500

DEDUCTION_PRINT_BASE_ODT = os.path.join(
    settings.PROJECT_ROOT,
    "officialdocument",
    "電子申復文件格式",
    "RCPI2012R01_核減明細表_print_base.odt",
)


@bp.route("/api/deduction/print", methods=["POST"])
def generate_deduction_print():
    """生成核減明細原格式 PDF（Phase 13-03）。"""
    data = json_body(request)
    case_id = clean_str(data, "case_id")
    payload_records = data.get("records")

    records: list[dict] = []
    if payload_records and isinstance(payload_records, list):
        # A-WR-04：限制筆數與元素型別（非 dict 會 AttributeError；過多列長時間佔用 soffice）
        if len(payload_records) > MAX_PRINT_RECORDS or not all(
            isinstance(r, dict) for r in payload_records
        ):
            raise ApiError(f"records 必須為物件陣列，且不超過 {MAX_PRINT_RECORDS} 筆")
        records = payload_records
    elif case_id:
        try:
            case = case_store().get(case_id)
        except CaseNotFoundError:
            raise ApiError(f"找不到案件 '{case_id}'", status=404)
        if case.payload:
            records = [case.payload]
    else:
        raise ApiError("必須提供 records 陣列或 case_id")

    if not records:
        raise ApiError("無有效核減資料可供列印")

    stem = safe_filename(case_id or uuid.uuid4().hex[:8], "file_stem")
    try:
        pdf_path, warnings = deduction_print.write_deduction_print(
            settings.OUTPUT_DIR,
            stem,
            records,
            settings.load_facility_config(),
            template_odt_path=DEDUCTION_PRINT_BASE_ODT,
        )
    except Exception:
        # A-WR-02：soffice stderr、暫存路徑、模板 hash 只進日誌，不回給呼叫端
        current_app.logger.exception("deduction print failed")
        raise ApiError("產生 PDF 失敗，請聯繫系統管理員", status=500)

    return jsonify({"status": "success", "pdf_url": output_url(pdf_path), "warnings": warnings})


@bp.route("/api/appeal/evidence-packet/print", methods=["POST"])
def generate_evidence_packet_print():
    """生成佐證包完整 PDF（Phase 14）。"""
    data = json_body(request)
    safe_case = safe_filename(clean_str(data, "case_id", required=True), "case_id")
    store = case_store()

    try:
        case = store.get(safe_case)
    except CaseNotFoundError:
        raise ApiError(f"找不到案件 '{safe_case}'", status=404)
    if not case.payload:
        raise ApiError("案件 payload 為空")

    # A-CR-04：申復理由段取自已保存的草稿；尚未生成就明說，不印空白段。
    draft = store.get_artifact(safe_case, "appeal_draft")
    if draft is None:
        raise ApiError("本案尚未生成（或未通過驗證的）申復草稿，請先呼叫 /api/appeal/generate", status=409)
    tracking = {"entries": [dataclasses.asdict(t) for t in store.history(safe_case)]}

    # A-CR-03：附件以 case_id 為鍵（流水號跨月重複，會混入他人影像）。
    attachments = [
        {
            "id": a.id,
            "filename": a.filename,
            "file_path": a.file_path,
            "mime_type": a.mime_type,
            "order_seq": a.order_seq,
            "order_code": a.order_code,
        }
        for a in attachment_store.list_attachments(case.case_id)
    ]
    legacy_warnings = []
    if (
        case.case_seq
        and case.case_seq != case.case_id
        and attachment_store.list_attachments(case.case_seq)
    ):
        legacy_warnings.append(
            f"發現以流水號 '{case.case_seq}' 存放的舊版附件，因無法確認屬於本案病患而未併入；"
            "請確認後以 case_id 重新上傳"
        )

    try:
        pdf_path, warnings = evidence_packet.write_evidence_packet(
            settings.OUTPUT_DIR,
            {**case.payload, **draft},
            settings.load_facility_config(),
            tracking=tracking,
            # 病史未於此端點查詢：傳 None 讓佐證包標示「未查詢」，而非「無就醫紀錄」。
            timeline=None,
            attachments=attachments,
            file_stem=safe_case,
        )
    except Exception:
        current_app.logger.exception("evidence packet print failed")
        raise ApiError("產生 PDF 失敗，請聯繫系統管理員", status=500)

    return jsonify({
        "status": "success",
        "pdf_url": output_url(pdf_path),
        "warnings": legacy_warnings + list(warnings),
    })
