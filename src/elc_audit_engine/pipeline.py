"""端到端管線（Phase 8）：比對 → 病歷補強報告 → 申復草稿 的單一入口。

`run_case_pipeline` 把 Phase 5（比對）→ Phase 6（補強報告＋審核軌跡）→
Phase 7（申復草稿）接成可測試、可替換的一條管線（C6-4 端到端案例的
執行面；C6-5 真實樣本回放時只換注入層，不動管線）。

注入點（08-CONTEXT D-03，皆可替換）：
- rule_lookup/judge_fn/narrative_fn → compare_case（D-08 替身，零 LLM）
- decisions → 醫師審核結果（Phase 6 軌跡輸入）
- deduction_records → 核減明細列（Phase 3 輸出；實體檔到手後直接餵入）

錯誤處理：單筆核減醫令的規則查詢故障（RuleRepositoryError）不阻斷整案
（C5 精神），該筆降級為「查無規則」並保留於草稿；LLM 判定/補強失敗
由 compare_case 降級「待人工」（C5），管線不吞不遮。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Sequence

from elc_audit_engine.comparator import (
    CaseComparisonResult,
    compare_case,
)
from elc_audit_engine.comparator.judger import JudgeFn
from elc_audit_engine.generators import (
    AppealDraft,
    adopted_narratives_from_tracking,
    build_appeal_draft,
    render_tracking,
    write_appeal,
    write_report,
)
from elc_audit_engine.parsers.models import SOAPDocument, SubmissionCase
from elc_audit_engine.record_aggregator.models import PatientTimeline
from elc_audit_engine.rule_repository.errors import RuleRepositoryError

RuleLookupFn = Callable[[str], object]
NarrativeFn = Callable[[object, str, str], list]


@dataclass(frozen=True)
class PipelineResult:
    """端到端管線輸出。

    Attributes:
        comparison: Phase 5 比對結果（報告內容來源）。
        report_path: 病歷補強報告.md 路徑。
        tracking_path: 審核軌跡.json 路徑。
        appeal_paths: 逐筆核減醫令的 (申復草稿.md, appeal.json) 路徑。
        appeal_drafts: 逐筆核減醫令的 AppealDraft（與 appeal_paths 同序）。
    """

    comparison: CaseComparisonResult
    report_path: str
    tracking_path: str
    appeal_paths: tuple[tuple[str, str], ...] = ()
    appeal_drafts: tuple[AppealDraft, ...] = ()


def _rule_text_for(rule: object) -> tuple[str | None, str | None]:
    """從 RuleResult 取出規則全文＋出處；查無（found=False）回傳 (None, None)。"""
    if rule is None:
        return None, None
    found = getattr(rule, "found", True)
    if found is False:
        return None, None
    text = getattr(rule, "article_full_text", None) or getattr(rule, "payment_text", None)
    return text, getattr(rule, "article_location", None)


def run_case_pipeline(
    case: SubmissionCase,
    soap_doc: SOAPDocument | None,
    timeline: PatientTimeline | None,
    deduction_records: Sequence,
    *,
    output_dir: str | os.PathLike[str],
    rule_lookup: RuleLookupFn | None = None,
    judge_fn: JudgeFn | None = None,
    narrative_fn: NarrativeFn | None = None,
    decisions: dict | None = None,
    reviewed_at: str | None = None,
    appeal_options: dict | None = None,
) -> PipelineResult:
    """執行單一案件的完整管線（C6-4/C6-5 共用入口）。

    Args:
        case: 申報案件（SubmissionCase；含病歷號/醫令）。
        soap_doc: 當次 SOAP 分段結果（可 None）。
        timeline: 半年病史時間軸（None＝病歷缺席降級）。
        deduction_records: 核減明細列（DeductionRecord，Phase 3）；逐筆
            獨立生成申復草稿（D10）。
        output_dir: 輸出目錄（寫 病歷補強報告/審核軌跡/申復草稿/appeal）。
        rule_lookup: 規則查詢函式，預設 get_rule（可注入替身）。
        judge_fn: 判定函式（可注入替身，D-08）。
        narrative_fn: 候選補強生成函式（可注入替身）。
        decisions: 醫師審核結果 {narrative_index: (status, edited_text)}；
            決定軌跡狀態與 appeal ④ 採用敘述。
        reviewed_at: 審核時間戳（ISO，可注入固定時間）。
        appeal_options: 套用於所有核減醫令的選項 dict（is_appealing/
            claimed_points/has_attachment）；個別覆寫需求由呼叫端自行
            逐筆呼叫 build_appeal_draft（本入口維持簡單）。

    Returns:
        PipelineResult：comparison＋輸出檔案路徑＋逐筆 appeal 草稿。
    """
    os.makedirs(output_dir, exist_ok=True)

    # ① 比對（Phase 5）
    comparison = compare_case(
        case,
        soap_doc,
        timeline,
        rule_lookup=rule_lookup,
        judge_fn=judge_fn,
        narrative_fn=narrative_fn,
    )

    # ② 病歷補強報告＋審核軌跡（Phase 6）
    record_no = comparison.case_record_no or "unknown"
    report_path, tracking_path = write_report(
        output_dir,
        record_no,
        comparison,
        decisions=decisions,
        timeline=timeline,
        reviewed_at=reviewed_at,
    )
    tracking_text = render_tracking(
        comparison, decisions=decisions, reviewed_at=reviewed_at
    )
    adopted = adopted_narratives_from_tracking(tracking_text)

    # ③ 逐筆核減醫令 → 申復草稿（Phase 7，D10 每筆獨立）
    opts = appeal_options or {}
    seen: dict[str, int] = {}
    appeal_paths: list[tuple[str, str]] = []
    appeal_drafts: list[AppealDraft] = []

    for record in deduction_records:
        order_code = record.order_code or ""
        per_order = [
            e for e in adopted if not e.get("order_code") or e["order_code"] == order_code
        ]

        rule_text = rule_location = None
        if order_code:
            lookup = rule_lookup or _default_rule_lookup()
            try:
                rule = lookup(order_code)
            except RuleRepositoryError:
                # 單筆規則庫故障不阻斷整案（C5 精神）；降級為查無規則。
                rule = None
            rule_text, rule_location = _rule_text_for(rule)

        draft = build_appeal_draft(
            record,
            is_appealing=opts.get("is_appealing", True),
            claimed_points=opts.get("claimed_points"),
            timeline=timeline,
            rule_text=rule_text,
            rule_location=rule_location,
            evidence=per_order,
            has_attachment=opts.get("has_attachment", False),
        )

        # 同一流水號多筆核減醫令時，file_stem 加醫令碼避免覆寫（C7 保底）
        case_seq = record.case_seq or ""
        seen[case_seq] = seen.get(case_seq, 0) + 1
        file_stem = opts.get("file_stem")
        if file_stem is None and seen[case_seq] > 1:
            file_stem = f"{case_seq}_{order_code or 'x'}"
        md_path, json_path = write_appeal(
            output_dir, case_seq, draft, file_stem=file_stem
        )
        appeal_paths.append((md_path, json_path))
        appeal_drafts.append(draft)

    return PipelineResult(
        comparison=comparison,
        report_path=report_path,
        tracking_path=tracking_path,
        appeal_paths=tuple(appeal_paths),
        appeal_drafts=tuple(appeal_drafts),
    )


def _default_rule_lookup() -> RuleLookupFn:
    from elc_audit_engine.rule_repository import get_rule

    return get_rule
