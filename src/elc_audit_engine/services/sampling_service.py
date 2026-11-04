"""抽樣事前預審服務層（Phase 22-04）。

路由層（`api/routes/sampling.py`）只做 HTTP 請求校驗與 JSON 封裝；本模組承接預審、
匯入解析、批次讀取與案件狀態推進等業務邏輯。本模組不依賴 Flask：錯誤以
`SamplingServiceError` 表達，由路由層轉為對應的 HTTP 狀態碼。
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import Any

from config import settings
from elc_audit_engine import attachment_store, evidence_vault
from elc_audit_engine.case_store import CaseNotFoundError, IllegalTransitionError
from elc_audit_engine.comparator.soap_advice import generate_soap_advice
from elc_audit_engine.generators.sampling_xml import SamplingXmlError, build_sampling_xml
from elc_audit_engine.ingest import (
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
from elc_audit_engine.packagers import PackagerError, build_base_name, build_case_package
from elc_audit_engine.parsers import parse_soap_text
from elc_audit_engine.parsers.models import OrderRecord, SubmissionCase
from elc_audit_engine.parsers.totfa import parse_totfa_zip
from elc_audit_engine.pipeline import run_presubmission_check
from elc_audit_engine.rule_repository import get_rule
from elc_audit_engine.rule_repository.errors import RuleRepositoryError
from elc_audit_engine.sampling_closed_loop import (
    build_review,
    fallback_soap,
    resolve_soap_text,
    save_review,
)
from elc_audit_engine.sampling_sampler import sample_monthly_batch
from elc_audit_engine.services.batch_reads import read_batch
from elc_audit_engine.services.case_mapping import to_sampling_case
from elc_audit_engine.services.record_policy import degraded_reason
from elc_audit_engine.unified_review_report import (
    RuleBlock,
    build_review_case_view,
    make_thumbnail_data_uri,
)

logger = logging.getLogger(__name__)

_PREVIEW_THUMB_LIMIT = 24
_SAMPLING_REVIEW_PATH = ("parsed", "reviewing", "reviewed")


class SamplingServiceError(Exception):
    """抽樣服務層錯誤；路由層依 `status` 轉為 HTTP 回應。"""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ParsedSamplingUpload:
    """上傳檔解析結果：媒體類型、匯入結果與來源標記（csv／zip_csv／totfa_zip／ocr／paddle）。"""

    media_type: str
    result: SamplingImportResult
    source: str


def parse_sampling_upload(path: str, filename: str) -> ParsedSamplingUpload:
    """依副檔名分派解析：CSV、ZIP（TOTFA.xml 或 CSV）、PDF、影像。

    解析失敗拋 MediaExtractError／SamplingImportError，由路由層映射為 4xx。
    TOTFA 壓縮檔若含有效的 t2 院所代碼，會寫回設定檔（失敗僅記錄警告）。
    """
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
            t2_code = (totfa_res.header.get("t2") or "").strip()
            if t2_code:
                try:
                    settings.save_facility_config({"code": t2_code})
                except (OSError, ValueError) as exc:
                    logger.warning("facility config save failed: %s", exc)
            # 建立抽樣案件清單：醫療費用>1000, (醫令點數>=350 或 藥令單價>=5), 取前50筆高風險項
            records = []
            seen_cases = set()
            for c in totfa_res.cases:
                tp = 0
                try:
                    tp = int(c.raw.get("d39") or 0)
                except (ValueError, TypeError):  # 非數字者以 0 計，不中斷匯入
                    pass
                for o in c.orders:
                    pts = 0
                    try:
                        pts = int(o.points or 0)
                    except (ValueError, TypeError):  # 非數字者以 0 計
                        pass
                    price = 0.0
                    try:
                        price = float(o.unit_price or 0.0)
                    except (ValueError, TypeError):  # 非數字者以 0 計
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
    return ParsedSamplingUpload(media_type=media_type, result=result, source=source)

def facility_code() -> str:
    """院所代碼（設定檔 code）；設定不存在或損毀時回空字串並記錄警告。"""
    try:
        return settings.load_facility_config().get("code", "")
    except (OSError, ValueError) as exc:
        logger.warning("facility config unavailable: %s", exc)
        return ""

def sampling_records(store) -> tuple[list, dict]:
    """所有第 2 階抽樣案件（kind='sampling'），依 created_at 升冪，並回傳截斷揭露資訊（P1-10）。"""
    return read_batch(store, "sampling")

def stage2_view(store, record, *, with_thumbnails: bool):
    """第 2 階統一審查檢視模型（單案預覽與批次報告共用）。

    with_thumbnails=False 時略過影像縮圖（批次報告案數多，避免一次解析大量影像）。
    """
    case_id = record.case_id
    payload = dict(record.payload or {})

    id_no = (
        payload.get("record_no")
        or payload.get("id_number")
        or payload.get("id_card")
        or payload.get("patient_id")
        or (payload.get("monthly_source") or {}).get("id_card")
        or (payload.get("monthly_source") or {}).get("record_no")
        or (payload.get("monthly_source") or {}).get("d3")
    )
    visit_date = (
        payload.get("visit_date")
        or (payload.get("monthly_source") or {}).get("visit_date")
        or (payload.get("monthly_source") or {}).get("d9")
    )
    vault_key = evidence_vault.vault_key_for_case(id_no, visit_date)
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

    # 查詢該醫令規則，裝填給付規定與條文全文
    rules_list = []
    order_code = payload.get("order_code") or payload.get("target_order_code") or (payload.get("monthly_source") or {}).get("order_code")
    if order_code:
        try:
            r = get_rule(order_code)
            if r.found:
                if r.payment_text:
                    rules_list.append(RuleBlock(label="給付規定（payment_text）", text=r.payment_text, is_payment_text=True))
                if r.article_full_text:
                    rules_list.append(RuleBlock(label="條文全文（article_full_text）", text=r.article_full_text))
        except RuleRepositoryError as exc:
            # 規則庫故障僅降級為無規則文字並留下警告；其他例外（程式錯誤）照常拋出（P1-11）。
            logger.warning("stage2 view: rule lookup degraded: %s", exc)

    return build_review_case_view(
        2,
        case_id,
        payload,
        rules=tuple(rules_list),
        vault_listing=vault_listing,
        soap_template=soap_template,
        attachments=attachments,
        thumbnails=thumbnails,
    )

def advance_sampling_case(
    store, case_id: str | None, *, failed_reason: str | None, actor: str | None
) -> str | None:
    """推進抽樣案件狀態，回傳結果供回應揭露（不只寫 warning 靜默吞掉）。

    Returns:
        None（未帶 case_id）／"ok"／"failed"（已轉入 failed）／
        "skipped"（已在 reviewed 或之後，重複預審不回退狀態）／
        "not_found"／"conflict"（並行請求改動了狀態）。
    """
    if not case_id:
        return None
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
        logger.warning("sampling case_id=%s 不存在，未推進狀態", case_id)
        return "not_found"
    except IllegalTransitionError as exc:
        logger.warning("sampling case_id=%s 狀態轉換衝突：%s", case_id, exc)
        return "conflict"

def evidence_context(store, case_id: str | None) -> str:
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

def advice(oj) -> str:
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

def run_presubmission_audit(
    store,
    *,
    order_code: str,
    order_name: str | None,
    soap_text: str | None,
    record_no: str | None,
    case_id: str | None,
    visit_date,
    timeline,
    records_source: str,
    actor: str | None,
) -> dict[str, Any]:
    """事前預審核心流程：查規則庫 → LLM 判定 → 狀態流轉 → 補強建議。

    呼叫端需先解析 visit_date 與 timeline（病史來源，見 api.records）。
    判定失敗時 support_level 為 None（待判定），狀態轉為 failed，不得顯示為「裸奔」（P1-1）。
    """
    case_payload: dict | None = None
    if case_id:
        try:
            record = store.get(case_id)
            if record.kind != "sampling":
                raise SamplingServiceError(f"案件 '{case_id}' 不是抽樣預審案件", status=409)
            case_payload = dict(record.payload or {})
        except CaseNotFoundError:
            pass  # 查無案件不阻斷預審（向後相容），state_transition 會標 not_found

    # Plan 18-03：SOAP 未填時自動帶入範本（僅供參考），來源寫入審查結果
    soap_source = "case" if soap_text else "none"
    if not soap_text and case_payload is not None:
        soap_text, soap_source = resolve_soap_text(store, case_payload)

    case = SubmissionCase(record_no=record_no, orders=(OrderRecord(code=order_code),))
    soap_doc = parse_soap_text(soap_text) if soap_text else None
    if visit_date is not None:
        # 供比對器檢查規則在就醫日是否生效（B-WR-07）
        case = dataclasses.replace(case, visit_date=visit_date.isoformat())
    try:
        result = run_presubmission_check(case, soap_doc, timeline)
    except RuleRepositoryError as exc:
        # D-06/P0-2：規則庫故障不得偽裝成「查無規則」或「裸奔」。
        logger.error("rule repository failure during presubmission: %s", exc)
        raise SamplingServiceError("規則庫暫時無法查詢，請稍後再試或聯繫系統管理員", status=503)

    judgments = result.comparison.order_judgments
    if not judgments:
        raise SamplingServiceError("無有效醫令可預審", status=400)
    oj = judgments[0]

    # A-CR-09：狀態轉換放在判定完成之後（P1-1）；多步轉換單一交易。
    state_transition = advance_sampling_case(
        store,
        case_id,
        failed_reason=(
            "LLM 判定服務異常，未完成預審" if oj.support_level is None and oj.rule_found else None
        ),
        actor=actor,
    )

    # Plan 18-03：支持度狀態流轉與警示寫回案件 payload["review"]（與 run_closed_loop 共用 build_review）。
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

    # 整合 Qwen3.8-27B 智慧比對：病史摘要（就診紀錄）＋多源證據併入同一份脈絡
    history_desc = timeline.history_lines() if timeline else ""
    evidence_desc = evidence_context(store, case_id)
    patient_history = "\n".join(part for part in (history_desc, evidence_desc) if part)
    rule_desc = oj.check_item.rule_text if oj.check_item else ""
    soap_advice = generate_soap_advice(
        order_code=order_code,
        order_name=order_name or order_code,
        soap_text=soap_text or "",
        patient_history=patient_history,
        rule_text=rule_desc,
    )

    return {
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
        "reinforcement_advice": advice(oj),
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
    }


def build_sampling_case_package(payload: dict) -> tuple[bytes, dict, str]:
    """單案健保送審資料夾（Phase 21-01）：送審 XML＋佐證庫檔案，依 11 碼規則命名。

    回傳 (zip 位元組, 包內報告, 基底檔名)。需設定 NHI_STAGE1_CODE／NHI_STAGE2_CODE（未設定 503）；
    缺來源申報總檔或欄位 422；不符規格的佐證檔列於包內 MANIFEST.txt。
    """
    stage1, stage2 = settings.NHI_STAGE1_CODE, settings.NHI_STAGE2_CODE
    if not stage1 or not stage2:
        raise SamplingServiceError(
            "未設定健保檔名第一、第二階層代碼（NHI_STAGE1_CODE／NHI_STAGE2_CODE）", status=503
        )

    source = payload.get("monthly_source") if isinstance(payload.get("monthly_source"), dict) else {}
    try:
        xml_bytes = build_sampling_xml(payload)
        base_name = build_base_name(stage1, stage2, source.get("case_class"), source.get("case_seq"))
    except (SamplingXmlError, PackagerError) as exc:
        raise SamplingServiceError(str(exc), status=422)

    evidence: list[tuple[str, bytes]] = []
    id_no = (
        payload.get("record_no")
        or payload.get("id_number")
        or payload.get("id_card")
        or payload.get("patient_id")
        or (payload.get("monthly_source") or {}).get("id_card")
        or (payload.get("monthly_source") or {}).get("record_no")
        or (payload.get("monthly_source") or {}).get("d3")
    )
    visit_date = (
        payload.get("visit_date")
        or (payload.get("monthly_source") or {}).get("visit_date")
        or (payload.get("monthly_source") or {}).get("d9")
    )
    vault_key = evidence_vault.vault_key_for_case(id_no, visit_date)
    if vault_key is not None:
        for files in evidence_vault.list_vault_files(vault_key).values():
            for vault_file in files:
                with open(vault_file.path, "rb") as handle:
                    evidence.append((vault_file.filename, handle.read()))

    package, report = build_case_package(base_name=base_name, xml_bytes=xml_bytes, evidence=evidence)
    return package, report, base_name


def sample_batch_cases(
    store, batch: str, *, random_count: int, intentional_count: int, seed: int | None
) -> tuple[list[dict], list]:
    """申報批次抽樣（20 隨機＋10 立意）：回傳 (待入庫的案件 dict 清單, 抽中項目)。

    批次不存在拋 SamplingServiceError(404)。持久化由路由層負責（與案件庫交易一致）。
    """
    if store.count_by_batch(batch) == 0:
        raise SamplingServiceError("查無此批次", status=404)
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
    return cases, picked
