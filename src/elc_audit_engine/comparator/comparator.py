"""三方比對器主流程（Phase 5 單一入口）：compare_case()。

流程（設計文件 §4）：
1. 要求萃取：每筆醫令查 `get_rule(p4)` → 檢核項（規則全文＋出處，D-01）
2. 證據搜尋：`build_evidence_blocks` 組裝當次 SOAP ＋ 半年病史（D-02）
3. 逐檢核項判定（C1）：judge_fn（LLM 或注入替身）→ Judgment
4. 三級分類（D-04）：classify_support
5. 缺口（薄弱/裸奔）生成候選補強（D-05/C2）

錯誤語意（D-06/P0-2）：`RuleRepositoryError`（DB 故障）穿透不吞；只有
`get_rule` 回傳 found=False（正常查無）才標未知醫令。
病歷缺席（D-07）：timeline=None 時只用當次 SOAP，結果 records_degraded=True。
"""

from __future__ import annotations

from datetime import date
from typing import Callable

from elc_audit_engine.parsers.models import SOAPDocument, SubmissionCase
from elc_audit_engine.record_aggregator.models import PatientTimeline
from elc_audit_engine.rule_repository import get_rule, is_effective_on
from elc_audit_engine.rule_repository.loaders.dates import parse_flexible_date
from elc_audit_engine.rule_repository.errors import RuleRepositoryError
from elc_audit_engine.rule_repository.models import RuleResult

from .evidence import build_evidence_blocks
from .judger import JudgeFn, create_judger
from .models import (
    SUPPORT_NONE,
    SUPPORT_WEAK,
    CandidateNarrative,
    CaseComparisonResult,
    CheckItem,
    Judgment,
    OrderJudgment,
    VERDICT_MANUAL,
)
from .narratives import NarrativeFn, create_generator
from .support import classify_support

RuleLookupFn = Callable[[str], RuleResult]


def _to_check_item(rule: RuleResult) -> CheckItem:
    rule_text = rule.article_full_text or rule.payment_text or ""
    # CheckItem.rule_source 值域為 csv/docx/unknown（B-IN-13）：原本 article_source
    # 為空時退回 rule.source（payment/drug），兩種值域混在同一欄位。
    if rule.article_full_text:
        rule_source = rule.article_source or "unknown"
    elif rule.payment_text:
        rule_source = "csv"
    else:
        rule_source = "unknown"
    return CheckItem(
        rule_text=rule_text,
        rule_source=rule_source,
        rule_location=rule.article_location,
    )


def _case_visit_date(case: SubmissionCase) -> date | None:
    """SubmissionCase.visit_date（民國 7 碼原樣，或 API 帶入的 ISO）→ date。"""
    raw = (case.visit_date or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        iso = parse_flexible_date(raw)
        return date.fromisoformat(iso) if iso else None


def compare_case(
    case: SubmissionCase,
    soap_doc: SOAPDocument | None,
    timeline: PatientTimeline | None,
    *,
    rule_lookup: RuleLookupFn | None = None,
    judge_fn: JudgeFn | None = None,
    narrative_fn: NarrativeFn | None = None,
) -> CaseComparisonResult:
    """對單一案件執行三方比對（Phase 5 單一入口）。

    Args:
        case: 申報案件（SubmissionCase，Phase 3 輸出）。
        soap_doc: 當次 SOAP 分段結果；None 表示無 SOAP 資料。
        timeline: 半年病史時間軸；None 表示病歷缺席（C5 降級，
            只用當次 SOAP，結果 records_degraded=True）。
        rule_lookup: 規則查詢函式，預設 `get_rule`（可注入測試替身）。
        judge_fn: 判定函式 `(check_item, evidence) -> Judgment`，
            預設 LLMJudger（可注入替身，D-08）。
        narrative_fn: 候選補強生成函式
            `(check_item, evidence, support_level) -> list[CandidateNarrative]`，
            預設 LLMNarrativeGenerator（可注入替身）。

    Returns:
        CaseComparisonResult：逐醫令判定＋三級分類＋候選補強。

    Raises:
        RuleRepositoryError: 規則庫 DB 故障（P0-2：infra 故障不得吞成
            「查無規則」，由呼叫端決定如何向使用者呈現）。
    """
    lookup = rule_lookup or get_rule
    judge = create_judger(judge_fn)
    generate = create_generator(narrative_fn)

    evidence = build_evidence_blocks(case, soap_doc, timeline)
    visit_date = _case_visit_date(case)

    order_judgments: list[OrderJudgment] = []
    unknown_orders: list[str] = []
    manual_review_orders: list[str] = []

    for order in case.orders:
        code = (order.code or "").strip()
        if not code:
            # 不靜默略過（B-WR-05）：報告上必須看得出有一筆醫令未被審查。
            order_judgments.append(
                OrderJudgment(
                    order_code="",
                    order_seq=order.seq,
                    rule_found=False,
                    note="醫令代碼缺漏，建議人工查核",
                )
            )
            unknown_orders.append("")
            continue

        rule = lookup(code)  # RuleRepositoryError 穿透（D-06）
        if not rule.found:
            order_judgments.append(
                OrderJudgment(
                    order_code=code,
                    order_seq=order.seq,
                    rule_found=False,
                    note="查無規則依據，建議人工查核",
                )
            )
            unknown_orders.append(code)
            continue

        check_item = _to_check_item(rule)
        if visit_date is not None and is_effective_on(rule, visit_date) is False:
            # 規則在就醫日不在生效期間（B-WR-07）：不得拿失效／未生效規則判定。
            judgment = Judgment(
                verdict=VERDICT_MANUAL,
                quote="",
                reason=(
                    f"規則生效期間 {rule.effective_from or '—'}～{rule.effective_to or '—'} "
                    f"不含就醫日 {visit_date.isoformat()}，改待人工"
                ),
            )
        elif not check_item.rule_text.strip():
            # 規則全文缺漏時不送 LLM（B-WR-06）：沒有要求可比對，任何判定都無意義。
            judgment = Judgment(
                verdict=VERDICT_MANUAL, quote="", reason="規則全文缺漏，無法判定，改待人工"
            )
        else:
            judgment = judge(check_item, evidence)
        support_level, manual = classify_support([judgment])

        narratives: list[CandidateNarrative] = []
        narrative_error = False
        if support_level in (SUPPORT_WEAK, SUPPORT_NONE):
            # support_level=None（全部待人工，P1-1）不生成候選補強：判定
            # 階段的 LLM 已失敗，補強階段沒有可靠的缺口可寫，再呼叫一次
            # 只會是注定失敗的重試，且會讓「待判定」看起來像有具體缺漏。
            try:
                narratives = generate(check_item, evidence, support_level)
            except Exception:  # 生成失敗 ≠ 沒有建議（B-WR-10）
                narratives = []
                narrative_error = True

        order_judgments.append(
            OrderJudgment(
                order_code=code,
                order_seq=order.seq,
                rule_found=True,
                rule_source=rule.source,
                check_item=check_item,
                judgment=judgment,
                support_level=support_level,
                manual_review=manual,
                narratives=tuple(narratives),
                narrative_error=narrative_error,
            )
        )
        if manual:
            manual_review_orders.append(code)

    return CaseComparisonResult(
        case_record_no=case.record_no or "",
        order_judgments=tuple(order_judgments),
        records_degraded=timeline is None,
        unknown_orders=tuple(unknown_orders),
        manual_review_orders=tuple(manual_review_orders),
    )
