"""當月申報 (TOTFA) 與本機每日門診語音 SOAP 自動比對關聯引擎。

比對核心邏輯：
1. TOTFA.zip 僅有代碼、診斷與點數，缺乏門診 SOAP 病歷本文。
2. 本機伺服器平時記錄每日門診看診之語音 SOAP（以機構代碼、年月份、身分證號/病歷號、就醫日期為鍵）。
3. 本模組在申報檔匯入或批次處理時，主動以多源三層策略進行關聯檢索，將 SOAP 與佐證檔案寫入案件 payload。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from elc_audit_engine.case_store.store import CaseStore
from elc_audit_engine.monthly_patient_service import normalize_date_variants
from elc_audit_engine.evidence_vault import list_vault_files, vault_key_for_case

logger = logging.getLogger(__name__)


def format_soap_to_text(soap_obj: Any) -> str:
    """將結構化 SOAP 物件（dict 或字串）標準化為純文字表現形式。"""
    if not soap_obj:
        return ""
    if isinstance(soap_obj, str):
        return soap_obj.strip()
    if isinstance(soap_obj, dict):
        s = soap_obj.get("s") or soap_obj.get("subjective") or ""
        o = soap_obj.get("o") or soap_obj.get("objective") or ""
        a = soap_obj.get("a") or soap_obj.get("assessment") or ""
        p = soap_obj.get("p") or soap_obj.get("plan") or ""
        parts = []
        if s:
            parts.append(f"[S] {s.strip()}")
        if o:
            parts.append(f"[O] {o.strip()}")
        if a:
            parts.append(f"[A] {a.strip()}")
        if p:
            parts.append(f"[P] {p.strip()}")
        return "\n".join(parts) if parts else ""
    return str(soap_obj).strip()


def _flatten_vault_files(vault_key: str) -> list[dict[str, Any]]:
    """將 list_vault_files 回傳之分類字典展平為檔案清單。"""
    result = []
    try:
        grouped = list_vault_files(vault_key)
        for cat, items in grouped.items():
            for it in items:
                result.append({
                    "vault_key": it.vault_key,
                    "category": it.category,
                    "filename": it.filename,
                    "size": it.size,
                    "path": it.path,
                })
    except Exception:
        pass
    return result


def reconcile_case_soap(
    store: CaseStore | None,
    case_payload: dict,
    *,
    facility_code: str | None = None,
) -> dict[str, Any]:
    """比對單一申報案件對應之日常門診語音 SOAP 與證據金庫檔案。

    Args:
        store: 案件存儲庫 (CaseStore)，用於搜尋已入庫的 kind='his' 紀錄。
        case_payload: 案件資訊 dict（需包含身分證號/病歷號與就醫日期）。
        facility_code: 醫事機構代碼（選填）。

    Returns:
        包含 found (bool), soap (dict|str), soap_text (str), vault_key (str), vault_files (list) 之比對結果。
    """
    raw = case_payload.get("raw") or {}
    id_card = (
        case_payload.get("id_card")
        or case_payload.get("record_no")
        or raw.get("d3")
        or ""
    )
    id_card_clean = re.sub(r"[^\w]", "", str(id_card)).strip().upper()

    visit_date = str(case_payload.get("visit_date") or raw.get("d9") or "").strip()
    patient_name = str(case_payload.get("patient_name") or raw.get("d49") or "").strip()

    if not id_card_clean or not visit_date:
        return {
            "found": False,
            "soap": "",
            "soap_text": "",
            "vault_key": None,
            "vault_files": [],
            "source": "missing_identifier",
        }

    date_variants = normalize_date_variants(visit_date)
    computed_vault_key = vault_key_for_case(id_card_clean, visit_date)

    # ─────────────────────────────────────────────────────────────────
    # 第 1 層檢索：搜尋 CaseStore 中 kind="his" 之診間匯入紀錄
    # ─────────────────────────────────────────────────────────────────
    if store is not None:
        try:
            his_records = store.list_all(kind="his", limit=1000)
            for rec in his_records:
                p = rec.payload or {}
                rec_id = re.sub(r"[^\w]", "", str(p.get("id_card") or p.get("record_no") or "")).strip().upper()
                rec_date = str(p.get("visit_date") or "").strip()
                rec_date_variants = normalize_date_variants(rec_date)
                if rec_id == id_card_clean and (date_variants.intersection(rec_date_variants)):
                    found_soap = p.get("soap") or p.get("soap_text") or ""
                    if found_soap:
                        v_key = p.get("vault_key") or computed_vault_key
                        v_files = p.get("vault_files") or []
                        if not v_files and v_key:
                            v_files = _flatten_vault_files(v_key)
                        return {
                            "found": True,
                            "soap": found_soap,
                            "soap_text": format_soap_to_text(found_soap),
                            "vault_key": v_key,
                            "vault_files": v_files,
                            "source": "casestore_his",
                        }
        except Exception as exc:
            logger.debug("CaseStore HIS 檢索略過: %s", exc)

    # ─────────────────────────────────────────────────────────────────
    # 第 2 層檢索：搜尋診所本機 PATIENT_DB（診間每日看診資料庫）
    # ─────────────────────────────────────────────────────────────────
    try:
        from elc_audit_engine.api.routes.his_integration import PATIENT_DB

        matched_pdata = None
        if id_card_clean in PATIENT_DB:
            matched_pdata = PATIENT_DB[id_card_clean]
        else:
            # 依姓名輔助比對
            for _, pdata in PATIENT_DB.items():
                if patient_name and pdata.get("patient_name") == patient_name:
                    matched_pdata = pdata
                    break

        if matched_pdata:
            encounters = matched_pdata.get("encounters") or []
            for enc in encounters:
                enc_date = str(enc.get("visit_date") or "").strip()
                enc_variants = normalize_date_variants(enc_date)
                if date_variants.intersection(enc_variants):
                    enc_soap = enc.get("soap") or {}
                    enc_key = enc.get("vault_key") or computed_vault_key
                    enc_files = enc.get("vault_files") or enc.get("files") or []
                    if not enc_files and enc_key:
                        enc_files = _flatten_vault_files(enc_key)
                    return {
                        "found": True,
                        "soap": enc_soap,
                        "soap_text": format_soap_to_text(enc_soap),
                        "vault_key": enc_key,
                        "vault_files": enc_files,
                        "source": "patient_db_local",
                    }
    except Exception as exc:
        logger.debug("PATIENT_DB 檢索略過: %s", exc)

    # ─────────────────────────────────────────────────────────────────
    # 第 3 層檢索：搜尋 evidence_vault 佐證金庫目錄
    # ─────────────────────────────────────────────────────────────────
    if computed_vault_key:
        v_files = _flatten_vault_files(computed_vault_key)
        if v_files:
            return {
                "found": True,
                "soap": "",
                "soap_text": "",
                "vault_key": computed_vault_key,
                "vault_files": v_files,
                "source": "evidence_vault_only",
            }

    return {
        "found": False,
        "soap": "",
        "soap_text": "",
        "vault_key": computed_vault_key,
        "vault_files": [],
        "source": "unmatched",
    }


def reconcile_monthly_batch(
    store: CaseStore,
    batch_id: str,
    *,
    facility_code: str | None = None,
) -> dict[str, Any]:
    """批次比對並將日常語音 SOAP 補強寫入整批當月申報案件（更新 CaseStore payload）。"""
    records = store.list_by_batch(batch_id, limit=5000)
    matched_count = 0
    updated_count = 0

    for rec in records:
        payload = dict(rec.payload or {})
        # 若已有完整 SOAP 則不重複覆寫
        if payload.get("soap") and payload.get("soap_text"):
            matched_count += 1
            continue

        result = reconcile_case_soap(store, payload, facility_code=facility_code)
        if result["found"]:
            matched_count += 1
            if result.get("soap") or result.get("vault_key"):
                payload["soap"] = result["soap"]
                payload["soap_text"] = result["soap_text"]
                payload["vault_key"] = result["vault_key"]
                payload["vault_files"] = result["vault_files"]
                payload["reconciled_source"] = result["source"]
                store.update_payload(rec.case_id, payload)
                updated_count += 1

    return {
        "batch_id": batch_id,
        "total_cases": len(records),
        "matched_count": matched_count,
        "updated_count": updated_count,
    }
