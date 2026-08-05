"""病歷補強報告生成器（Phase 6，純渲染層）。

把 Phase 5 的 `CaseComparisonResult` 渲染成 Markdown checkbox 逐條審
報告（D8：Phase 1 為 Markdown checkbox 檢核表），供醫師逐條審核（D9）。

純函式核心：`render_report(comparison) -> str`；檔案輸出 `write_report`
為薄包裝（06-CONTEXT.md D-05/D-06）。
"""

from __future__ import annotations

import os

from elc_audit_engine.comparator.models import (
    SUPPORT_NONE,
    SUPPORT_SUFFICIENT,
    SUPPORT_WEAK,
    VERDICT_MANUAL,
    VERDICT_PARTIAL,
    VERDICT_SUPPORTED,
    VERDICT_UNSUPPORTED,
    CaseComparisonResult,
)
from elc_audit_engine.safe_paths import safe_filename

from .tracking import render_tracking

_VERDICT_LABELS = {
    VERDICT_SUPPORTED: "支持",
    VERDICT_PARTIAL: "部分支持",
    VERDICT_UNSUPPORTED: "無記載",
    VERDICT_MANUAL: "待人工",
}

_SUPPORT_BADGES = {
    SUPPORT_SUFFICIENT: "✅ 充分",
    SUPPORT_WEAK: "⚠️ 薄弱",
    SUPPORT_NONE: "❌ 裸奔",
}


def _support_badge(level: str | None, rule_found: bool = False) -> str:
    """支持度徽章。

    level=None 有兩種成因，必須分辨（P1-1）：
    - rule_found=False：規則庫查無此醫令 →「查無規則」
    - rule_found=True：規則有、但判定全部待人工（LLM 故障降級）
      →「待判定」。絕不可顯示為裸奔或查無規則——兩者都會讓醫師
      誤以為已完成判定。
    """
    if level is None:
        return "⏳ 待判定（系統未能判定，請人工複核）" if rule_found else "❓ 查無規則"
    return _SUPPORT_BADGES.get(level, level)


def _timeline_summary(comparison: CaseComparisonResult) -> list[str]:
    """半年病史摘要區（timeline 存在時由 comparison 提供者帶入）。"""
    # CaseComparisonResult 目前未攜帶 timeline 明細；摘要區由呼叫端
    # 以 render_timeline_summary(timeline) 另行渲染，此處僅留佔位。
    return []


def render_timeline_summary(timeline) -> str:
    """渲染半年病史摘要（供報告「半年病史摘要」區塊使用）。

    Args:
        timeline: PatientTimeline（Phase 4）；None 時回傳空字串。

    Returns:
        Markdown 摘要文字（四類筆數＋最近 3 筆），無 timeline 時空字串。
    """
    if timeline is None:
        return ""
    lines = ["## 半年病史摘要", ""]
    counts = {
        "就診": len(timeline.visits),
        "檢驗": len(timeline.labs),
        "檢查": len(timeline.exams),
        "影像": len(timeline.imaging),
    }
    lines.append(
        "時間窗：" + " ~ ".join(str(d) for d in (timeline.window_start, timeline.window_end))
    )
    lines.append("、".join(f"{k} {v} 筆" for k, v in counts.items()))
    lines.append("")
    for record in list(timeline.visits)[-3:]:
        lines.append(f"- 就診 {record.date} {record.clinic}：{record.soap_text[:60] or '（無 SOAP）'}")
    for record in list(timeline.labs)[-3:]:
        lines.append(f"- 檢驗 {record.date}：{record.test_name} = {record.result} {record.unit}")
    for record in list(timeline.exams)[-3:]:
        lines.append(f"- 檢查 {record.date}：{record.exam_name}：{record.finding[:60]}")
    for record in list(timeline.imaging)[-3:]:
        lines.append(
            f"- 影像 {record.date}：{record.modality} {record.body_part}："
            f"{record.impression[:60]}"
        )
    lines.append("")
    return "\n".join(lines)


def render_report(comparison: CaseComparisonResult, timeline=None) -> str:
    """渲染病歷補強報告（Markdown checkbox 逐條審格式，D-01）。

    Args:
        comparison: Phase 5 的比對結果。
        timeline: PatientTimeline（可選）；提供時報告含半年病史摘要區。

    Returns:
        Markdown 報告文字。
    """
    lines: list[str] = []
    lines.append("# 病歷補強報告")
    lines.append("")
    lines.append(f"- 病歷號：`{comparison.case_record_no or '（未知）'}`")
    lines.append("")

    # 警告區（D-01）
    warnings: list[str] = []
    if comparison.records_degraded:
        warnings.append("⚠ 本報告未含病史佐證（病歷缺席，僅以當次 SOAP 判定）")
    if comparison.unknown_orders:
        warnings.append(
            "⚠ 未知醫令（查無規則依據，建議人工查核）："
            + "、".join(f"`{c}`" for c in comparison.unknown_orders)
        )
    if comparison.manual_review_orders:
        warnings.append(
            "⚠ 待人工複核醫令（LLM 判定失敗）："
            + "、".join(f"`{c}`" for c in comparison.manual_review_orders)
        )
    if warnings:
        lines.append("## ⚠ 注意事項")
        lines.append("")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    # 逐醫令區塊
    lines.append("## 逐醫令支持度")
    lines.append("")
    for oj in comparison.order_judgments:
        lines.append(f"### {oj.order_code}" + (f"（序 {oj.order_seq}）" if oj.order_seq else ""))
        lines.append("")
        lines.append(f"- 支持度：{_support_badge(oj.support_level, oj.rule_found)}")
        if oj.judgment is not None:
            lines.append(
                f"- 判定：{_VERDICT_LABELS.get(oj.judgment.verdict, oj.judgment.verdict)}"
            )
            if oj.judgment.quote:
                lines.append(f"  - 引用原文：> {oj.judgment.quote}")
            if oj.judgment.reason:
                lines.append(f"  - 理由：{oj.judgment.reason}")
        if oj.check_item is not None and oj.check_item.rule_location:
            lines.append(f"- 規則出處：`{oj.check_item.rule_location}`")
        if oj.note:
            lines.append(f"- 備註：{oj.note}")
        if oj.narratives:
            lines.append("- 候選補強敘述（醫師勾選／編輯）：")
            for n in oj.narratives:
                loc = f"（{n.rule_location}）" if n.rule_location else ""
                suffix = "〔提示型〕" if n.prompt_only else ""
                lines.append(f"  - [ ] {n.text}{suffix}{loc}")
        lines.append("")

    # 半年病史摘要區
    summary = render_timeline_summary(timeline)
    if summary:
        lines.append(summary)

    return "\n".join(lines)


def write_report(
    output_dir: str | os.PathLike[str],
    case_record_no: str,
    comparison: CaseComparisonResult,
    decisions: dict | None = None,
    *,
    timeline=None,
    reviewed_at: str | None = None,
) -> tuple[str, str]:
    """寫出病歷補強報告.md 與審核軌跡.json（D-05，薄包裝）。

    Args:
        output_dir: 輸出目錄（可注入；預設由呼叫端傳 config.settings.OUTPUT_DIR）。
        case_record_no: 病歷號（檔名的一部分）。
        comparison: Phase 5 比對結果。
        decisions: 醫師審核結果（選用，見 tracking.render_tracking）。
        timeline: PatientTimeline（可選）。
        reviewed_at: 審核時間戳（ISO，選用）。

    Returns:
        (報告路徑, 軌跡路徑)。
    """
    # P1-3：case_record_no 進檔名，未校驗會造成寫入型路徑穿越。
    safe_no = safe_filename(case_record_no, "case_record_no")
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, f"病歷補強報告_{safe_no}.md")
    tracking_path = os.path.join(output_dir, f"審核軌跡_{safe_no}.json")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(render_report(comparison, timeline=timeline))

    with open(tracking_path, "w", encoding="utf-8") as f:
        f.write(
            render_tracking(comparison, decisions=decisions, reviewed_at=reviewed_at)
        )

    return report_path, tracking_path
