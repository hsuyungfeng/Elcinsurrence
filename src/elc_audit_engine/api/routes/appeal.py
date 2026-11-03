"""核減事後申復 API：案件清單、申復草稿生成、核減明細匯入。"""

from __future__ import annotations

import json
import os

from flask import Blueprint, Response, current_app, jsonify, request

from elc_audit_engine import attachment_store, evidence_vault
from elc_audit_engine.appeal_linkage import (
    DEFAULT_COUNT,
    MAX_COUNT,
    appeal_xml_case,
    link_stage2_to_appeal,
)
from elc_audit_engine.sampling_closed_loop import fallback_soap
from elc_audit_engine.generators.appeal_xml import (
    TOTFA_ZIP_NAME,
    AppealBatchError,
    AppealXmlEncodingError,
    appeal_root_to_big5_bytes,
    build_batch_appeal_xml,
    wrap_totfa_zip,
)
from elc_audit_engine.case_store import CaseNotFoundError, IllegalTransitionError
from elc_audit_engine.comparator.soap_advice import generate_soap_advice
from elc_audit_engine.generators import build_appeal_draft, render_appeal_json
from elc_audit_engine.ingest import MediaExtractError, detect_media_type, extract_text
from elc_audit_engine.ingest.zip_support import inspect_zip_contents
from elc_audit_engine.parsers.deduction import DeductionFileError, parse_deduction_file
from elc_audit_engine.parsers.models import DeductionRecord
from elc_audit_engine.parsers.totfa import parse_totfa_zip
from elc_audit_engine.rule_repository import get_rule
from elc_audit_engine.rule_repository.errors import RuleRepositoryError
from elc_audit_engine.unified_review_report import (
    RuleBlock,
    build_review_case_view,
    make_thumbnail_data_uri,
    render_aggregated_review_html,
    render_unified_review_html,
)

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

    # 整合 Qwen3.8-27B 智慧比對：比對原始 SOAP 與雲端病歷/多源證據，產出 SOAP 補強與申復理由建議
    soap_advice = None
    try:
        history_desc = ""
        if timeline and timeline.events:
            history_desc = "\n".join(
                f"- [{e.date}] {e.category}: {e.summary}" for e in timeline.events[:5]
            )
        if evidence:
            ev_desc = "\n".join(f"- [證據] {e}" for e in evidence)
            history_desc = f"{history_desc}\n{ev_desc}".strip()
        soap_advice = generate_soap_advice(
            order_code=order_code,
            order_name=order_name or order_code,
            soap_text=deduction_reason or "",
            patient_history=history_desc,
            rule_text=rule_text or "",
        )
    except Exception as exc:
        current_app.logger.warning("LLM SOAP appeal advice generation failed: %s", exc)

    # W4 契約橋（D-03）：回應主體為 render_appeal_json 標準契約（單一契約）。
    payload = json.loads(render_appeal_json(draft))
    # A-CR-04：通過驗證的草稿寫回 CaseStore，供佐證包列印讀取。
    if state_transition == "ok":
        case_store().set_artifact(case_id, "appeal_draft", payload)
    payload["status"] = "success"
    payload["case_id"] = case_id or None
    payload["state_transition"] = state_transition
    payload["rule_found"] = rule.found
    payload["soap_advice"] = soap_advice
    payload["records_degraded"] = timeline is None
    payload["records_source"] = records_source
    payload["records_window_anchor"] = "visit_date" if visit_date else "today"
    payload["records_degraded_reason"] = degraded_reason(records_source, timeline is None)
    return jsonify(payload)


@bp.route("/api/appeal/cases/clear", methods=["POST", "DELETE"])
def clear_appeal_cases_endpoint():
    """清空目前所有申復案件 (kind='appeal')。"""
    store = case_store()
    deleted = store.delete_by_kind("appeal")
    return jsonify({
        "status": "success",
        "deleted_count": deleted,
        "message": f"已成功刪除 {deleted} 筆申復案件",
    })


@bp.route("/api/appeal/sample-from-stage2", methods=["POST"])
def sample_appeal_from_stage2():
    """自第 2 階抽樣案件隨機抽選 N 案（預設 5），連動建立第 3 階申復案件（Plan 20-02）。

    請求：{"count": 5, "seed": 可選整數}。回傳抽中、新建與已存在（重複）的申復案件 ID。
    """
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        raise ApiError("請求內容必須為 JSON 物件")
    count = _opt_int(data, "count")
    seed = _opt_int(data, "seed")
    count = DEFAULT_COUNT if count is None else count
    if not 1 <= count <= MAX_COUNT:
        raise ApiError(f"count 須介於 1 至 {MAX_COUNT}")

    store = case_store()
    sources = store.list_all(kind="sampling", limit=1000)
    if not sources:
        raise ApiError("尚無第 2 階抽樣案件可供連動", status=404)
    try:
        result = link_stage2_to_appeal(store, sources, count=count, seed=seed, actor=caller_id())
    except RuleRepositoryError as exc:
        current_app.logger.error("rule repository failure during stage2 linkage: %s", exc)
        raise ApiError("規則庫暫時無法查詢，請稍後再試或聯繫系統管理員", status=503)
    return jsonify({"status": "success", **result})


def _stage3_view(store, record, *, with_thumbnails: bool):
    """第 3 階統一審查/申復檢視模型（單案預覽與批次報告共用）。"""
    case_id = record.case_id
    payload = dict(record.payload or {})

    vault_key = evidence_vault.vault_key_for_case(payload.get("record_no"), payload.get("visit_date"))
    vault_listing = None
    thumbnails: dict[str, str] = {}
    if vault_key is not None:
        files_by_cat = evidence_vault.list_vault_files(vault_key)
        vault_listing = {cat: [{"filename": f.filename} for f in files] for cat, files in files_by_cat.items()}
        if with_thumbnails:
            for image in files_by_cat.get("images", [])[:24]:
                uri = make_thumbnail_data_uri(image.path)
                if uri:
                    thumbnails[image.filename] = uri
    attachments = tuple(a.filename for a in attachment_store.list_attachments(case_id))

    soap_template = None
    if not str(payload.get("soap") or "").strip():
        soap, source = fallback_soap(store, payload)
        if source.startswith("template") and soap is not None:
            soap_template = soap

    # 查詢該醫令規則，裝填給付規定與條文全文
    rules_list = []
    order_code = payload.get("order_code") or (payload.get("monthly_source") or {}).get("order_code")
    if order_code:
        try:
            r = get_rule(order_code)
            if r.found:
                if r.payment_text:
                    rules_list.append(RuleBlock(label="給付規定（payment_text）", text=r.payment_text, is_payment_text=True))
                if r.article_full_text:
                    rules_list.append(RuleBlock(label="條文全文（article_full_text）", text=r.article_full_text))
        except Exception:
            pass

    return build_review_case_view(
        3,
        case_id,
        payload,
        rules=tuple(rules_list),
        vault_listing=vault_listing,
        soap_template=soap_template,
        attachments=attachments,
        thumbnails=thumbnails,
    )


@bp.route("/api/appeal/cases/<case_id>/preview-html", methods=["GET"])
def appeal_case_preview_html(case_id: str):
    """單一申復案件的統一審查格式預覽（第 3 階；HTML）。"""
    store = case_store()
    try:
        record = store.get(case_id)
    except CaseNotFoundError:
        raise ApiError(f"找不到案件：{case_id}", status=404)
    if record.kind != "appeal":
        raise ApiError(f"案件 {case_id} 並非申復案件 (kind={record.kind})", status=400)
    view = _stage3_view(store, record, with_thumbnails=True)
    return Response(render_unified_review_html(view), content_type="text/html; charset=utf-8")


@bp.route("/api/appeal/batch-report", methods=["GET"])
def appeal_batch_report():
    """全部第 3 階申復案件的聚合預審報告。"""
    store = case_store()
    records = list(store.list_all(kind="appeal", limit=1000))
    if not records:
        raise ApiError("尚無申復案件可產生報告", status=404)
    views = [_stage3_view(store, record, with_thumbnails=False) for record in records]
    batches = sorted({str((r.payload or {}).get("batch") or "") for r in records} - {""})
    html = render_aggregated_review_html(
        views,
        title="核減事後申復批次報告",
        batch_label=", ".join(batches) or None,
    )
    return Response(html, content_type="text/html; charset=utf-8")


@bp.route("/api/appeal/cases/<case_id>/export-xml", methods=["GET"])
def export_single_appeal_xml(case_id: str):
    """單案電子申復 XML 導出（Big5 編碼，單案 TOTFA 格式）。"""
    store = case_store()
    try:
        record = store.get(case_id)
    except CaseNotFoundError:
        raise ApiError(f"找不到案件：{case_id}", status=404)
    if record.kind != "appeal":
        raise ApiError(f"案件 {case_id} 並非申復案件 (kind={record.kind})", status=400)

    payload = dict(record.payload or {})
    case_dict = appeal_xml_case(payload)
    try:
        root = build_batch_appeal_xml([case_dict])
        xml_bytes = appeal_root_to_big5_bytes(root)
    except (AppealBatchError, AppealXmlEncodingError) as exc:
        raise ApiError(str(exc), status=422)

    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", case_id)
    return Response(
        xml_bytes,
        content_type="application/xml; charset=big5",
        headers={"Content-Disposition": f'attachment; filename="appeal_{safe_id}.xml"'},
    )


@bp.route("/api/appeal/cases/<case_id>/export-json", methods=["GET"])
def export_single_appeal_json(case_id: str):
    """單案申復 JSON 導出（render_appeal_json 契約結構）。"""
    store = case_store()
    try:
        record = store.get(case_id)
    except CaseNotFoundError:
        raise ApiError(f"找不到案件：{case_id}", status=404)
    if record.kind != "appeal":
        raise ApiError(f"案件 {case_id} 並非申復案件 (kind={record.kind})", status=400)

    # 優先從 case_artifacts 獲取最近通過驗證的 appeal.json，若無則回傳 payload
    artifacts = store.get_artifacts(case_id)
    appeal_json_str = artifacts.get("appeal.json")
    if appeal_json_str:
        try:
            data = json.loads(appeal_json_str)
            return jsonify(data)
        except Exception:
            pass

    return jsonify(dict(record.payload or {}))


@bp.route("/api/appeal/export-batch-xml", methods=["GET"])
def export_appeal_batch_xml():
    """全批次電子申復 XML（Phase 21-02）：所有申復案件聚合為單一 Big5 文件（t38/t39 加總）。

    無申復案件 404；欄位缺漏、字數超限或 Big5 無法編碼 422（整批拒絕，不產生殘缺檔）。
    """
    records = list(case_store().list_all(kind="appeal", limit=1000))
    if not records:
        raise ApiError("尚無申復案件可導出", status=404)
    try:
        root = build_batch_appeal_xml([appeal_xml_case(r.payload or {}) for r in records])
        xml_bytes = appeal_root_to_big5_bytes(root)
    except (AppealBatchError, AppealXmlEncodingError) as exc:
        raise ApiError(str(exc), status=422)
    # 門診申復上傳包：TOTFA.zip 內僅含 TOTFA.xml（格式說明 §五）
    return Response(
        wrap_totfa_zip(xml_bytes),
        content_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{TOTFA_ZIP_NAME}"'},
    )


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
        if media_type == "zip":
            zip_cat, zip_items = inspect_zip_contents(path)
            if zip_cat == "totfa":
                totfa_res = parse_totfa_zip(path)
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
                                records.append(DeductionRecord(
                                    non_reimbursed_amount=pts or int(price),
                                    case_seq=c.case_seq,
                                    visit_date=c.visit_date,
                                    id_number=c.record_no,
                                    order_seq=str(o.seq) if o.seq is not None else None,
                                    order_code=o.code,
                                    deduction_reason=f"申報總檔核對預審（主診斷：{c.primary_diagnosis}）",
                                ))
                from elc_audit_engine.parsers.deduction import DeductionParseResult
                result = DeductionParseResult(records=tuple(records), rejected=())
            elif zip_cat == "csv" and zip_items:
                # 寫出解出的 csv 暫存並解析
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp_csv:
                    tmp_csv.write(zip_items[0][1])
                    tmp_csv_path = tmp_csv.name
                try:
                    result = parse_deduction_file(tmp_csv_path)
                finally:
                    if os.path.exists(tmp_csv_path):
                        os.remove(tmp_csv_path)
            else:
                raise DeductionFileError("ZIP 壓縮檔內未找到 TOTFA.xml 或有效的 CSV 檔案")
        elif media_type != "csv":
            text, tool = extract_text(path, media_type=media_type)
            return jsonify({
                "status": "partial",
                "media_type": media_type,
                "tool": tool,
                "imported": 0,
                "message": "紙本核減清單（PDF／影像）無法自動結構化為 18 欄，請以 CSV 匯出後上傳，或改用逐筆新增。",
                "extracted_text_preview": text[:500],
            })
        else:
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
