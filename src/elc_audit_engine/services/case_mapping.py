"""案件列表契約的映射函式（Phase 22-04：Flask-free，供服務層與路由共用）。"""

from __future__ import annotations

import dataclasses
import hashlib
import json

from elc_audit_engine.rule_repository import get_rule
from elc_audit_engine.rule_repository.errors import RuleRepositoryError


def content_case_id(prefix: str, rec) -> str:
    """以記錄業務內容雜湊產生 case_id（A-CR-02）。

    原本 f"{prefix}-{idx:04d}" 每次匯入都從 0001 起算，第二批不同內容的案件
    會全數被當成重複而靜默拒收。改以內容雜湊：
    - 不同批次、不同內容 → 不同 id，不再撞號；
    - 同一份檔案重複匯入 → 同 id，由 CaseStore 回報 conflicts（冪等）。
    raw／ocr_line／source 為來源格式資訊，不參與雜湊。
    """
    fields = {
        k: v for k, v in dataclasses.asdict(rec).items()
        if k not in {"raw", "ocr_line", "source", "lab_results", "cloud_records", "attachments"}
    }
    digest = hashlib.sha256(
        json.dumps(fields, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return f"{prefix}-{digest}"

def to_sampling_case(idx: int, rec) -> dict:
    """SamplingCaseRecord → 前端列表契約 dict（醫令名稱優先自規則庫查詢）。"""
    order_name = getattr(rec, "order_name", None)
    if not order_name and rec.order_code:
        try:
            rule = get_rule(rec.order_code)
            if rule and rule.found and rule.name:
                order_name = rule.name
        except RuleRepositoryError:  # 規則庫故障僅降級為不補醫令名稱（P1-11）
            pass
    return {
        "id": content_case_id("SAMP", rec),
        "demo": False,
        "case_seq": rec.case_seq or str(idx),
        "record_no": rec.record_no,
        "patient_name": rec.patient_name,
        "order_code": rec.order_code,
        "order_name": order_name,
        "visit_date": rec.visit_date,
        "clinic": rec.clinic,
        "soap": rec.soap_text or "",
        "support_level": None,
        "missing_reason": None,
        "source": rec.source,
        "ocr_line": rec.ocr_line,
        "lab_results": list(getattr(rec, "lab_results", ()) or ()),
        "cloud_records": getattr(rec, "cloud_records", None),
        "attachments": list(getattr(rec, "attachments", ()) or ()),
    }
