"""第 2 → 第 3 階申復庫連動（Plan 20-02）。

自第 2 階（抽樣預審）案件隨機抽選 N 案（預設 5），連動建立第 3 階申復案件（kind='appeal'）：
- 多源證據（檢驗數據、健保跨院雲端病歷、佐證庫檔案清單）由來源案件帶入；
- 申復理由以 D10 四段（①案情摘要 ②醫療必要性 ③規則依據 ④病歷佐證）組裝，規則全文經 get_rule 注入；
- 申復案件 case_id 固定為 `APL-S2-<來源案件 ID>`，重複連動不會重複建案，回報於 duplicates。

純編排層：不改動來源案件的審查狀態（支持度、payload["review"] 皆保持原樣）。
病史時間軸未在此載入，故②醫療必要性採「病歷缺席」降級文案，待接入病歷來源後再補強。
"""

from __future__ import annotations

import random
import re

from elc_audit_engine import evidence_vault
from elc_audit_engine.case_store import DuplicateCaseError
from elc_audit_engine.generators.appeal import build_appeal_draft
from elc_audit_engine.parsers.models import DeductionRecord
from elc_audit_engine.rule_repository import get_rule

APPEAL_KIND = "appeal"
LINK_PREFIX = "APL-S2-"
DEFAULT_COUNT = 5
MAX_COUNT = 30
_CLOUD_SNIPPET_CHARS = 300


def link_stage2_to_appeal(
    store,
    source_records,
    *,
    count: int = DEFAULT_COUNT,
    seed: int | None = None,
    actor: str | None = None,
) -> dict:
    """隨機抽選第 2 階案件並建立第 3 階申復案件。

    Args:
        store: CaseStore。
        source_records: 第 2 階（kind='sampling'）案件紀錄清單。
        count: 抽選案數（1～MAX_COUNT）。
        seed: 隨機種子；同 seed 且同名單可重現。
        actor: 操作者（寫入狀態歷程）。

    Returns:
        {"selected": [來源案件 ID], "created": [申復案件 ID], "duplicates": [已存在的申復案件 ID]}

    Raises:
        ValueError: count 超出範圍。
        RuleRepositoryError: 規則庫故障（P0-2：不以「查無規則」掩蓋）。
    """
    if not 1 <= count <= MAX_COUNT:
        raise ValueError(f"抽選案數須介於 1 至 {MAX_COUNT}")
    pool = sorted(source_records, key=lambda record: record.case_id)  # 先排序，同 seed 可重現
    chosen = random.Random(seed).sample(pool, min(count, len(pool)))

    created: list[str] = []
    duplicates: list[str] = []
    for record in chosen:
        payload = _appeal_payload(record)
        appeal_id = f"{LINK_PREFIX}{record.case_id}"
        try:
            store.create(
                case_id=appeal_id,
                kind=APPEAL_KIND,
                order_code=payload["order_code"] or None,
                payload=payload,
                actor=actor,
            )
        except DuplicateCaseError:
            duplicates.append(appeal_id)
            continue
        created.append(appeal_id)
    return {
        "selected": [record.case_id for record in chosen],
        "created": created,
        "duplicates": duplicates,
    }


def _appeal_payload(record) -> dict:
    src = dict(record.payload or {})
    labs = [item for item in (src.get("lab_results") or []) if isinstance(item, dict) and item.get("name")]
    cloud = str(src.get("cloud_records") or "").strip()
    order_code = str(src.get("order_code") or "").strip()
    order_name = src.get("order_name")
    if not order_name and order_code:
        try:
            rule_obj = get_rule(order_code)
            if rule_obj and rule_obj.found and rule_obj.name:
                order_name = rule_obj.name
        except Exception:
            pass

    rule_text, rule_location = _rule_for(order_code)

    vault_files = _vault_file_names(src)
    # 連動預設以核減金額作為申復訴求點數，使新連動案件符合申復 XML 導出規範（p6 點數受理）
    default_deduct = src.get("deduct_amount") or 100
    claimed_points = src.get("claimed_points") if src.get("claimed_points") is not None else default_deduct

    draft = build_appeal_draft(
        DeductionRecord(case_seq=src.get("case_seq") or None, order_code=order_code or None, non_reimbursed_amount=default_deduct),
        is_appealing=True,
        claimed_points=claimed_points,
        timeline=None,
        rule_text=rule_text,
        rule_location=rule_location,
        evidence=_evidence_lines(labs, cloud),
        has_attachment=bool(vault_files.get("images") or vault_files.get("reports")),
    )
    return {
        "source": "stage2",
        "source_case_id": record.case_id,
        "case_seq": src.get("case_seq") or "1",
        "case_class": (src.get("monthly_source") or {}).get("case_class"),
        "fee_year_month": _fee_year_month(src.get("batch")),
        "order_seq": src.get("order_seq") or "1",
        "patient_name": src.get("patient_name"),
        "record_no": src.get("record_no"),
        "birth_date": src.get("birth_date") or (src.get("monthly_source") or {}).get("birth_date"),
        "total_points": src.get("total_points") or (src.get("monthly_source") or {}).get("total_points"),
        "clinic": src.get("clinic") or (src.get("monthly_source") or {}).get("clinic"),
        "doctor_code": src.get("doctor_code") or (src.get("monthly_source") or {}).get("doctor_code"),
        "primary_diagnosis": src.get("primary_diagnosis") or (src.get("monthly_source") or {}).get("primary_diagnosis"),
        "secondary_diagnoses": src.get("secondary_diagnoses") or (src.get("monthly_source") or {}).get("secondary_diagnoses") or [],
        "monthly_source": src.get("monthly_source"),
        "visit_date": src.get("visit_date"),
        "order_code": order_code,
        "order_name": order_name,
        "deduct_amount": default_deduct,
        "claimed_points": claimed_points,
        "p6_points": claimed_points,
        "deduction_reason": src.get("deduction_reason") or "抽審未附完整佐證核減",
        "soap": src.get("soap") or "",
        "lab_results": labs,
        "cloud_records": cloud or None,
        "multisource_evidence": {
            "labs": labs,
            "cloud_sync": [cloud] if cloud else [],
            "vault": vault_files,
        },
        "appeal_sections": [
            {"key": s.key, "title": s.title, "text": s.text, "trimmed": s.trimmed}
            for s in draft.sections
        ],
        "appeal_reason1": draft.reason1,
        "appeal_reason2": draft.reason2,
        "appeal_total_chars": draft.total_chars,
        "appeal_over_limit": draft.over_limit,
        "appeal_validation_errors": list(draft.validation_errors),
    }


def _fee_year_month(batch: object) -> str | None:
    """`MONTHLY-202307` → `202307`（費用年月 YYYYMM）；格式不符回 None。"""
    match = re.fullmatch(r"MONTHLY-(\d{6})", str(batch or ""))
    return match.group(1) if match else None


def appeal_xml_case(payload: dict) -> dict:
    """申復案件 payload → build_batch_appeal_xml 的單案輸入。

    申復點數（claimed_points）、是否申復（is_appealing）、附件（has_attachment）由醫師於申復工作台填寫；
    未填寫時不會自動推算，批次導出會以 422 明確拒絕，避免把推測值送審。
    """
    return {
        "case_class": payload.get("case_class"),
        "case_seq": payload.get("case_seq"),
        "fee_year_month": payload.get("fee_year_month"),
        "items": [{
            "order_seq": payload.get("order_seq"),
            "order_code": payload.get("order_code"),
            "is_appealing": payload.get("is_appealing", True),
            "claimed_points": payload.get("claimed_points"),
            "has_attachment": bool(payload.get("has_attachment", False)),
            "reason1": payload.get("appeal_reason1"),
            "reason2": payload.get("appeal_reason2"),
        }],
    }


def _rule_for(order_code: str) -> tuple[str | None, str | None]:
    """規則全文與出處；查無規則回 (None, None)，不捏造條文。"""
    if not order_code:
        return None, None
    rule = get_rule(order_code)
    if not rule.found:
        return None, None
    return (rule.article_full_text or rule.payment_text or None), rule.article_location


def _evidence_lines(labs: list[dict], cloud: str) -> list[str]:
    """④病歷佐證素材：檢驗數據與雲端病歷摘要（逐項列出，不改寫原文）。"""
    lines = [
        " ".join(part for part in (f"檢驗：{item['name']}", str(item.get("value") or ""), str(item.get("unit") or "")) if part)
        for item in labs
    ]
    if cloud:
        lines.append("健保跨院病歷：" + cloud[:_CLOUD_SNIPPET_CHARS])
    return lines


def _vault_file_names(src: dict) -> dict[str, list[str]]:
    """依來源案件的身分證與就醫日，列出佐證庫檔名（分類 → 檔名）；無佐證庫回空。"""
    vault_key = evidence_vault.vault_key_for_case(src.get("record_no"), src.get("visit_date"))
    if vault_key is None:
        return {}
    return {
        category: [f.filename for f in files]
        for category, files in evidence_vault.list_vault_files(vault_key).items()
        if files
    }


__all__ = ["APPEAL_KIND", "DEFAULT_COUNT", "LINK_PREFIX", "MAX_COUNT", "link_stage2_to_appeal"]
