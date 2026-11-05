"""當月申報檔（TOTFA.zip）匯入 CaseStore（Phase 15-01）。

- 每筆成功案件以 `kind="monthly"`、內容雜湊 `MON-…` 為 case_id 建立。
- 同一批次重複匯入：既有 case_id 會被略過（計入 `skipped_existing`），
  不覆寫既有狀態與歷史（沿用 CaseStore 的 DuplicateCaseError 語意）。
- 拒收案件（缺 d1/d2、d3、pdata）不入庫，只計數並回傳原因。
- 每筆 create 各自一個交易；中途失敗時已寫入的案件保留，重跑即冪等補齊。
- payload 含患者識別欄位（d3 病歷號、d49 姓名、d11 出生日期），供報告顯示；
  這些欄位屬 PHI，僅存於 cases.sqlite3（不進版控），**不得寫入日誌**。
"""

from __future__ import annotations

from dataclasses import dataclass

from elc_audit_engine.case_store.store import CaseStore, DuplicateCaseError
from elc_audit_engine.parsers.models import SubmissionCase, SubmissionParseResult
from elc_audit_engine.parsers.totfa import batch_name_from_header, monthly_case_ids


@dataclass(frozen=True)
class MonthlyIngestSummary:
    """一次匯入的結果計數（不含 PHI）。

    Attributes:
        batch: 批次名，如 `MONTHLY-202307`。
        created: 本次新建的案件數。
        skipped_existing: 因 case_id 已存在而略過的案件數。
        rejected: 解析階段即被拒收、未入庫的案件數。
        case_ids: 本次批次中所有可入庫案件的 case_id（新建＋已存在）。
    """

    batch: str
    created: int
    skipped_existing: int
    rejected: int
    case_ids: tuple[str, ...]


def _payload(
    batch: str,
    case: SubmissionCase,
    *,
    store: CaseStore | None = None,
    facility_code: str | None = None,
) -> dict:
    payload = {
        "batch": batch,
        "case_class": case.case_class,
        # case_seq 可於同批次重複，僅作顯示／彙總欄位，不作主鍵（AGENTs.md §2.3）。
        "case_seq": case.case_seq,
        "record_no": case.record_no,
        "patient_name": case.patient_name,
        "birth_date": case.birth_date,
        "id_card": case.raw.get("d3", ""),
        "total_points": case.raw.get("d39"),  # 醫療費用總點數（報告門檻）
        "clinic": case.clinic,
        # d30 診治醫事人員代號（電子抽審.md）；僅作彙總鍵，不做其他用途。
        "doctor_code": case.raw.get("d30"),
        "visit_date": case.visit_date,
        "primary_diagnosis": case.primary_diagnosis,
        "secondary_diagnoses": list(case.secondary_diagnoses),
        "orders": [order.raw for order in case.orders],
        "warnings": list(case.warnings),
    }

    # 自動比對本機每日門診語音 SOAP 與佐證金庫（Phase 28-01）
    try:
        from elc_audit_engine.reconciliation.soap_reconciler import reconcile_case_soap
        reconciled = reconcile_case_soap(store, payload, facility_code=facility_code)
        if reconciled.get("found"):
            payload["soap"] = reconciled.get("soap")
            payload["soap_text"] = reconciled.get("soap_text")
            payload["vault_key"] = reconciled.get("vault_key")
            payload["vault_files"] = reconciled.get("vault_files")
            payload["reconciled_source"] = reconciled.get("source")
        else:
            payload["soap"] = ""
            payload["soap_text"] = ""
            payload["vault_key"] = reconciled.get("vault_key")
            payload["vault_files"] = []
    except Exception:
        payload["soap"] = ""
        payload["soap_text"] = ""

    return payload


def ingest_monthly_declaration(
    store: CaseStore,
    result: SubmissionParseResult,
    *,
    actor: str | None = None,
) -> MonthlyIngestSummary:
    """把 `parse_totfa_zip` 的結果寫入 CaseStore（冪等）。

    Args:
        store: 案件存放區。
        result: TOTFA.xml 解析結果。
        actor: 寫入者識別碼（不含 PHI）。

    Returns:
        MonthlyIngestSummary。

    Raises:
        SubmissionXmlError: tdata.t3 無法推得批次名（整檔不匯入）。
    """
    batch = batch_name_from_header(result.header)
    case_ids = monthly_case_ids(batch, result.cases)
    facility_code = (result.header.get("t2") or "").strip()

    created = 0
    skipped = 0
    for case_id, case in zip(case_ids, result.cases):
        try:
            store.create(
                case_id=case_id,
                kind="monthly",
                case_seq=case.case_seq,
                payload=_payload(batch, case, store=store, facility_code=facility_code),
                actor=actor,
            )
            created += 1
        except DuplicateCaseError:
            skipped += 1

    return MonthlyIngestSummary(
        batch=batch,
        created=created,
        skipped_existing=skipped,
        rejected=len(result.rejected),
        case_ids=case_ids,
    )
