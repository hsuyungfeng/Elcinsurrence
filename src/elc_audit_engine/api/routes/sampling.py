"""抽樣事前預審 API：案件清單、預審（三方比對）、批次匯入。"""

from __future__ import annotations

import dataclasses
import os
import re
from collections import Counter
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from elc_audit_engine import attachment_store, evidence_vault
from elc_audit_engine.case_store import CaseNotFoundError, IllegalTransitionError
from elc_audit_engine.comparator.soap_advice import generate_soap_advice
from config import settings
from elc_audit_engine.generators.sampling_xml import (
    SamplingXmlError,
    build_batch_sampling_xml,
    build_sampling_xml,
)
from elc_audit_engine.packagers import PackagerError, build_base_name, build_case_package
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
from elc_audit_engine.ingest.sampling import SamplingCaseRecord, SamplingImportResult
from elc_audit_engine.ingest.zip_support import inspect_zip_contents
from elc_audit_engine.parsers import parse_soap_text
from elc_audit_engine.parsers.models import OrderRecord, SubmissionCase
from elc_audit_engine.parsers.totfa import parse_totfa_zip
from elc_audit_engine.pipeline import run_presubmission_check
from elc_audit_engine.rule_repository.errors import RuleRepositoryError
from elc_audit_engine.sampling_closed_loop import (
    build_review,
    fallback_soap,
    resolve_soap_text,
    run_closed_loop,
    save_review,
)
from elc_audit_engine.sampling_sampler import sample_monthly_batch
from elc_audit_engine.unified_review_report import (
    build_review_case_view,
    make_thumbnail_data_uri,
    render_aggregated_review_html,
    render_unified_review_html,
)

from ..cases import persist_cases, to_sampling_case
from ..context import caller_id, case_store
from ..demo_data import DEMO_SAMPLING_CASES
from ..errors import ApiError
from ..records import (
    degraded_reason,
    records_provider,
    resolve_records_source,
    resolve_visit_date,
)
from ..uploads import import_error_message, save_upload
from ..validation import MAX_SOAP_CHARS, clean_str, json_body
from ._lists import case_list_response

bp = Blueprint("sampling", __name__)

_PREVIEW_THUMB_LIMIT = 24
_EVIDENCE_MAX_LABS = 50
_EVIDENCE_MAX_CLOUD_CHARS = 5000


def _sampling_case_or_404(case_id: str):
    """取得抽樣案件；查無或非 kind='sampling' 一律 404（不洩漏其他類別案件）。"""
    try:
        record = case_store().get(case_id)
    except CaseNotFoundError:
        raise ApiError("查無此抽樣案件", status=404)
    if record.kind != "sampling":
        raise ApiError("查無此抽樣案件", status=404)
    return record


def _lab_results(raw: Any) -> list[dict[str, str]]:
    """檢驗數據清單驗證：每項需有 name 與 value；可選 unit、date；全部轉為字串。"""
    if not isinstance(raw, list):
        raise ApiError("lab_results 必須為陣列")
    if len(raw) > _EVIDENCE_MAX_LABS:
        raise ApiError(f"lab_results 最多 {_EVIDENCE_MAX_LABS} 筆")
    labs: list[dict[str, str]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ApiError(f"lab_results 第 {index} 筆必須為物件")
        name = str(item.get("name") or "").strip()
        value = str(item.get("value") if item.get("value") is not None else "").strip()
        if not name or not value:
            raise ApiError(f"lab_results 第 {index} 筆缺少 name 或 value")
        entry = {"name": name[:100], "value": value[:100]}
        for optional in ("unit", "date"):
            text = str(item.get(optional) or "").strip()
            if text:
                entry[optional] = text[:20]
        labs.append(entry)
    return labs


@bp.route("/api/sampling/cases/<case_id>/evidence", methods=["PUT"])
def update_sampling_evidence(case_id: str):
    """更新抽樣案件的檢驗數據與健保雲端跨院紀錄（覆寫，不改變案件狀態）。"""
    record = _sampling_case_or_404(case_id)
    data = json_body(request)
    labs = _lab_results(data.get("lab_results", []))
    cloud = data.get("cloud_records", "")
    if cloud is None:
        cloud = ""
    if not isinstance(cloud, str):
        raise ApiError("cloud_records 必須為字串")
    if len(cloud) > _EVIDENCE_MAX_CLOUD_CHARS:
        raise ApiError(f"cloud_records 超過 {_EVIDENCE_MAX_CLOUD_CHARS} 字")

    payload = dict(record.payload or {})
    payload["lab_results"] = labs
    payload["cloud_records"] = cloud.strip() or None
    case_store().update_payload(case_id, payload)
    return jsonify({
        "status": "success",
        "case_id": case_id,
        "lab_results": labs,
        "cloud_records": payload["cloud_records"],
    })


def _sampling_records() -> list:
    """所有第 2 階抽樣案件（kind='sampling'），依 created_at 升冪。"""
    return list(case_store().list_all(kind="sampling", limit=1000))


def _stage2_view(store, record, *, with_thumbnails: bool):
    """第 2 階統一審查檢視模型（單案預覽與批次報告共用）。

    with_thumbnails=False 時略過影像縮圖（批次報告案數多，避免一次解析大量影像）。
    """
    case_id = record.case_id
    payload = dict(record.payload or {})

    vault_key = evidence_vault.vault_key_for_case(payload.get("record_no"), payload.get("visit_date"))
    vault_listing = None
    thumbnails: dict[str, str] = {}
    if vault_key is not None:
        files_by_cat = evidence_vault.list_vault_files(vault_key)
        vault_listing = {cat: [{"filename": f.filename} for f in files] for cat, files in files_by_cat.items()}
        if with_thumbnails:
            # 影像縮圖（Phase 19-01）：上限 24 張，無法解析者以檔名佔位
            for image in files_by_cat.get("images", [])[:_PREVIEW_THUMB_LIMIT]:
                uri = make_thumbnail_data_uri(image.path)
                if uri:
                    thumbnails[image.filename] = uri
    attachments = tuple(a.filename for a in attachment_store.list_attachments(case_id))

    soap_template = None
    if not str(payload.get("soap") or "").strip():
        soap, source = fallback_soap(store, payload)
        if source.startswith("template") and soap is not None:
            soap_template = soap

    return build_review_case_view(
        2,
        case_id,
        payload,
        vault_listing=vault_listing,
        soap_template=soap_template,
        attachments=attachments,
        thumbnails=thumbnails,
    )


@bp.route("/api/sampling/batch-audit", methods=["POST"])
def batch_audit_sampling():
    """全自動批次審查（Plan 20-03）：對全部第 2 階抽樣案件執行閉環，寫回各案 payload["review"]。

    單案的 ValueError（如無有效醫令）記入 errors 並繼續；規則庫／病歷來源基礎設施故障照常穿透（P0-2）。
    """
    store = case_store()
    provider = records_provider()
    records = _sampling_records()
    results = []
    errors = []
    for record in records:
        try:
            outcome = run_closed_loop(store, record.case_id, provider=provider)
        except ValueError as exc:
            errors.append({"case_id": record.case_id, "message": str(exc)})
            continue
        results.append({
            "case_id": outcome.case_id,
            "support_state": outcome.support_state,
            "records_degraded": outcome.records_degraded,
            "soap_source": outcome.soap_source,
            "warnings": list(outcome.warnings),
        })
    by_state = dict(Counter(item["support_state"] for item in results))
    return jsonify({
        "status": "success",
        "total": len(records),
        "completed": len(results),
        "by_state": by_state,
        "results": results,
        "errors": errors,
    })


@bp.route("/api/sampling/cases/<case_id>/closed-loop", methods=["POST"])
def closed_loop_single_sampling_case(case_id: str):
    """單案事前預審閉環執行（寫回 payload['review']）。"""
    store = case_store()
    provider = records_provider()
    try:
        outcome = run_closed_loop(store, case_id, provider=provider)
    except ValueError as exc:
        raise ApiError(str(exc), status=400)
    except CaseNotFoundError:
        raise ApiError(f"找不到案件：{case_id}", status=404)
    return jsonify({
        "status": "success",
        "case_id": outcome.case_id,
        "support_state": outcome.support_state,
        "records_degraded": outcome.records_degraded,
        "soap_source": outcome.soap_source,
        "warnings": list(outcome.warnings),
    })


@bp.route("/api/sampling/export-batch-xml", methods=["GET"])
def export_sampling_batch_xml():
    """全批次健保抽審 XML（Plan 20-03）：多案件聚合為單一 Big5 文件。

    任一案件缺來源或欄位即整批拒絕（422），錯誤點名該案，不產生殘缺檔。
    """
    payloads = []
    for record in _sampling_records():
        item = dict(record.payload or {})
        item["id"] = record.case_id
        payloads.append(item)
    try:
        body = build_batch_sampling_xml(payloads)
    except SamplingXmlError as exc:
        raise ApiError(str(exc), status=422)
    return Response(
        body,
        content_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="sampling_batch.xml"'},
    )


@bp.route("/api/sampling/cases/<case_id>/export-package", methods=["GET"])
def export_sampling_case_package(case_id: str):
    """單案健保送審資料夾（Phase 21-01）：送審 XML＋佐證庫檔案，依 11 碼規則命名，一次性整包導出。

    需設定 NHI_STAGE1_CODE／NHI_STAGE2_CODE（未設定 503）；缺來源申報總檔或欄位 422；
    不符規格的佐證檔不會靜默略過，而是列於包內 MANIFEST.txt 並於回應標頭說明數量。
    """
    record = _sampling_case_or_404(case_id)
    payload = dict(record.payload or {})
    stage1, stage2 = settings.NHI_STAGE1_CODE, settings.NHI_STAGE2_CODE
    if not stage1 or not stage2:
        raise ApiError("未設定健保檔名第一、第二階層代碼（NHI_STAGE1_CODE／NHI_STAGE2_CODE）", status=503)

    source = payload.get("monthly_source") if isinstance(payload.get("monthly_source"), dict) else {}
    try:
        xml_bytes = build_sampling_xml(payload)
        base_name = build_base_name(stage1, stage2, source.get("case_class"), source.get("case_seq"))
    except (SamplingXmlError, PackagerError) as exc:
        raise ApiError(str(exc), status=422)

    evidence: list[tuple[str, bytes]] = []
    vault_key = evidence_vault.vault_key_for_case(payload.get("record_no"), payload.get("visit_date"))
    if vault_key is not None:
        for files in evidence_vault.list_vault_files(vault_key).values():
            for vault_file in files:
                with open(vault_file.path, "rb") as handle:
                    evidence.append((vault_file.filename, handle.read()))

    package, report = build_case_package(base_name=base_name, xml_bytes=xml_bytes, evidence=evidence)
    return Response(
        package,
        content_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{base_name}.zip"',
            "X-Package-Accepted": str(len(report["accepted"])),
            "X-Package-Rejected": str(len(report["rejected"])),
        },
    )


@bp.route("/api/sampling/batch-report", methods=["GET"])
def sampling_batch_report():
    """全部第 2 階案件的聚合預審報告（Plan 20-01）：每案一個可收合的 case-item。"""
    store = case_store()
    records = _sampling_records()
    views = [_stage2_view(store, record, with_thumbnails=False) for record in records]
    batches = sorted({str((r.payload or {}).get("batch") or "") for r in records} - {""})
    html = render_aggregated_review_html(
        views,
        title="抽樣預審批次報告",
        batch_label=", ".join(batches) or None,
    )
    return Response(html, content_type="text/html; charset=utf-8")


@bp.route("/api/sampling/cases/<case_id>/preview-html", methods=["GET"])
def sampling_case_preview_html(case_id: str):
    """單一抽樣案件的統一審查格式預覽（第 2 階；HTML）；需 API Key（含病歷與個資）。

    身分證字號即 record_no；佐證庫依身分證＋就醫日推導（Phase 17-03）；
    SOAP 缺漏時以範本降級並標示須醫師審核（Plan 18-03）。
    """
    record = _sampling_case_or_404(case_id)
    view = _stage2_view(case_store(), record, with_thumbnails=True)
    return Response(render_unified_review_html(view), content_type="text/html; charset=utf-8")


@bp.route("/api/sampling/cases/<case_id>/export-xml", methods=["GET"])
def export_sampling_case_xml(case_id: str):
    """導出單一抽樣案件的健保抽審 XML（Big5 附件下載）。

    缺來源申報總檔或必要欄位（d1/d2/d3、pdata）時回 422，不產生殘缺檔（見 sampling_xml）。
    """
    record = _sampling_case_or_404(case_id)
    try:
        body = build_sampling_xml(dict(record.payload or {}))
    except SamplingXmlError as exc:
        raise ApiError(str(exc), status=422)
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", case_id)
    response = Response(body, content_type="application/xml")
    response.headers["Content-Disposition"] = f'attachment; filename="sampling_{safe_id}.xml"'
    return response


_SAMPLE_BATCH_RE = re.compile(r"^MONTHLY-\d{6}$")
_SAMPLE_MAX_COUNT = 200


def _count_field(data: dict, key: str, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(f"欄位 {key} 必須為整數")
    if not 0 <= value <= _SAMPLE_MAX_COUNT:
        raise ApiError(f"欄位 {key} 須介於 0～{_SAMPLE_MAX_COUNT}")
    return value


@bp.route("/api/sampling/cases/clear", methods=["POST", "DELETE"])
def clear_sampling_cases_endpoint():
    """清空目前所有抽樣案件 (kind='sampling')。"""
    store = case_store()
    deleted = store.delete_by_kind("sampling")
    return jsonify({
        "status": "success",
        "deleted_count": deleted,
        "message": f"已成功刪除 {deleted} 筆抽樣案件",
    })


@bp.route("/api/sampling/sample-batch", methods=["POST"])
def sample_monthly_batch_endpoint():
    """申報批次抽樣：20 隨機＋10 立意（前三最高點數醫令合計）入庫為 kind='sampling'。

    請求：{"batch": "MONTHLY-202307", "random_count": 20, "intentional_count": 10, "seed": 可選}。
    """
    data = json_body(request)
    batch = clean_str(data, "batch", required=True)
    if not _SAMPLE_BATCH_RE.match(batch):
        raise ApiError("batch 格式應為 MONTHLY-YYYYMM")
    random_count = _count_field(data, "random_count", 20)
    intentional_count = _count_field(data, "intentional_count", 10)
    seed = data.get("seed")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise ApiError("seed 必須為整數")

    store = case_store()
    if store.count_by_batch(batch) == 0:
        raise ApiError("查無此批次", status=404)

    picked = sample_monthly_batch(
        store, batch, random_count=random_count, intentional_count=intentional_count, seed=seed
    )
    cases = [to_sampling_case(idx, item.record) for idx, item in enumerate(picked, start=1)]
    for case, item in zip(cases, picked):
        case["sample_type"] = item.sample_type
        case["batch"] = batch
        case["monthly_case_id"] = item.monthly_case_id
        case["top3_points_total"] = str(item.top3_points_total)
        case["target_order_code"] = item.target_order_code
        # 帶入來源申報總檔案件（含 d1/d2/d3 與 orders 原始欄位），供健保抽審 XML 導出。
        case["monthly_source"] = item.source_payload

    persisted, conflicts = persist_cases(case_store(), "sampling", cases, caller_id())
    return jsonify({
        "status": "success",
        "batch": batch,
        "sampled": len(cases),
        "random": sum(1 for item in picked if item.sample_type == "random"),
        "intentional": sum(1 for item in picked if item.sample_type == "intentional"),
        "case_store_persisted": persisted,
        "case_store_conflicts": conflicts,
        "cases": cases,
    })

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


def _evidence_context(store, case_id: str | None) -> str:
    """抽樣案件的檢驗數據與雲端病歷轉為 LLM 可讀的病史脈絡行；無資料回空字串。"""
    if not case_id:
        return ""
    try:
        payload = store.get(case_id).payload or {}
    except CaseNotFoundError:
        return ""
    lines = []
    for lab in payload.get("lab_results") or []:
        unit = f" {lab['unit']}" if lab.get("unit") else ""
        when = f" ({lab['date']})" if lab.get("date") else ""
        lines.append(f"- [檢驗]{when} {lab.get('name', '')}: {lab.get('value', '')}{unit}")
    if payload.get("cloud_records"):
        lines.append(f"- [健保雲端跨院病歷] {payload['cloud_records']}")
    return "\n".join(lines)


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

    case_payload: dict | None = None
    if case_id:
        try:
            record = store.get(case_id)
            if record.kind != "sampling":
                raise ApiError(f"案件 '{case_id}' 不是抽樣預審案件", status=409)
            case_payload = dict(record.payload or {})
        except CaseNotFoundError:
            pass  # 查無案件不阻斷預審（向後相容），state_transition 會標 not_found

    # Plan 18-03：SOAP 未填時自動帶入範本（僅供參考），來源寫入審查結果
    soap_source = "case" if soap_text else "none"
    if not soap_text and case_payload is not None:
        soap_text, soap_source = resolve_soap_text(store, case_payload)

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

    # Plan 18-03：支持度狀態流轉（待判定／充分／薄弱／裸奔）與警示寫回案件 payload["review"]。
    # 與 run_closed_loop 共用 build_review，確保 audit 與閉環結果一致。
    review = None
    if case_payload is not None:
        review = build_review(
            judgment_level=oj.support_level,
            rule_found=oj.rule_found,
            records_degraded=result.comparison.records_degraded,
            records_source=records_source,
            soap_source=soap_source,
        )
        save_review(store, case_id, review)

    # 整合 Qwen3.8-27B 智慧比對：比對原始 SOAP 與雲端病歷/病史時間軸，產出結構化建議供醫師審批
    soap_advice = None
    try:
        history_desc = ""
        if timeline and timeline.events:
            history_desc = "\n".join(
                f"- [{e.date}] {e.category}: {e.summary}" for e in timeline.events[:5]
            )
        # 多源證據（檢驗數據、健保雲端跨院病歷）併入同一份病史脈絡，供 LLM 比對缺口
        evidence_desc = _evidence_context(store, case_id)
        patient_history = "\n".join(part for part in (history_desc, evidence_desc) if part)
        rule_desc = oj.check_item.rule_text if oj.check_item else ""
        soap_advice = generate_soap_advice(
            order_code=order_code,
            order_name=order_name or order_code,
            soap_text=soap_text or "",
            patient_history=patient_history,
            rule_text=rule_desc,
        )
    except Exception as exc:
        current_app.logger.warning("LLM SOAP advice generation failed: %s", exc)

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
        "soap_advice": soap_advice,
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
        # 閉環（Plan 18-03）：狀態流轉、警示與本次判定實際使用的 SOAP 來源／文字
        "support_state": review["support_state"] if review else None,
        "closed_loop_warnings": review["warnings"] if review else [],
        "soap_source": soap_source,
        "soap_text_used": soap_text or "",
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
        elif media_type == "zip":
            # 支援 .zip 壓縮包：若內含 TOTFA.xml 則依使用者條件挑選高風險案件（小於50筆）；若為 CSV 則解析 CSV
            zip_cat, zip_items = inspect_zip_contents(path)
            if zip_cat == "totfa":
                totfa_res = parse_totfa_zip(path)
                # 建立抽樣案件清單：醫療費用>1000, (醫令點數>=350 或 藥令單價>=5), 取前50筆高風險項
                records = []
                seen_cases = set()
                for c in totfa_res.cases:
                    tp = 0
                    try:
                        tp = int(c.raw.get("d39") or 0)
                    except:
                        pass
                    for o in c.orders:
                        pts = 0
                        try:
                            pts = int(o.points or 0)
                        except:
                            pass
                        price = 0.0
                        try:
                            price = float(o.unit_price or 0.0)
                        except:
                            pass
                        if (tp > 1000 and (pts >= 350 or price >= 5.0)) or len(records) < 50:
                            if c.case_seq not in seen_cases and len(records) < 50:
                                seen_cases.add(c.case_seq)
                                records.append(SamplingCaseRecord(
                                    order_code=o.code,
                                    case_seq=c.case_seq,
                                    record_no=c.record_no,
                                    patient_name=c.patient_name,
                                    order_name=o.code,
                                    visit_date=c.visit_date,
                                    clinic=c.clinic,
                                    soap_text="",
                                    source="totfa_zip",
                                ))
                result = SamplingImportResult(records=tuple(records), rejected=())
                source = "totfa_zip"
            elif zip_cat == "csv" and zip_items:
                # 取第一個 CSV 進行解析
                _, csv_bytes = zip_items[0]
                result = parse_sampling_csv(csv_bytes)
                source = "zip_csv"
            else:
                raise SamplingImportError("ZIP 壓縮檔內未找到 TOTFA.xml 或有效的 CSV 檔案")
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
