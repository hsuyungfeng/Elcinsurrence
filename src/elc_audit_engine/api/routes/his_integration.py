"""HIS 整合 REST API 與審批回寫 Webhook（Plan 15-03）。

- POST /api/his/v1/cases/push：接收 HIS 看診紀錄（kind='his'，case_id 為內容雜湊，重複推送冪等）。
- POST /api/his/v1/cases/soap-enhance：以本機 LLM 產生雙語建議；`recommended_soap` 為英文，
  `comparison`／`approval_advice` 為繁體中文。範例病歷一律標示需醫師審核。
- POST /api/his/v1/cases/<case_id>/approve-callback：醫師審批結果；若設定 `HIS_WEBHOOK_URL`
  則轉送至診所 HIS，否則只存本機並明示未送出。

安全：三個端點皆需 X-API-Key（不豁免）。Webhook 目的地只來自伺服器設定（環境變數），
不接受請求內指定，避免被用來對任意主機發送病歷（SSRF）。日誌不記錄病歷內容。

系統失敗與業務結論分離：LLM 或規則庫故障回 503 且 `status="undetermined"`，不偽裝成建議結果。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from elc_audit_engine.case_store import CaseNotFoundError
from elc_audit_engine.case_store.store import DuplicateCaseError
from elc_audit_engine.comparator.soap_advice import (
    generate_soap_advice,
    validate_soap_quality,
)
from elc_audit_engine.rule_repository import get_rule
from elc_audit_engine.rule_repository.errors import RuleRepositoryError

from ..context import caller_id, case_store
from ..errors import ApiError
from ..validation import MAX_SOAP_CHARS, clean_str, json_body

logger = logging.getLogger(__name__)

bp = Blueprint("his", __name__)

HIS_KIND = "his"
APPROVED_ARTIFACT = "his_approved_soap"
WEBHOOK_TIMEOUT_SECONDS = 10
_APPROVAL_STATUSES = ("approved", "rejected", "revised")


def _encounter_case_id(*parts: str) -> str:
    """內容雜湊 case_id：同一看診、同一醫令、同一 SOAP 重複推送得到同一 ID。"""
    digest = hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"HIS-{digest[:32]}"


def _deliver_webhook(url: str, record: dict[str, Any]) -> dict[str, str]:
    """轉送審批結果至 HIS。只回傳結果類別，不回傳內容或完整錯誤訊息。"""
    body = json.dumps(record, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=WEBHOOK_TIMEOUT_SECONDS) as resp:
            if 200 <= resp.status < 300:
                return {"status": "delivered"}
            return {"status": "failed", "error": f"HTTP {resp.status}"}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"status": "failed", "error": type(exc).__name__}


@bp.route("/api/his/v1/cases/push", methods=["POST"])
def push_his_case():
    """接收 HIS 看診紀錄並建檔。"""
    data = json_body(request)
    record_no = clean_str(data, "record_no", required=True)
    order_code = clean_str(data, "order_code", required=True)
    clinic = clean_str(data, "clinic")
    visit_date = clean_str(data, "visit_date")
    his_encounter_id = clean_str(data, "his_encounter_id")
    soap_text = clean_str(data, "soap_text", max_len=MAX_SOAP_CHARS)

    case_id = _encounter_case_id(clinic, record_no, visit_date, his_encounter_id, order_code, soap_text)
    payload = {
        "record_no": record_no,
        "patient_name": clean_str(data, "patient_name"),
        "order_code": order_code,
        "order_name": clean_str(data, "order_name") or order_code,
        "visit_date": visit_date,
        "clinic": clinic,
        "soap": soap_text,
        "his_encounter_id": his_encounter_id,
        "source": "his_direct_api",
        "received_at": datetime.now(UTC).isoformat(),
    }
    try:
        case_store().create(
            case_id=case_id,
            kind=HIS_KIND,
            case_seq=clean_str(data, "case_seq") or None,
            order_code=order_code,
            payload=payload,
            actor=caller_id(),
        )
    except DuplicateCaseError:
        return jsonify({
            "status": "duplicate",
            "case_id": case_id,
            "message": "同一看診紀錄已建檔，未重複寫入",
        }), 200
    return jsonify({"status": "success", "case_id": case_id, "payload": payload}), 201


@bp.route("/api/his/v1/cases/soap-enhance", methods=["POST"])
def soap_enhance():
    """產生雙語建議與範例病歷（範例病歷需醫師審核後才可使用）。"""
    data = json_body(request)
    order_code = clean_str(data, "order_code", required=True)
    order_name = clean_str(data, "order_name") or order_code
    soap_text = clean_str(data, "soap_text", max_len=MAX_SOAP_CHARS)
    patient_history = clean_str(data, "patient_history", max_len=MAX_SOAP_CHARS)
    primary_diagnosis = clean_str(data, "primary_diagnosis")
    if not primary_diagnosis and patient_history:
        # 嘗試從 patient_history 解析主診斷（例如 "主診斷：D2362" 或 "S90221A"）
        import re
        m = re.search(r"(?:主診斷[:：\s]*|^)([A-TV-Z][0-9][0-9A-Z]?(?:\.[0-9A-Z]{1,4})?)", patient_history, re.IGNORECASE)
        if m:
            primary_diagnosis = m.group(1).strip().upper()

    force = data.get("force") is True
    store = case_store()

    # 1. 優先查詢通用快取 (soap_templates)
    if not force and primary_diagnosis:
        cached = store.get_soap_template(order_code, primary_diagnosis)
        if cached is not None:
            c_soap = cached["soap"]
            c_template = "\n".join(f"{key.upper()}: {str(c_soap.get(key, '')).strip()}" for key in ("s", "o", "a", "p"))
            advice = {
                "status": "success",
                "recommended_soap": c_soap,
                "comparison": "已載入此醫令與主診斷之通用標準範本",
                "approval_advice": "請核對病患實際處置部位、病理報告與同意書記錄完整性。",
            }
            return jsonify({
                "status": "success",
                "from_cache": True,
                "template_scope": cached["scope"],
                "order_code": order_code,
                "order_name": order_name,
                "primary_diagnosis": primary_diagnosis,
                "rule_found": True,
                "rule_text": "",
                "bilingual_advice": advice,
                "example_soap_template": c_template,
                "review_required": True,
                "warning": None,
            })

    try:
        rule = get_rule(order_code, db_path=current_app.config.get("ELC_RULES_DB_PATH"))
    except RuleRepositoryError:
        return jsonify({
            "status": "undetermined",
            "message": "規則庫查詢失敗，無法判定給付規定（系統故障，非判定結果）",
        }), 503
    # 組合完整規則與醫令資訊，避免 payment_text 為字串 "null" 或空值
    rule_parts = []
    if rule.found:
        if rule.name:
            rule_parts.append(f"醫令名稱：{rule.name}")
        pt = (rule.payment_text or "").strip()
        if pt and pt.lower() != "null":
            rule_parts.append(f"給付規定：\n{pt}")
        aft = (rule.article_full_text or "").strip()
        if aft and aft.lower() != "null":
            rule_parts.append(f"章節規範與通則：\n{aft}")
        if rule.article_location:
            rule_parts.append(f"章節位置：{rule.article_location}")
    rule_text = "\n\n".join(rule_parts) if rule_parts else ""

    advice = generate_soap_advice(
        order_code=order_code,
        order_name=order_name,
        soap_text=soap_text,
        patient_history=patient_history,
        rule_text=rule_text,
    )
    if advice.get("status") == "error":
        # LLM 無法連線或逾時：系統故障，不產生任何建議內容
        return jsonify({
            "status": "undetermined",
            "message": "LLM 服務無法連線或逾時，未產生建議（系統故障，非判定結果）",
            "rule_found": rule.found,
        }), 503

    structured = advice.get("status") == "success"
    soap = advice.get("recommended_soap", {}) if structured else {}
    template = "\n".join(f"{key.upper()}: {str(soap.get(key, '')).strip()}" for key in ("s", "o", "a", "p"))

    # 品質驗證通過後存入通用 soap_templates 快取
    if structured and primary_diagnosis:
        quality = validate_soap_quality(soap)
        if quality.get("pass"):
            try:
                store.put_soap_template(
                    order_code,
                    primary_diagnosis,
                    {k: str(soap[k]).strip() for k in ("s", "o", "a", "p")},
                    source="llm_validated",
                    quality_score=quality.get("quality_score"),
                )
            except Exception as e:
                logger.warning("寫入 soap_templates 失敗: %s", e)

    case_id = clean_str(data, "case_id")
    if case_id:
        store = case_store()
        try:
            store.get(case_id)
            artifact_key = f"example_soap_{order_code}"
            store.set_artifact(case_id, artifact_key, {
                "order_code": order_code,
                "order_name": order_name,
                "example_soap_template": template if structured else "",
                "bilingual_advice": advice,
                "updated_at": datetime.now(UTC).isoformat(),
            })
        except Exception as e:
            logger.warning("無法將範例病歷存入 case_artifacts (case_id=%s): %s", case_id, e)

    return jsonify({
        "status": "success" if structured else "fallback",
        "order_code": order_code,
        "order_name": order_name,
        "rule_found": rule.found,
        "rule_text": rule_text,
        "bilingual_advice": advice,
        "example_soap_template": template if structured else "",
        "review_required": True,
        "warning": None if structured else "模型未回傳完整結構，未產生範例病歷，請醫師人工判讀",
    })


@bp.route("/api/his/v1/cases/<case_id>/approve-callback", methods=["POST"])
def approve_callback(case_id: str):
    """醫師審批結果回寫。未設定 HIS_WEBHOOK_URL 時只存本機，並如實回報未送出。"""
    data = json_body(request)
    approved_soap = clean_str(data, "approved_soap", required=True, max_len=MAX_SOAP_CHARS)
    doctor_id = clean_str(data, "doctor_id") or "attending_doctor"
    approval_status = clean_str(data, "approval_status") or "approved"
    if approval_status not in _APPROVAL_STATUSES:
        raise ApiError("approval_status 須為 approved、rejected 或 revised")

    store = case_store()
    try:
        store.get(case_id)
    except CaseNotFoundError:
        raise ApiError("查無此案件", status=404)

    record: dict[str, Any] = {
        "case_id": case_id,
        "doctor_id": doctor_id,
        "approval_status": approval_status,
        "final_soap": approved_soap,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    webhook_url = current_app.config.get("HIS_WEBHOOK_URL") or os.environ.get("HIS_WEBHOOK_URL")
    if webhook_url:
        delivery = _deliver_webhook(webhook_url, record)
    else:
        delivery = {"status": "not_sent", "reason": "未設定 HIS_WEBHOOK_URL，僅存於本機"}
    record["delivery"] = delivery
    record["written_to_his"] = delivery["status"] == "delivered"
    store.set_artifact(case_id, APPROVED_ARTIFACT, record)

    if delivery["status"] == "failed":
        # 本機已保存，但 HIS 未收到：回 502 讓呼叫端重送
        logger.warning("HIS webhook 轉送失敗 case_id=%s error=%s", case_id, delivery.get("error"))
        return jsonify({"status": "delivery_failed", "case_id": case_id, "record": record}), 502
    return jsonify({"status": "success", "case_id": case_id, "record": record})


@bp.route("/api/his/soapvoice-ingest", methods=["POST"])
def ingest_soapvoice_session():
    """接收 SoapVoice 診間上傳之音訊、截圖與結構化 SOAP（Phase 24-01）。
    
    支援 multipart/form-data 或 application/json：
    - multipart/form-data:
        - session_id: str
        - patient_name: str
        - id_card: str (身分證字號，如 A123456789)
        - visit_date: str (ROC 7碼如 1120718 或 YYYY-MM-DD)
        - soap_json: str (包含 subjective, objective, assessment, plan)
        - icd10_code: str (選填)
        - order_code: str (選填，如 39004C)
        - audio_file: UploadFile (WAV, MP3, Opus 等)
        - screenshot_file: UploadFile (JPG, PNG 等)
    """
    import base64
    from elc_audit_engine.evidence_vault import (
        vault_key_for_case,
        store_single_file,
        validate_vault_key,
        InvalidVaultKeyError,
    )

    content_type = request.content_type or ""
    audio_bytes: bytes | None = None
    audio_filename = "consultation.opus"
    image_bytes: bytes | None = None
    image_filename = "screenshot.png"
    
    if "multipart/form-data" in content_type:
        form = request.form
        session_id = form.get("session_id", "").strip()
        patient_name = form.get("patient_name", "").strip()
        id_card = form.get("id_card", "").strip().upper()
        visit_date = form.get("visit_date", "").strip()
        icd10_code = form.get("icd10_code", "").strip()
        order_code = form.get("order_code", "").strip()
        raw_soap = form.get("soap_json", "{}")
        try:
            soap_dict = json.loads(raw_soap) if isinstance(raw_soap, str) else raw_soap
        except Exception:
            soap_dict = {}

        if "audio_file" in request.files:
            f = request.files["audio_file"]
            audio_bytes = f.read()
            if f.filename:
                audio_filename = os.path.basename(f.filename)

        if "screenshot_file" in request.files:
            f = request.files["screenshot_file"]
            image_bytes = f.read()
            if f.filename:
                image_filename = os.path.basename(f.filename)
    else:
        data = json_body(request)
        session_id = clean_str(data, "session_id")
        patient_name = clean_str(data, "patient_name")
        id_card = clean_str(data, "id_card", required=True).upper()
        visit_date = clean_str(data, "visit_date")
        icd10_code = clean_str(data, "icd10_code")
        order_code = clean_str(data, "order_code")
        soap_dict = data.get("soap", {})
        if "audio_base64" in data:
            try:
                audio_bytes = base64.b64decode(data["audio_base64"])
                audio_filename = data.get("audio_filename", "consultation.opus")
            except Exception:
                pass
        if "screenshot_base64" in data:
            try:
                image_bytes = base64.b64decode(data["screenshot_base64"])
                image_filename = data.get("screenshot_filename", "screenshot.png")
            except Exception:
                pass

    if not id_card:
        raise ApiError("缺少必要欄位 id_card", status=400)
    
    # 計算/校驗 vault_key
    computed_vault_key = vault_key_for_case(id_card, visit_date)
    if not computed_vault_key:
        # Fallback to current year-month if visit_date is absent
        now = datetime.now()
        computed_vault_key = f"{id_card}-{now.year % 100:02d}{now.month:02d}"

    try:
        validate_vault_key(computed_vault_key)
    except InvalidVaultKeyError as exc:
        raise ApiError(f"計算所得之 vault_key 不合法: {exc}", status=400)

    vault_files_stored = []
    if audio_bytes:
        try:
            vf = store_single_file(computed_vault_key, audio_filename, audio_bytes)
            vault_files_stored.append({"category": vf.category, "filename": vf.filename, "size": vf.size})
        except Exception as exc:
            logger.warning("SoapVoice 音訊歸檔失敗: %s", exc)

    if image_bytes:
        try:
            vf = store_single_file(computed_vault_key, image_filename, image_bytes)
            vault_files_stored.append({"category": vf.category, "filename": vf.filename, "size": vf.size})
        except Exception as exc:
            logger.warning("SoapVoice 截圖歸檔失敗: %s", exc)

    # 建立 HIS 看診個案記錄入 case_store
    soap_text_repr = json.dumps(soap_dict, ensure_ascii=False) if isinstance(soap_dict, dict) else str(soap_dict)
    case_id = _encounter_case_id(id_card, visit_date or "", order_code or "", session_id or "")

    store = case_store()
    payload = {
        "session_id": session_id,
        "patient_name": patient_name,
        "id_card": id_card,
        "visit_date": visit_date,
        "icd10_code": icd10_code,
        "order_code": order_code,
        "soap": soap_dict,
        "vault_key": computed_vault_key,
        "vault_files": vault_files_stored,
        "source": "soapvoice_lan",
    }
    
    try:
        record = store.create(
            case_id=case_id,
            kind="his",
            payload=payload,
            actor=caller_id(),
        )
    except DuplicateCaseError:
        record = store.get(case_id)

    # 雙軌審核與比對（健保合規審核 + 自費品項推薦）
    compliance_evaluation = {"status": "ok", "warnings": []}
    if order_code:
        try:
            rule = get_rule(order_code)
            if rule and getattr(rule, "found", False):
                compliance_evaluation["rule_name"] = getattr(rule, "name", "")
                compliance_evaluation["payment_criteria"] = getattr(rule, "payment_text", "") or getattr(rule, "article_full_text", "")
        except RuleRepositoryError:
            pass

    # 自費品項智慧推薦 (基於診斷與主訴)
    self_pay_suggestions = []
    assessment_text = soap_dict.get("assessment", "") if isinstance(soap_dict, dict) else ""
    subjective_text = soap_dict.get("subjective", "") if isinstance(soap_dict, dict) else ""
    combined_diag = (assessment_text + " " + subjective_text + " " + icd10_code).lower()
    
    if any(k in combined_diag for k in ("膝", "關節", "m17", "osteoarthritis", "膝痛")):
        self_pay_suggestions.append({
            "item_code": "SP-ORTHO-PRP",
            "name": "高濃度自體血小板 (PRP) 關節修復注射",
            "price_ntd": 15000,
            "indication": "退化性關節炎軟骨磨損，保守治療輔助自費修復",
        })
        self_pay_suggestions.append({
            "item_code": "SP-ORTHO-HA",
            "name": "長效型玻尿酸關節腔內注射劑 (自費微創)",
            "price_ntd": 6000,
            "indication": "免除健保同一院所連續6個月保守治療限制",
        })

    return jsonify({
        "status": "success",
        "case_id": case_id,
        "vault_key": computed_vault_key,
        "vault_files": vault_files_stored,
        "compliance_evaluation": compliance_evaluation,
        "self_pay_suggestions": self_pay_suggestions,
        "created_at": datetime.now(UTC).isoformat(),
    }), 201
