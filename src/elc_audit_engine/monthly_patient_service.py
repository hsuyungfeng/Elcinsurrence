"""當月申報檔 (TOTFA) 跨模組資料帶入與病患鍵入檢索服務。

提供：
1. 查詢最新當月申報批次 (find_latest_monthly_batch)
2. 依病患身分證字號／出生年月日／姓名檢索當月申報案件 (find_monthly_patient_cases)
3. 當月申報一鍵帶入抽樣事前預審 (import_monthly_to_sampling)
4. 當月申報一鍵帶入核減事後申復 (import_monthly_to_appeal)
5. 單一病患鍵入加入抽審 (add_sampling_case_by_patient)
6. 單一病患鍵入加入申復 (add_appeal_case_by_patient)
"""

from __future__ import annotations

import hashlib
import re

from elc_audit_engine.services.date_utils import ROC_OFFSET
from elc_audit_engine.case_store.store import CaseStore
from elc_audit_engine.ingest.sampling import SamplingCaseRecord
from elc_audit_engine.rule_repository import get_rule
from elc_audit_engine.sampling_sampler import (
    _record,
    _target_code,
    sample_monthly_batch,
    top3_points_total,
)


def find_latest_monthly_batch(store: CaseStore) -> str | None:
    """找出最新一筆已入庫的當月申報批次名稱（依名稱倒序）。"""
    batches = store.list_batches()
    if not batches:
        return None
    # 批次名如 MONTHLY-202307，字串倒序排序即時間由新到舊
    sorted_batches = sorted([b[0] for b in batches], reverse=True)
    return sorted_batches[0]


def normalize_date_variants(raw_date: str) -> set[str]:
    """將輸入之日期字串（民國年或西元年）正規化為各種常見的比對形式。

    例如：
    - "0761224" -> {"0761224", "761224", "19871224"}
    - "1987-12-24" -> {"19871224", "0761224", "761224"}
    - "76/12/24" -> {"761224", "0761224", "19871224"}
    """
    clean = re.sub(r"[^\w]", "", raw_date).strip()
    if not clean:
        return set()
    variants = {clean, clean.lstrip("0")}

    # 若為 8 碼西元年 (YYYYMMDD)
    if len(clean) == 8 and clean[:4].isdigit():
        try:
            year = int(clean[:4])
            roc_year = year - ROC_OFFSET
            m_d = clean[4:]
            variants.add(f"{roc_year:03d}{m_d}")
            variants.add(f"{roc_year}{m_d}")
        except ValueError:
            pass
    # 若為 6 或 7 碼民國年 (YYYMMDD / YYMMDD)
    elif len(clean) in (6, 7) and clean.isdigit():
        try:
            roc_year = int(clean[:-4])
            ce_year = roc_year + ROC_OFFSET
            m_d = clean[-4:]
            variants.add(f"{ce_year:04d}{m_d}")
            variants.add(f"{roc_year:03d}{m_d}")
            variants.add(f"{roc_year}{m_d}")
        except ValueError:
            pass

    return variants


def find_monthly_patient_cases(
    store: CaseStore,
    *,
    id_card: str = "",
    birth_date: str = "",
    patient_name: str = "",
    batch_id: str | None = None,
) -> list[dict]:
    """在當月申報檔 (kind='monthly') 中比對病患案件。

    以身分證字號、出生年月日與病患姓名進行彈性比對；
    若提供 batch_id 則限定該批次，否則搜尋所有已匯入之當月申報批次。
    回傳相符案件的原始 payload 清單。
    """
    id_card_clean = re.sub(r"[^\w]", "", id_card).strip().upper()
    name_clean = patient_name.strip()
    birth_variants = normalize_date_variants(birth_date)

    if not id_card_clean and not name_clean and not birth_variants:
        return []

    # 取得要比對的批次
    batches_to_search: list[str] = []
    if batch_id:
        batches_to_search = [batch_id]
    else:
        latest = find_latest_monthly_batch(store)
        if latest:
            batches_to_search = [latest]
        else:
            batches_to_search = [b[0] for b in store.list_batches()]

    matched: list[dict] = []
    for b in batches_to_search:
        offset = 0
        limit = 500
        while True:
            records = store.list_by_batch(b, limit=limit, offset=offset)
            if not records:
                break
            for rec in records:
                payload = rec.payload or {}
                # 取得案件內患者欄位
                rec_id = (
                    payload.get("id_card")
                    or payload.get("record_no")
                    or ""
                )
                rec_id_clean = re.sub(r"[^\w]", "", str(rec_id)).strip().upper()

                rec_name = str(payload.get("patient_name") or "").strip()
                rec_birth = str(payload.get("birth_date") or "").strip()
                rec_birth_variants = normalize_date_variants(rec_birth)

                score = 0
                required_checks = 0

                # 1. 身分證字號比對
                if id_card_clean:
                    required_checks += 1
                    if id_card_clean == rec_id_clean or id_card_clean in rec_id_clean or rec_id_clean in id_card_clean:
                        score += 1

                # 2. 姓名比對
                if name_clean:
                    required_checks += 1
                    if name_clean == rec_name or name_clean in rec_name or rec_name in name_clean:
                        score += 1

                # 3. 出生年月日比對
                if birth_variants:
                    required_checks += 1
                    if birth_variants.intersection(rec_birth_variants):
                        score += 1

                # 當提供多個欄位時，所有提供的欄位皆相符才判定為命中；若只提供一個欄位則該欄位命中即可
                if required_checks > 0 and score == required_checks:
                    item = dict(payload)
                    item["_monthly_case_id"] = rec.case_id
                    matched.append(item)

            offset += len(records)

    return matched


def monthly_payload_to_sampling_case(payload: dict, case_seq: int | str = 1) -> dict:
    """將當月申報 payload 轉成抽審工作台之 Sampling Case 契約 dict。"""
    from elc_audit_engine.api.cases import to_sampling_case
    from elc_audit_engine.reconciliation.soap_reconciler import format_soap_to_text

    target = _target_code(payload)
    rec = _record(payload, target)
    case = to_sampling_case(int(case_seq) if str(case_seq).isdigit() else 1, rec)
    case["batch"] = payload.get("batch")
    case["monthly_case_id"] = payload.get("_monthly_case_id") or payload.get("id") or f"MON-{case.get('id', '')}"
    case["sample_type"] = "patient_entry"
    case["top3_points_total"] = str(top3_points_total(payload))
    case["target_order_code"] = target
    case["birth_date"] = payload.get("birth_date")
    case["id_card"] = payload.get("id_card") or payload.get("record_no")
    case["monthly_source"] = payload

    # 繼承自動比對所得之真實日常門診語音 SOAP 與佐證金庫
    soap_val = payload.get("soap_text") or (format_soap_to_text(payload.get("soap")) if isinstance(payload.get("soap"), dict) else payload.get("soap")) or case.get("soap") or ""
    case["soap"] = soap_val
    case["vault_key"] = payload.get("vault_key")
    case["vault_files"] = payload.get("vault_files") or []
    return case


def monthly_payload_to_appeal_case(payload: dict, case_seq: int | str = 1) -> dict:
    """將當月申報 payload 轉成申復工作台之 Appeal Case 契約 dict。"""
    from elc_audit_engine.reconciliation.soap_reconciler import format_soap_to_text

    orders = payload.get("orders") or []
    target = _target_code(payload)
    matched_order = None
    for o in orders:
        if (o.get("p4") or "").strip() == target:
            matched_order = o
            break
    if not matched_order and orders:
        matched_order = orders[0]

    order_code = target or (matched_order.get("p4") if matched_order else "") or ""
    order_name = None
    if order_code:
        try:
            rule = get_rule(order_code)
            if rule and rule.found:
                order_name = rule.name
        except Exception:
            pass

    order_seq = (matched_order.get("p13") if matched_order else None) or "1"
    points = (
        (matched_order.get("p12") if matched_order else None)
        or (matched_order.get("p11") if matched_order else None)
        or payload.get("total_points")
        or "0"
    )

    id_val = payload.get("id_card") or payload.get("record_no") or ""
    visit_date = payload.get("visit_date") or ""
    digest_input = f"{id_val}-{visit_date}-{order_code}-{order_seq}"
    c_id = f"APP-M-{hashlib.sha256(digest_input.encode('utf-8')).hexdigest()[:14]}"

    soap_val = payload.get("soap_text") or (format_soap_to_text(payload.get("soap")) if isinstance(payload.get("soap"), dict) else payload.get("soap")) or ""
    vault_files = payload.get("vault_files") or []

    # 依佐證檔案自動組裝 multisource_evidence 多源證據清單
    evidence: dict[str, list] = {"labs": [], "images": [], "cloud_sync": []}
    for vf in vault_files:
        cat = vf.get("category")
        fname = vf.get("filename", "")
        if cat == "images" or fname.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            evidence["images"].append({"name": fname, "report": f"佐證庫影像：{fname}"})
        elif cat == "reports" or fname.lower().endswith((".pdf", ".txt")):
            evidence["labs"].append({"name": fname, "result": f"佐證庫報告：{fname}"})

    return {
        "id": c_id,
        "demo": False,
        "case_seq": str(payload.get("case_seq") or case_seq),
        "record_no": payload.get("record_no"),
        "id_number": id_val,
        "patient_name": payload.get("patient_name"),
        "birth_date": payload.get("birth_date"),
        "order_code": order_code,
        "order_name": order_name or order_code,
        "order_seq": order_seq,
        "deduct_amount": str(points),
        "deduction_reason": "申報費用審查核減（自當月申報預審資料帶入）",
        "visit_date": visit_date,
        "soap": soap_val,
        "vault_key": payload.get("vault_key"),
        "vault_files": vault_files,
        "multisource_evidence": evidence,
        "source": "monthly_declaration",
        "monthly_source": payload,
    }


def import_monthly_to_sampling(
    store: CaseStore,
    *,
    batch_id: str | None = None,
    limit: int = 30,
    actor: str | None = None,
) -> dict:
    """自當月申報批次一鍵匯入抽樣清單 (kind='sampling')。"""
    from elc_audit_engine.api.cases import persist_cases, to_sampling_case

    batch = batch_id or find_latest_monthly_batch(store)
    if not batch:
        return {"status": "error", "message": "尚未上傳任何當月申報批次資料 (申報壓縮檔)"}

    # 若批次案件大於 limit，使用 20 隨機 + 10 立意抽樣
    count = store.count_by_batch(batch)
    if count == 0:
        return {"status": "error", "message": f"批次 {batch} 內無任何案件"}

    if count > limit:
        sampled = sample_monthly_batch(
            store, batch, random_count=min(20, limit), intentional_count=max(0, limit - 20)
        )
        cases = []
        for idx, item in enumerate(sampled, start=1):
            c = to_sampling_case(idx, item.record)
            c["sample_type"] = item.sample_type
            c["batch"] = batch
            c["monthly_case_id"] = item.monthly_case_id
            c["top3_points_total"] = str(item.top3_points_total)
            c["target_order_code"] = item.target_order_code
            c["monthly_source"] = item.source_payload
            cases.append(c)
    else:
        records = store.list_by_batch(batch, limit=limit)
        cases = [
            monthly_payload_to_sampling_case(rec.payload or {}, idx)
            for idx, rec in enumerate(records, start=1)
        ]

    persisted, conflicts = persist_cases(store, "sampling", cases, actor)
    return {
        "status": "success",
        "batch": batch,
        "total_in_batch": count,
        "imported": len(cases),
        "persisted": persisted,
        "conflicts": conflicts,
        "cases": cases,
    }


def import_monthly_to_appeal(
    store: CaseStore,
    *,
    batch_id: str | None = None,
    limit: int = 20,
    actor: str | None = None,
) -> dict:
    """自當月申報批次一鍵匯入申復清單 (kind='appeal')。"""
    from elc_audit_engine.api.cases import persist_cases

    batch = batch_id or find_latest_monthly_batch(store)
    if not batch:
        return {"status": "error", "message": "尚未上傳任何當月申報批次資料 (申報壓縮檔)"}

    count = store.count_by_batch(batch)
    if count == 0:
        return {"status": "error", "message": f"批次 {batch} 內無任何案件"}

    # 取得批次中金額最高或前 N 筆案件帶入申復
    records = store.list_by_batch(batch, limit=limit)
    cases = [
        monthly_payload_to_appeal_case(rec.payload or {}, idx)
        for idx, rec in enumerate(records, start=1)
    ]

    persisted, conflicts = persist_cases(store, "appeal", cases, actor)
    return {
        "status": "success",
        "batch": batch,
        "total_in_batch": count,
        "imported": len(cases),
        "persisted": persisted,
        "conflicts": conflicts,
        "cases": cases,
    }


def add_sampling_case_by_patient(
    store: CaseStore,
    *,
    id_card: str = "",
    birth_date: str = "",
    patient_name: str = "",
    batch_id: str | None = None,
    actor: str | None = None,
) -> dict:
    """依病患資訊單筆鍵入加入抽審 (Sampling) 清單。"""
    from elc_audit_engine.api.cases import persist_cases, to_sampling_case

    matched_payloads = find_monthly_patient_cases(
        store, id_card=id_card, birth_date=birth_date, patient_name=patient_name, batch_id=batch_id
    )

    created_cases = []
    if matched_payloads:
        for idx, payload in enumerate(matched_payloads, start=1):
            c = monthly_payload_to_sampling_case(payload, idx)
            created_cases.append(c)
    else:
        # 手動建立備用案件
        digest_input = f"{id_card}-{patient_name}-{birth_date}"
        c_id = f"SAMP-MANUAL-{hashlib.sha256(digest_input.encode('utf-8')).hexdigest()[:12]}"
        rec = SamplingCaseRecord(
            order_code="",
            order_name="",
            case_seq="1",
            record_no=id_card,
            patient_name=patient_name,
            visit_date="",
            clinic="",
            soap_text="",
            source="manual_entry",
        )
        c = to_sampling_case(1, rec)
        c["id"] = c_id
        c["sample_type"] = "manual"
        c["id_card"] = id_card
        c["birth_date"] = birth_date
        c["monthly_source"] = {
            "record_no": id_card,
            "patient_name": patient_name,
            "birth_date": birth_date,
            "orders": [],
        }
        created_cases.append(c)

    persisted, conflicts = persist_cases(store, "sampling", created_cases, actor)
    return {
        "status": "success",
        "matched_monthly": bool(matched_payloads),
        "count": len(created_cases),
        "persisted": persisted,
        "conflicts": conflicts,
        "cases": created_cases,
    }


def add_appeal_case_by_patient(
    store: CaseStore,
    *,
    id_card: str = "",
    birth_date: str = "",
    patient_name: str = "",
    batch_id: str | None = None,
    actor: str | None = None,
) -> dict:
    """依病患資訊單筆鍵入加入申復 (Appeal) 清單。"""
    from elc_audit_engine.api.cases import persist_cases

    matched_payloads = find_monthly_patient_cases(
        store, id_card=id_card, birth_date=birth_date, patient_name=patient_name, batch_id=batch_id
    )

    created_cases = []
    if matched_payloads:
        for idx, payload in enumerate(matched_payloads, start=1):
            c = monthly_payload_to_appeal_case(payload, idx)
            created_cases.append(c)
    else:
        # 手動建立備用案件
        digest_input = f"{id_card}-{patient_name}-{birth_date}"
        c_id = f"APP-MANUAL-{hashlib.sha256(digest_input.encode('utf-8')).hexdigest()[:12]}"
        c = {
            "id": c_id,
            "demo": False,
            "case_seq": "1",
            "record_no": id_card,
            "id_number": id_card,
            "patient_name": patient_name,
            "birth_date": birth_date,
            "order_code": "",
            "order_name": "待填寫醫令",
            "order_seq": "1",
            "deduct_amount": "0",
            "deduction_reason": "待填寫申復理由",
            "visit_date": "",
            "soap": "",
            "multisource_evidence": {"labs": [], "images": [], "cloud_sync": []},
            "source": "manual_entry",
            "monthly_source": {
                "record_no": id_card,
                "patient_name": patient_name,
                "birth_date": birth_date,
                "orders": [],
            },
        }
        created_cases.append(c)

    persisted, conflicts = persist_cases(store, "appeal", created_cases, actor)
    return {
        "status": "success",
        "matched_monthly": bool(matched_payloads),
        "count": len(created_cases),
        "persisted": persisted,
        "conflicts": conflicts,
        "cases": created_cases,
    }
