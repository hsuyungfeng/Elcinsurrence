"""當月申報預審 API：上傳 TOTFA.zip（匯入＋比對）、批次清單、批次報告（JSON／HTML）。

認證：全部端點皆需 X-API-Key（不列入 AUTH_EXEMPT_ENDPOINTS；新端點預設受保護）。
PHI：回應只含代碼、日期與規則原文，不含病患姓名；上傳暫存檔於處理後即刪除。
"""

from __future__ import annotations

import os
import re
import shutil
import uuid

from flask import Blueprint, Response, current_app, jsonify, request

from config import settings
from elc_audit_engine.case_store.monthly import ingest_monthly_declaration
from elc_audit_engine.monthly_audit import audit_batch, report_view
from elc_audit_engine.monthly_pregen import (
    STATUS_QUALITY_FAILED,
    STATUS_UNDETERMINED,
    load_templates,
    pregen_batch,
    pregen_template,
)
from elc_audit_engine.monthly_reasoning import attach_reasoning
from elc_audit_engine.monthly_report_html import render_batch_report_html
from elc_audit_engine.parsers.models import SubmissionParseResult
from elc_audit_engine.parsers.submission_xml import SubmissionXmlError
from elc_audit_engine.parsers.totfa import parse_totfa_zip
from elc_audit_engine.rule_repository import get_rule as _get_rule
from elc_audit_engine.rule_repository.errors import RuleRepositoryError

from ..context import caller_id, case_store
from ..errors import ApiError

bp = Blueprint("monthly", __name__)

MAX_TOTFA_UPLOAD_BYTES = 10 * 1024 * 1024
_BATCH_RE = re.compile(r"^MONTHLY-\d{6}$")
_REPORT_FORMATS = ("json", "html")
_PARSE_FAILED = "TOTFA 檔案無法解析：需為含 TOTFA.xml（Big5）的 zip，且結構須符合申報格式"


def _save_stream(stream, dest: str) -> None:
    """串流寫入暫存檔並強制大小上限；超過即刪檔並回 413。"""
    size = 0
    with open(dest, "wb") as out:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_TOTFA_UPLOAD_BYTES:
                out.close()
                os.remove(dest)
                raise ApiError("檔案超過 10MB 上限", status=413)
            out.write(chunk)


def _totals_for_upload(report: dict) -> dict:
    """上傳回應只帶總計與科別／醫師彙總；case_seq 彙總與案件明細改由報告端點取得。"""
    return {
        "totals": report["totals"],
        "by_department": report["by_department"],
        "by_doctor": report["by_doctor"],
    }


@bp.route("/api/monthly/upload", methods=["POST"])
def upload_monthly():
    """上傳 TOTFA.zip：解析 → 冪等匯入 CaseStore → 規則比對（結果寫入案件產物）。"""
    upload = request.files.get("file")
    if upload is None or not (upload.filename or "").lower().endswith(".zip"):
        raise ApiError("請以 multipart 欄位 file 上傳 TOTFA.zip")

    raw_dir = current_app.config["ELC_RAW_DIR"]
    os.makedirs(raw_dir, exist_ok=True)
    dest = os.path.join(raw_dir, f"{uuid.uuid4().hex}.zip")
    store = case_store()
    try:
        _save_stream(upload.stream, dest)
        try:
            result: SubmissionParseResult = parse_totfa_zip(dest)
            ingest = ingest_monthly_declaration(store, result, actor=caller_id())
            # 自動將申報資料中之機構代碼寫入院所檔案（User Requirement: KEY 使用上傳資料中機構代碼、存入院所檔案）
            facility_code = (result.header.get("t2") or "").strip()
            if facility_code:
                try:
                    settings.save_facility_config({"code": facility_code})
                except Exception as exc:
                    current_app.logger.warning("自動寫入院所機構代碼失敗：%s", exc)
        except SubmissionXmlError as exc:
            current_app.logger.warning("monthly upload rejected: %s", type(exc).__name__)
            raise ApiError(_PARSE_FAILED)
        audit = audit_batch(
            store,
            ingest.batch,
            rules_db_path=current_app.config.get("ELC_RULES_DB_PATH"),
            persist=True,
        )

        # 申報總檔與分析結果留存伺服機持久目錄（data/uploads/ 与 data/output/）
        upload_dir = current_app.config.get("ELC_UPLOAD_DIR") or settings.DATA_DIR
        os.makedirs(upload_dir, exist_ok=True)
        saved_zip = os.path.join(upload_dir, f"{ingest.batch}.zip")
        shutil.copy2(dest, saved_zip)

        out_dir = current_app.config.get("ELC_OUTPUT_DIR") or settings.OUTPUT_DIR
        os.makedirs(out_dir, exist_ok=True)
        report_html = render_batch_report_html(audit, templates=load_templates(store, report_view(audit)))
        saved_html = os.path.join(out_dir, f"report_{ingest.batch}.html")
        with open(saved_html, "w", encoding="utf-8") as f:
            f.write(report_html)
    finally:
        if os.path.exists(dest):
            os.remove(dest)  # 清理暫存檔（原始檔已安全備份至 saved_zip）

    fac_code = (result.header.get("t2") or "").strip()
    return jsonify({
        "status": "success",
        "batch": ingest.batch,
        "facility_code": fac_code,
        "total_cases": len(result.cases),
        "ingest": {
            "created": ingest.created,
            "skipped_existing": ingest.skipped_existing,
            "rejected": ingest.rejected,
        },
        "report": _totals_for_upload(audit.report),
    })


@bp.route("/api/monthly/batches", methods=["GET"])
def list_monthly_batches():
    """已匯入的當月申報批次及案件數。"""
    rows = case_store().list_batches()
    return jsonify([{"batch": batch, "cases": count} for batch, count in rows])


@bp.route("/api/monthly/batch/<batch_id>/report", methods=["GET"])
def monthly_batch_report(batch_id: str):
    """批次報告：`?format=json`（預設，含每案推理樹與 SOAP 清單）或 `?format=html`（視覺卡片）。"""
    if not _BATCH_RE.match(batch_id):
        raise ApiError("batch_id 格式應為 MONTHLY-YYYYMM")
    fmt = request.args.get("format", "json")
    if fmt not in _REPORT_FORMATS:
        raise ApiError("format 僅支援 json 或 html")

    store = case_store()
    if store.count_by_batch(batch_id) == 0:
        raise ApiError("查無此批次", status=404)

    audit = audit_batch(
        store,
        batch_id,
        rules_db_path=current_app.config.get("ELC_RULES_DB_PATH"),
        persist=False,
    )
    if fmt == "html":
        templates = load_templates(store, report_view(audit))
        return Response(
            render_batch_report_html(audit, templates=templates),
            content_type="text/html; charset=utf-8",
        )

    audit = report_view(audit)  # 報告納入規則（醫療總點數 > 1000、有給付規定且超過門檻）
    payload = audit.to_dict(include_rule_text=True)
    payload["cases"] = [
        attach_reasoning(case_dict, case)
        for case_dict, case in zip(payload["cases"], audit.cases)
    ]
    return jsonify(payload)


@bp.route("/api/monthly/batch/<batch_id>/email", methods=["POST"])
def email_monthly_report(batch_id: str):
    """已停用 Email 寄送端點（依資安與醫療隱私保護政策，全面停用 Email 傳輸個資與申報報告）。"""
    raise ApiError("已依資安與醫療隱私政策停用 Email 寄送功能（不使用 Email 傳輸申報報告）", status=403)


@bp.route("/api/monthly/template", methods=["POST"])
def monthly_soap_template():
    """取得單一處置／手術醫令＋主診斷的範例病歷：命中快取直接回傳，否則生成（通過品質檢核才存庫）。

    請求 JSON：{"order_code", "primary_diagnosis", "order_name"?, "force"?}。
    規則庫查詢失敗回 503（系統故障，不以空規則生成）；LLM 失敗回 503；品質未過回 422 且不存庫。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("請求主體必須為 JSON 物件")
    order_code = str(data.get("order_code") or "").strip()
    dx = str(data.get("primary_diagnosis") or "").strip()
    order_name = str(data.get("order_name") or "").strip()
    if not order_code or not dx:
        raise ApiError("order_code 與 primary_diagnosis 皆必填")
    if len(order_code) > 32 or len(dx) > 32 or len(order_name) > 200:
        raise ApiError("欄位長度超過上限")
    force = data.get("force") is True

    try:
        rule = _get_rule(order_code, db_path=current_app.config.get("ELC_RULES_DB_PATH"))
    except RuleRepositoryError:
        return jsonify({"status": "undetermined", "message": "規則庫查詢失敗（系統故障，非判定結果）"}), 503
    rule_text = (rule.payment_text or rule.article_full_text or "") if rule.found else ""
    name = order_name or (rule.name if rule.found and rule.name else order_code)

    outcome = pregen_template(
        case_store(),
        order_code=order_code,
        order_name=name,
        primary_diagnosis=dx,
        rule_text=rule_text,
        force=force,
    )
    if outcome.status == STATUS_UNDETERMINED:
        return jsonify({"status": "undetermined", "message": "LLM 服務無法連線或逾時（系統故障，非判定結果）"}), 503
    if outcome.status == STATUS_QUALITY_FAILED:
        return jsonify({"status": "quality_failed", "quality": outcome.quality,
                         "message": "生成內容未通過品質檢核，未存入範本"}), 422
    return jsonify({
        "status": outcome.status,
        "order_code": order_code,
        "primary_diagnosis": dx,
        "soap": outcome.soap,
        "quality": outcome.quality,
    })


@bp.route("/api/monthly/batch/<batch_id>/pregen", methods=["POST"])
def monthly_batch_pregen(batch_id: str):
    """批次預生成報告中處置／手術高價醫令的範例病歷（快取命中不計次數；新生成數量受 limit 限制）。"""
    if not _BATCH_RE.match(batch_id):
        raise ApiError("batch_id 格式應為 MONTHLY-YYYYMM")
    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        raise ApiError("limit 須為整數")
    if not 1 <= limit <= 50:
        raise ApiError("limit 須介於 1～50")

    store = case_store()
    if store.count_by_batch(batch_id) == 0:
        raise ApiError("查無此批次", status=404)
    audit = audit_batch(
        store,
        batch_id,
        rules_db_path=current_app.config.get("ELC_RULES_DB_PATH"),
        persist=False,
    )
    counts = pregen_batch(store, report_view(audit), limit=limit)
    return jsonify({"status": "success", "batch": batch_id, **counts})


@bp.route("/api/monthly/batches/clear", methods=["POST", "DELETE"])
def clear_all_monthly_batches():
    """清空所有當月申報批次案件 (kind='monthly')。"""
    store = case_store()
    deleted = store.delete_by_kind("monthly")
    return jsonify({
        "status": "success",
        "deleted_count": deleted,
        "message": f"已成功清空 {deleted} 筆當月申報案件",
    })


@bp.route("/api/monthly/batch/<batch_id>/clear", methods=["POST", "DELETE"])
def clear_single_monthly_batch(batch_id: str):
    """清空指定申報批次的案件。"""
    if not _BATCH_RE.match(batch_id):
        raise ApiError("batch_id 格式應為 MONTHLY-YYYYMM")
    store = case_store()
    deleted = store.delete_by_batch(batch_id)
    return jsonify({
        "status": "success",
        "batch": batch_id,
        "deleted_count": deleted,
        "message": f"已成功清空批次 {batch_id}（共 {deleted} 筆案件）",
    })
