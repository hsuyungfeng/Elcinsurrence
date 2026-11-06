"""抽樣事前預審 API：案件清單、預審（三方比對）、批次匯入。"""

from __future__ import annotations

import os
import re
from collections import Counter
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from elc_audit_engine.case_store import CaseNotFoundError
from elc_audit_engine.parsers.totfa import MONTHLY_BATCH_PATTERN
from elc_audit_engine.generators.sampling_xml import (
    SamplingXmlError,
    build_batch_sampling_xml,
    build_sampling_xml,
)
from elc_audit_engine.ingest import (
    MediaExtractError,
    SamplingImportError,
)
from elc_audit_engine.monthly_patient_service import (
    add_sampling_case_by_patient,
    import_monthly_to_sampling,
)
from elc_audit_engine.sampling_closed_loop import (
    run_closed_loop,
)
from elc_audit_engine.services.sampling_service import (
    SamplingServiceError,
    build_sampling_case_package,
    facility_code,
    parse_sampling_upload,
    run_presubmission_audit,
    sample_batch_cases,
    sampling_records,
)
from elc_audit_engine.services.sampling_service import (
    stage2_view as _stage2_view,
)
from elc_audit_engine.unified_review_report import (
    render_aggregated_review_html,
    render_unified_review_html,
)

from ..batch_limits import refuse_if_truncated
from ..cases import persist_cases, to_sampling_case
from ..context import caller_id, case_store
from ..demo_data import DEMO_SAMPLING_CASES
from ..errors import ApiError
from ..records import (
    records_provider,
    resolve_records_source,
    resolve_visit_date,
)
from ..uploads import import_error_message, save_upload
from ..validation import MAX_SOAP_CHARS, clean_str, json_body
from ._lists import case_list_response

bp = Blueprint("sampling", __name__)


def _sampling_records():
    """第 2 階抽樣案件（依 created_at 升冪）與截斷揭露資訊；業務邏輯見服務層。"""
    return sampling_records(case_store())

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


@bp.route("/api/sampling/cases/<case_id>/soap", methods=["PUT", "POST"])
def update_sampling_soap(case_id: str):
    """更新抽樣案件的 SOAP 病歷文字（持久化儲存至資料庫）。"""
    data = json_body(request)
    soap_text = clean_str(data, "soap", max_len=MAX_SOAP_CHARS)
    if soap_text is None:
        soap_text = clean_str(data, "soap_text", max_len=MAX_SOAP_CHARS) or ""
    store = case_store()
    try:
        record = _sampling_case_or_404(case_id)
        payload = dict(record.payload or {})
        payload["soap"] = soap_text
        payload["soap_text"] = soap_text
        store.update_payload(case_id, payload)
    except Exception:
        # demo 案件或記憶體案件容錯
        for demo in DEMO_SAMPLING_CASES:
            if demo["id"] == case_id:
                demo["soap"] = soap_text
                break
    return jsonify({
        "status": "success",
        "case_id": case_id,
        "soap": soap_text,
        "message": "SOAP 病歷已成功寫入資料庫",
    })


@bp.route("/api/sampling/batch-audit", methods=["POST"])
def batch_audit_sampling():
    """全自動批次審查（Plan 20-03）：對全部第 2 階抽樣案件執行閉環，寫回各案 payload["review"]。

    單案的 ValueError（如無有效醫令）記入 errors 並繼續；規則庫／病歷來源基礎設施故障照常穿透（P0-2）。
    """
    store = case_store()
    provider = records_provider()
    records, meta = _sampling_records()
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
        **meta,
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
    records, meta = _sampling_records()
    refuse_if_truncated(meta, what="第 2 階抽樣案件")
    payloads = []
    for record in records:
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
    """單案健保送審資料夾（Phase 21-01）：送審 XML＋佐證庫檔案，一次性整包導出（服務層組裝）。"""
    record = _sampling_case_or_404(case_id)
    try:
        package, report, base_name = build_sampling_case_package(dict(record.payload or {}))
    except SamplingServiceError as exc:
        raise ApiError(str(exc), status=exc.status)
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
    records, meta = _sampling_records()
    refuse_if_truncated(meta, what="第 2 階抽樣案件")
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


_SAMPLE_BATCH_RE = re.compile(rf"^{MONTHLY_BATCH_PATTERN}$")
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
    try:
        cases, picked = sample_batch_cases(
            store, batch, random_count=random_count, intentional_count=intentional_count, seed=seed
        )
    except SamplingServiceError as exc:
        raise ApiError(str(exc), status=exc.status)
    persisted, conflicts = persist_cases(store, "sampling", cases, caller_id())
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


@bp.route("/api/sampling/import-from-monthly", methods=["POST"])
def import_sampling_from_monthly():
    """自當月申報批次一鍵匯入抽樣清單（免重複填寫或重複上傳）。"""
    data = request.get_json(silent=True) or {}
    batch = data.get("batch")
    limit = data.get("limit", 30)
    store = case_store()
    res = import_monthly_to_sampling(
        store,
        batch_id=batch,
        limit=int(limit) if str(limit).isdigit() else 30,
        actor=caller_id(),
    )
    if res.get("status") == "error":
        raise ApiError(res.get("message", "匯入失敗"), status=400)
    return jsonify(res)


@bp.route("/api/sampling/cases/add-by-patient", methods=["POST"])
def add_sampling_by_patient():
    """依病患身分證字號／出生年月日／姓名自當月申報檢索並鍵入加入抽審清單。"""
    data = request.get_json(silent=True) or {}
    id_card = str(data.get("id_card") or "").strip()
    birth_date = str(data.get("birth_date") or "").strip()
    patient_name = str(data.get("patient_name") or "").strip()
    batch = str(data.get("batch") or "").strip() or None

    if not id_card and not birth_date and not patient_name:
        raise ApiError("身分證字號、出生年月日與姓名至少需提供一項進行查詢", status=400)

    store = case_store()
    res = add_sampling_case_by_patient(
        store,
        id_card=id_card,
        birth_date=birth_date,
        patient_name=patient_name,
        batch_id=batch,
        actor=caller_id(),
    )
    return jsonify(res)


@bp.route("/api/sampling/cases", methods=["GET"])
def get_sampling_cases():
    """抽樣預審案件清單（CaseStore 為單一真實來源；未匯入時回示範資料）。"""
    return case_list_response("sampling", DEMO_SAMPLING_CASES)


@bp.route("/api/sampling/audit", methods=["POST"])
def audit_sampling_case():
    """事前預審支持度評估與病歷補強建議（服務層：run_presubmission_audit）。

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
    try:
        # RecordProviderError（infra 故障）不捕捉，穿透至統一 500（P0-2）。
        visit_date = resolve_visit_date(store, data, case_id)
        timeline, records_source = resolve_records_source(records_provider(), record_no, visit_date)
        payload = run_presubmission_audit(
            store,
            order_code=order_code,
            order_name=order_name,
            soap_text=soap_text,
            record_no=record_no,
            case_id=case_id,
            visit_date=visit_date,
            timeline=timeline,
            records_source=records_source,
            actor=caller_id(),
        )
    except SamplingServiceError as exc:
        raise ApiError(str(exc), status=exc.status)
    return jsonify(payload)


@bp.route("/api/sampling/import", methods=["POST"])
def import_sampling_cases():
    """批次匯入抽樣清單：CSV（digital）／PDF／JPEG 影像（paper→OCR）。

    解析邏輯見服務層 parse_sampling_upload；本函式只負責上傳暫存、錯誤映射與案件入庫。
    PDF／影像僅結構化醫令代碼＋名稱，其餘欄位留空供人工補齊（OCR 猜欄位比留空更危險）。
    """
    file = request.files.get("file")
    if file is None or not (file.filename or "").strip():
        raise ApiError("缺少上傳檔案（multipart 欄位名 file）")
    path, filename = save_upload(file, current_app.config["ELC_RAW_DIR"])
    try:
        parsed = parse_sampling_upload(path, filename)
    except (MediaExtractError, SamplingImportError) as exc:
        current_app.logger.warning("sampling import failed: %s", exc)
        raise ApiError(import_error_message(exc))
    finally:
        os.remove(path)  # 暫存檔即時清除（PHI 最小化）

    media_type, result, source = parsed.media_type, parsed.result, parsed.source
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
        "facility_code": facility_code(),
        "imported": len(cases),
        "rejected": len(rejected),
        "rejected_rows": rejected,
        "case_store_persisted": persisted,
        "case_store_conflicts": conflicts,
    })
