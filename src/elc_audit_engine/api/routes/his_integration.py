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
from elc_audit_engine.comparator.soap_advice import generate_soap_advice
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
