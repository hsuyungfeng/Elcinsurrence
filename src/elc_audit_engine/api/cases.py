"""匯入記錄 → 案件 payload 的轉換，以及 CaseStore 持久化／舊快照遷移。"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

from elc_audit_engine.case_store import CaseStore, DuplicateCaseError
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
        if k not in {"raw", "ocr_line", "source"}
    }
    digest = hashlib.sha256(
        json.dumps(fields, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return f"{prefix}-{digest}"


def to_sampling_case(idx: int, rec) -> dict:
    """SamplingCaseRecord → 前端列表契約 dict。"""
    return {
        "id": content_case_id("SAMP", rec),
        "demo": False,
        "case_seq": rec.case_seq or str(idx),
        "record_no": rec.record_no,
        "patient_name": rec.patient_name,
        "order_code": rec.order_code,
        "order_name": rec.order_name,
        "visit_date": rec.visit_date,
        "clinic": rec.clinic,
        "soap": rec.soap_text or "",
        "support_level": None,
        "missing_reason": None,
        "source": rec.source,
        "ocr_line": rec.ocr_line,
    }


def to_appeal_case(idx: int, rec) -> dict:
    """DeductionRecord → 前端列表契約 dict（醫令名稱以規則庫為準）。"""
    name = None
    try:
        rule = get_rule(rec.order_code or "")
        if rule.found:
            name = rule.name
    except RuleRepositoryError:
        pass  # 名稱缺失不阻斷導入，前端以代碼顯示
    return {
        "id": content_case_id("APP", rec),
        "demo": False,
        "case_seq": rec.case_seq or str(idx),
        "record_no": None,
        # W5 數據流（D-05 前置）：透傳 rec.id_number（健保署已遮罩後 4 碼）——
        # 僅透傳不重組完整字號；缺省 None 時照印 None、不捏造。
        "id_number": rec.id_number,
        "patient_name": None,
        "order_code": rec.order_code,
        "order_name": name or rec.order_code,
        # W5 數據流（11.1-01）：透傳 rec.order_seq（欄 10「醫令序號」，對應
        # 申報 XML p13）——僅透傳不轉型。
        "order_seq": rec.order_seq,
        "deduct_amount": rec.non_reimbursed_amount,
        "deduction_reason": rec.deduction_reason or rec.institution_note or "",
        "visit_date": rec.visit_date,
        "soap": "",
        "multisource_evidence": {"labs": [], "images": [], "cloud_sync": []},
        "source": "csv",
    }


def persist_cases(
    store: CaseStore, kind: str, cases: list[dict], actor: str | None
) -> tuple[int, list[str]]:
    """將解析後的案件逐筆持久化至 CaseStore (state=imported)。

    重複的 case_id 記入 conflicts 並拒絕建案，其餘照常建案；非
    DuplicateCaseError（如 UnsafeIdentifierError）不捕捉，直接向上傳播。
    """
    persisted = 0
    conflicts: list[str] = []
    for case in cases:
        try:
            store.create(
                case_id=case["id"],
                kind=kind,
                case_seq=case.get("case_seq"),
                order_code=case.get("order_code"),
                payload=case,
                actor=actor,
            )
            persisted += 1
        except DuplicateCaseError:
            conflicts.append(case["id"])
    return persisted, conflicts


def load_latest_cases(upload_dir: str, kind: str) -> list[dict] | None:
    """載入最新一份舊版匯入快照 data/uploads/{kind}_*.json；無檔或損毀回 None。"""
    files = sorted(Path(upload_dir).glob(f"{kind}_*.json"))
    if not files:
        return None
    try:
        with open(files[-1], encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def migrate_legacy_uploads(store: CaseStore, upload_dir: str) -> dict[str, int]:
    """一次性且冪等地把舊版 data/uploads/*.json 快照中尚未入庫的案件遷入 CaseStore。

    2026-09 起匯入不再寫快照（A-WR-11）；此遷移只為接住升級前留下的檔案。
    """
    migrated_counts = {"sampling": 0, "appeal": 0}
    for kind in ("sampling", "appeal"):
        cases = load_latest_cases(upload_dir, kind)
        if not cases:
            continue
        for case in cases:
            try:
                store.create(
                    case_id=case["id"],
                    kind=kind,
                    case_seq=case.get("case_seq"),
                    order_code=case.get("order_code"),
                    payload=case,
                )
                migrated_counts[kind] += 1
            except DuplicateCaseError:
                pass
    return migrated_counts
