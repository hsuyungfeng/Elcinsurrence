"""給付規定區塊的共用判斷與標記（月審預審報告與二／三階審查報告共用）。

報表有兩條渲染路徑（`monthly_report_html._rule_fulltext_html` 與
`report_renderer._case_body_html` / `_section_rule`），折疊區的 wrapper 與標籤各自不同，
但「哪一段是 payment_text」與「上方自動展開的 payment_text 框」必須完全一致，
否則兩份報表會出現不同的展開行為。此模組只集中這兩個共通部分。
"""

from __future__ import annotations

from html import escape

PAYMENT_TITLE = "📜 給付規定（payment_text）"

# 以 label 辨識 payment_text 的字串（相容舊資料：RuleBlock 未設 is_payment_text 旗標時）
_PAYMENT_LABELS = ("給付規定（payment_text）", "payment_text")


def is_payment_text(name_or_label: str, flagged: bool = False) -> bool:
    """判斷一段規則文字是否為 payment_text。

    Args:
        name_or_label: 來源欄位名（月審 `source_texts`，如 `payment_text`）或顯示標籤（二／三階 `RuleBlock.label`）。
        flagged: 呼叫端已明確標記為 payment_text（`RuleBlock.is_payment_text`）。
    """
    return flagged or name_or_label in _PAYMENT_LABELS


def payment_box_html(text: str) -> str:
    """上方自動展開的 payment_text 框。呼叫端需先去除空白並確認非空。"""
    return (
        f'<div class="rule-payment">'
        f'<div class="rule-payment-title">{PAYMENT_TITLE}</div>'
        f'<div class="rule-payment-text">{escape(text)}</div>'
        f"</div>"
    )
