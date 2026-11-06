"""處置／手術類高價醫令的範例病歷預生成與 DB 快取（Plan 15-04）。

- 適用對象：點數 > 350 且**非藥品**（醫令類別 ≠ DRUG_CATEGORY）的旗標醫令。
- 快取鍵：(醫令代碼, 主診斷)。命中即直接回傳，不呼叫 LLM。
- 品質關卡：LLM 產出須通過 `validate_soap_quality` 才會存庫；未通過者回傳 `quality_failed`
  且**不寫入快取**，避免壞範本被反覆使用。
- LLM 失敗回 `undetermined`（系統故障），不寫入、不偽裝成範本。
- 範本僅供醫師參考與自行修改，不是病歷的事實紀錄。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from elc_audit_engine.case_store.store import CaseStore
from elc_audit_engine.comparator.soap_advice import (
    generate_soap_advice,
    validate_soap_quality,
)
from elc_audit_engine.monthly_audit import (
    STATUS_RESTRICTION,
    BatchAudit,
    OrderFinding,
    is_excluded_order_code,
)
from elc_audit_engine.parsers.totfa import DRUG_CATEGORY

POINTS_FLAG = "points_over_350"
SOURCE_LLM = "llm_validated"

STATUS_CACHE = "cache"
STATUS_GENERATED = "generated"
STATUS_QUALITY_FAILED = "quality_failed"
STATUS_UNDETERMINED = "undetermined"

Generator = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class PregenOutcome:
    status: str
    soap: dict[str, str] | None
    quality: dict[str, Any] | None


# 病理檢驗（外科病理等）是檢驗室報告，不是醫師開立的手術／處置紀錄，不產生範例病歷。
PATHOLOGY_CODE_PREFIX = "25"
PATHOLOGY_EXCLUDED_CODES = frozenset({"25003C", "25004C"})


def is_pathology_code(code: str) -> bool:
    """病理檢驗醫令：代碼以 25 開頭（外科病理等級），或列於明確排除清單。"""
    normalized = (code or "").strip().upper()
    return normalized.startswith(PATHOLOGY_CODE_PREFIX) or normalized in PATHOLOGY_EXCLUDED_CODES


def is_pregen_target(finding: OrderFinding) -> bool:
    """需要範例病歷範本的醫令：處置／手術高價醫令，或有給付限制（restriction_present）的醫令。

    排除診療費（001 開頭）與病理檢查；給付限制醫令不受點數與藥品門檻影響。
    """
    if is_excluded_order_code(finding.code):
        return False
    if finding.rule_status == STATUS_RESTRICTION and not is_pathology_code(finding.code):
        return True
    return is_procedure_finding(finding)


def is_procedure_finding(finding: OrderFinding) -> bool:
    """處置／手術類高價醫令：點數 > 350、非藥品，且非病理檢驗（不產生範例病歷）。"""
    return (
        finding.category != DRUG_CATEGORY
        and POINTS_FLAG in finding.flags
        and not is_pathology_code(finding.code)
    )


def _key(code: str, dx: str) -> tuple[str, str]:
    return (code or "").strip().upper(), (dx or "").strip().upper()


def pregen_template(
    store: CaseStore,
    *,
    order_code: str,
    order_name: str,
    primary_diagnosis: str,
    rule_text: str = "",
    force: bool = False,
    generator: Generator | None = None,
) -> PregenOutcome:
    """取得（或生成）單一醫令＋主診斷的範例病歷。`force=True` 略過快取重新生成。"""
    if not force:
        cached = store.get_soap_template(order_code, primary_diagnosis)
        if cached is not None:
            return PregenOutcome(STATUS_CACHE, cached["soap"], {"quality_score": cached["quality_score"]})

    call = generator or generate_soap_advice  # 執行期解析，便於測試替換
    advice = call(
        order_code=order_code,
        order_name=order_name or order_code,
        soap_text="",
        patient_history="",
        rule_text=rule_text,
    )
    if advice.get("status") == "error":
        return PregenOutcome(STATUS_UNDETERMINED, None, None)

    soap = advice.get("recommended_soap") or {}
    quality = validate_soap_quality(soap)
    if not quality["pass"]:
        return PregenOutcome(STATUS_QUALITY_FAILED, soap, quality)

    store.put_soap_template(
        order_code,
        primary_diagnosis,
        {k: str(soap[k]).strip() for k in ("s", "o", "a", "p")},
        source=SOURCE_LLM,
        quality_score=quality["quality_score"],
    )
    return PregenOutcome(STATUS_GENERATED, soap, quality)


def procedure_targets(batch: BatchAudit) -> list[tuple[str, str, str, str]]:
    """批次內需範本醫令（處置高價＋給付限制）的唯一 (醫令代碼, 醫令名稱, 主診斷, 規則全文) 清單（依首次出現排序）。"""
    seen: set[tuple[str, str]] = set()
    targets: list[tuple[str, str, str, str]] = []
    for case in batch.cases:
        for finding in case.findings:
            if not is_pregen_target(finding):
                continue
            key = _key(finding.code, case.primary_diagnosis or "")
            if key in seen or not key[0] or not key[1]:
                continue
            seen.add(key)
            targets.append((finding.code, finding.rule_name or finding.code, case.primary_diagnosis or "", finding.rule_full_text or ""))
    return targets


def load_templates(store: CaseStore, batch: BatchAudit) -> dict[tuple[str, str], dict[str, str]]:
    """報告用：回傳已快取範本 {(醫令代碼, 主診斷): soap}；未快取者不出現在結果中（不輸出空框）。"""
    found: dict[tuple[str, str], dict[str, str]] = {}
    for code, _name, dx, _text in procedure_targets(batch):
        cached = store.get_soap_template(code, dx)
        if cached is not None:
            found[_key(code, dx)] = cached["soap"]
    return found


def pregen_batch(
    store: CaseStore,
    batch: BatchAudit,
    *,
    limit: int,
    generator: Generator | None = None,
) -> dict[str, int]:
    """批次預生成：快取命中不計入 `limit`；每筆 LLM 呼叫計為一次，達 `limit` 即停止。

    Returns:
        {"targets", "cached", "generated", "quality_failed", "undetermined", "skipped_limit"}
    """
    counts = {"targets": 0, "cached": 0, "generated": 0, "quality_failed": 0, "undetermined": 0, "skipped_limit": 0}
    llm_calls = 0
    for code, name, dx, text in procedure_targets(batch):
        counts["targets"] += 1
        if store.get_soap_template(code, dx) is not None:
            counts["cached"] += 1
            continue
        if llm_calls >= limit:
            counts["skipped_limit"] += 1
            continue
        llm_calls += 1
        outcome = pregen_template(
            store, order_code=code, order_name=name, primary_diagnosis=dx, rule_text=text, generator=generator,
        )
        counts[outcome.status if outcome.status in counts else "undetermined"] += 1
    return counts
