"""當月申報預審 API：上傳 申報壓縮檔（匯入＋比對）、批次清單、批次報告（JSON／HTML）。

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
from elc_audit_engine.monthly_package import (
    FacilityProfileError,
    build_batch_package,
    build_gap_check,
    profile_status,
)
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
from elc_audit_engine.parsers.totfa import MONTHLY_BATCH_PATTERN, parse_totfa_zip
from elc_audit_engine.rule_repository import get_rule as _get_rule
from elc_audit_engine.rule_repository.errors import RuleRepositoryError

from ..context import caller_id, case_store
from ..errors import ApiError

bp = Blueprint("monthly", __name__)

MAX_TOTFA_UPLOAD_BYTES = 10 * 1024 * 1024
_BATCH_RE = re.compile(rf"^{MONTHLY_BATCH_PATTERN}$")
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
    """上傳 申報壓縮檔：解析 → 冪等匯入 CaseStore → 規則比對（結果寫入案件產物）。"""
    upload = request.files.get("file")
    if upload is None or not (upload.filename or "").lower().endswith(".zip"):
        raise ApiError("請以 multipart 欄位 file 上傳 申報壓縮檔")

    raw_dir = current_app.config["ELC_RAW_DIR"]
    os.makedirs(raw_dir, exist_ok=True)
    dest = os.path.join(raw_dir, f"{uuid.uuid4().hex}.zip")
    store = case_store()
    try:
        _save_stream(upload.stream, dest)
        try:
            result: SubmissionParseResult = parse_totfa_zip(dest)
            ingest = ingest_monthly_declaration(store, result, actor=caller_id())
            # Phase 29：不覆寫本院院所設定。院所尚未設定時才以 zip 的機構代碼初始化；
            # 機構代碼與本院不同（新機構 zip）則只標示 foreign_facility，本院設定保持不變。
            facility_code = (result.header.get("t2") or "").strip()
            foreign_facility = False
            if facility_code:
                try:
                    current_code = str(settings.load_facility_config().get("code") or "").strip()
                except (FileNotFoundError, ValueError):
                    current_code = ""
                if not current_code:
                    try:
                        settings.save_facility_config({"code": facility_code})
                    except Exception as exc:
                        current_app.logger.warning("初始化院所機構代碼失敗：%s", exc)
                elif current_code != facility_code:
                    foreign_facility = True
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
        "foreign_facility": foreign_facility,
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


@bp.route("/api/monthly/batch/<batch_id>/package", methods=["GET"])
def monthly_batch_package(batch_id: str):
    """下載到本機（ZIP）：僅針對「無 SOAP、只上傳申報檔」的案件，提供範例病歷。

    `?generate=N`（0～50，預設 20）：快取缺少的範本時，最多由本機 LLM 生成 N 筆（通過品質檢核才存庫）；
    其餘仍缺者在文件中標示「尚未預生成」。院所資料未完整或未確認 → 412。
    """
    try:
        generate_limit = int(request.args.get("generate", "20"))
    except ValueError:
        raise ApiError("generate 須為整數")
    if not 0 <= generate_limit <= 50:
        raise ApiError("generate 須介於 0～50")

    if not _BATCH_RE.match(batch_id):
        raise ApiError("batch_id 格式應為 MONTHLY-YYYYMM 或 MONTHLY-YYYYMM-機構代碼")
    store = case_store()
    if store.count_by_batch(batch_id) == 0:
        raise ApiError("查無此批次", status=404)

    try:
        facility = settings.load_facility_config()
    except (FileNotFoundError, ValueError):
        facility = {}
    status = profile_status(facility)
    if not status.ready:
        return jsonify({
            "status": "error",
            "code": "facility_profile_required",
            "missing": list(status.missing),
            "confirmed": status.confirmed,
            "message": "請先填寫並確認院所資料（診所表單），之後即可直接下載",
        }), 412

    try:
        body = build_batch_package(
            store,
            batch_id,
            facility=facility,
            rules_db_path=current_app.config.get("ELC_RULES_DB_PATH"),
            generate_limit=generate_limit,
        )
    except FacilityProfileError as exc:  # 理論上已於上方檢查，保留防禦
        return jsonify({"status": "error", "code": "facility_profile_required", "missing": exc.missing,
                         "confirmed": exc.confirmed, "message": str(exc)}), 412
    filename = f"monthly_examples_{batch_id}.zip"
    return Response(
        body,
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.route("/api/monthly/batch/<batch_id>/gap-check", methods=["GET"])
def monthly_batch_gap_check(batch_id: str):
    """SOAP 缺項比對：有 SOAP 的案件與標準範本（soap_templates）比對，列出缺少的描述（advisory，只讀）。"""
    if not _BATCH_RE.match(batch_id):
        raise ApiError("batch_id 格式應為 MONTHLY-YYYYMM 或 MONTHLY-YYYYMM-機構代碼")
    store = case_store()
    if store.count_by_batch(batch_id) == 0:
        raise ApiError("查無此批次", status=404)
    return jsonify(build_gap_check(store, batch_id, rules_db_path=current_app.config.get("ELC_RULES_DB_PATH")))


def _roc_today() -> str:
    """今日民國 7 碼（YYYMMDD），例：2026-11-09 → 1151109。"""
    from datetime import date

    today = date.today()
    return f"{today.year - 1911:03d}{today.month:02d}{today.day:02d}"


def _case_images(case_id: str) -> list[bytes]:
    """以 case_id 讀取附件中的影像原始位元組（僅 image/*，不回傳其他檔案）。"""
    from elc_audit_engine.attachment_store import list_attachments

    out: list[bytes] = []
    for rec in list_attachments(case_id):
        if not str(rec.mime_type or "").startswith("image/"):
            continue
        try:
            with open(rec.file_path, "rb") as fh:
                out.append(fh.read())
        except OSError:
            continue
    return out


@bp.route("/api/monthly/batch/<batch_id>/emr-bundle", methods=["GET"])
def monthly_batch_emr_bundle(batch_id: str):
    """EMR 審查包：每案 XML（健保核算，Big5）＋ HTML（審查，影像內嵌），打包為 ZIP 上傳用。

    query：`tier1`（第一階層代碼，2 碼，預設 11）、`roc`（民國 7 碼，預設今日）。
    任一案件失敗 → 422 並列出案件與原因（不產生殘缺檔）。目前單次僅支援一個 ZIP；超過 450MB 需分批（409）。
    """
    from elc_audit_engine.monthly_package import build_emr_bundle

    if not _BATCH_RE.match(batch_id):
        raise ApiError("batch_id 格式應為 MONTHLY-YYYYMM 或 MONTHLY-YYYYMM-機構代碼")
    tier1 = request.args.get("tier1", "11")
    roc = request.args.get("roc") or _roc_today()
    store = case_store()
    if store.count_by_batch(batch_id) == 0:
        raise ApiError("查無此批次", status=404)
    try:
        facility_code = str(settings.load_facility_config().get("code") or "").strip()
    except (FileNotFoundError, ValueError):
        raise ApiError("院所設定缺少醫事機構代碼，無法產生 ZIP 檔名", status=412)

    from elc_audit_engine.generators.emr_review_bundle import BundleError

    try:
        zips, failures = build_emr_bundle(
            store, batch_id, facility_code=facility_code, roc_date=roc,
            tier1=tier1, images_for_case=_case_images,
            rules_db_path=current_app.config.get("ELC_RULES_DB_PATH"),
        )
    except BundleError as exc:
        raise ApiError(str(exc), status=422)
    if failures:
        return jsonify({"status": "error", "code": "emr_bundle_incomplete",
                        "message": f"{len(failures)} 筆案件無法組成合規檔案，未產生 ZIP",
                        "failures": failures}), 422
    if len(zips) != 1:
        return jsonify({"status": "error", "code": "multiple_packages",
                        "message": f"需切成 {len(zips)} 個 ZIP（超過 450MB），目前請分批下載",
                        "packages": [name for name, _ in zips]}), 409
    name, body = zips[0]
    return Response(body, mimetype="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
