"""Phase 38 驗收（Tester）：62010C 以「真實」正式 DB 資料驗證 HTML 渲染。

讀取 data/db/rules.sqlite3（唯讀 get_rule）的 62010C 規則，呼叫
  - render_batch_report_html        （Stage 1 月審報告）
  - render_aggregated_review_html   （Stage 2/3 統一報告）
並驗證使用者驗收標準：

(a) 📜 給付規定（payment_text）區塊「完整」包含 payment_text 原文
    —— 脂肪瘤＋痣切除兩大段俱在，且無 '…'（或 '...'）截斷。
(b) 📜 檢視完整給付規定條文折疊區（<details class="rule-fulltext">）
    「徹底排除」payment_text，僅保留 article_full_text 條文全文。

本測試只唯讀正式 DB，絕不寫入。可：
  uv run pytest tests/test_62010c_render_verify.py -v   （pytest）
  uv run python tests/test_62010c_render_verify.py      （standalone 報告）
"""

from __future__ import annotations

import sys
from pathlib import Path

# standalone 執行時確保 repo root 在 sys.path（pytest 環境由 tests/conftest.py 處理）
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import html
import re

from elc_audit_engine.monthly_audit import BatchAudit, CaseAudit, OrderFinding, STATUS_RESTRICTION
from elc_audit_engine.monthly_report_html import render_batch_report_html
from elc_audit_engine.rule_repository import get_rule
from elc_audit_engine.services.report_renderer import (
    ReviewCaseView,
    RuleBlock,
    render_aggregated_review_html,
)
from elc_audit_engine.services.rule_summary import summarize_payment_text

DB = _PROJECT_ROOT / "data" / "db" / "rules.sqlite3"

# 僅存在於 payment_text、不在 article_full_text 的「payment 專屬標記」（全/半形標點差異）。
# 用於證明折疊區若含這些字樣即代表 payment_text 滲漏。
PAY_SPECIFIC_MARKERS = [
    "以本項目（62010C）申報",
    "（但先天性黑色素細胞痣不在此限）",
    "62010C及相關病理費用",
    "超過10公分以上，得以75602C（腹壁腫瘤切除術，良性）項申報",
]

PAYMENT_BLOCK_RE = re.compile(r'<div class="rule-payment-text">(.*?)</div>', re.S)
DETAILS_RE = re.compile(r'<details class="rule-fulltext">.*?</details>', re.S)


def _load_rule():
    rule = get_rule("62010C", db_path=str(DB))
    assert rule.payment_text is not None, "62010C payment_text 不存在"
    assert rule.article_full_text is not None, "62010C article_full_text 不存在"
    return rule


def _texts(rule) -> tuple[str, str]:
    """回傳 (payment_text, article_full_text) 的非 None 字串。"""
    pay, art = rule.payment_text, rule.article_full_text
    assert isinstance(pay, str) and isinstance(art, str)
    return pay, art


def _build_batch(rule, pay: str, art: str) -> BatchAudit:
    finding = OrderFinding(
        order_seq="1",
        code=rule.code,
        category="2",
        unit_price=rule.unit_price or "",
        points="1623",
        flags=("points_over_350",),
        rule_status=STATUS_RESTRICTION,
        rule_name=rule.name or "皮下腫瘤摘除術",
        source_texts=(("payment_text", pay), ("article_full_text", art)),
        article_location=rule.article_location,
    )
    case = CaseAudit(
        case_id="VRFY-62010",
        batch="VERIFY-202611",
        case_seq="1",
        department="03",
        doctor_code="D1",
        visit_date="1151123",
        primary_diagnosis="D234",
        secondary_diagnoses=(),
        total_points="4500",
        findings=(finding,),
    )
    return BatchAudit(
        batch="VERIFY-202611",
        cases_total=1,
        cases=(case,),
        report={
            "totals": {"cases_flagged": 1, "findings": 1, "rule_status": {STATUS_RESTRICTION: 1}},
            "by_department": {"03": {"cases_flagged": 1, "findings": 1, "rule_status": {STATUS_RESTRICTION: 1}}},
            "by_doctor": {"D1": {"cases_flagged": 1, "findings": 1, "rule_status": {STATUS_RESTRICTION: 1}}},
        },
    )


def _build_view(rule, pay: str, art: str) -> ReviewCaseView:
    return ReviewCaseView(
        case_id="VRFY-62010",
        stage=2,
        header={"醫令": rule.code},
        kpis={},
        rules=(
            RuleBlock(label="給付規定（payment_text）", text=pay, is_payment_text=True),
            RuleBlock(label="條文全文（article_full_text）", text=art, location=rule.article_location),
        ),
        order_code=rule.code,
        order_name=rule.name or "皮下腫瘤摘除術",
    )


def _assert_payment_block(html_doc: str, payment_text: str, label: str) -> str:
    """(a) 驗證 payment 區塊完整展開原文、含兩大段、無截斷。回傳 unescape 後的內容。"""
    m = PAYMENT_BLOCK_RE.search(html_doc)
    assert m, f"{label}: 找不到 <div class=\"rule-payment-text\">"
    pay = html.unescape(m.group(1))
    assert pay == payment_text.strip(), f"{label}: payment 區塊內容 ≠ payment_text 完整原文"
    assert "脂肪瘤" in pay and "脂肪瘤如在皮下" in pay, f"{label}: 缺脂肪瘤段落"
    assert "痣切除" in pay and "痣切除於病歷中未見惡性症候記載者" in pay, f"{label}: 缺痣切除段落"
    assert "…" not in pay, f"{label}: payment 區塊含 '…' 截斷標記"
    assert "..." not in pay, f"{label}: payment 區塊含 '...' 截斷標記"
    return pay


def _assert_details_block(html_doc: str, article_full_text: str, payment_text: str, label: str) -> str:
    """(b) 驗證折疊區僅含 article_full_text、徹底排除 payment_text。回傳 unescape 後的內容。"""
    m = DETAILS_RE.search(html_doc)
    assert m, f"{label}: 找不到 <details class=\"rule-fulltext\">"
    details = m.group(0)
    details_text = html.unescape(details)
    assert article_full_text in details_text, f"{label}: article_full_text 未完整收錄於折疊區"
    assert payment_text not in details, f"{label}: 折疊區含 raw payment_text"
    assert payment_text not in details_text, f"{label}: 折疊區含 payment_text"
    for marker in PAY_SPECIFIC_MARKERS:
        assert marker not in details_text, f"{label}: payment 專屬標記 {marker!r} 滲漏進折疊區"
    return details


def _assert_layout_order(html_doc: str, label: str) -> None:
    """payment 區塊須先於折疊區出現；折疊區預設不得 open。"""
    assert html_doc.index('<div class="rule-payment">') < html_doc.index('<details class="rule-fulltext">'), (
        f"{label}: payment 區塊未位於折疊區之前"
    )
    assert '<details class="rule-fulltext" open' not in html_doc, f"{label}: 折疊區預設為展開（open）"


def test_62010c_real_db_stage1_batch_report():
    rule = _load_rule()
    pay, art = _texts(rule)
    assert "脂肪瘤" in pay and "痣切除" in pay
    assert len(art) > 200
    html_doc = render_batch_report_html(_build_batch(rule, pay, art))
    _assert_payment_block(html_doc, pay, "Stage1")
    _assert_details_block(html_doc, art, pay, "Stage1")
    _assert_layout_order(html_doc, "Stage1")


def test_62010c_real_db_stage23_aggregated_review():
    rule = _load_rule()
    pay, art = _texts(rule)
    html_doc = render_aggregated_review_html([_build_view(rule, pay, art)], title="62010C 驗證")
    _assert_payment_block(html_doc, pay, "Stage23")
    _assert_details_block(html_doc, art, pay, "Stage23")
    _assert_layout_order(html_doc, "Stage23")


def _report() -> None:
    rule = _load_rule()
    pay, art = _texts(rule)
    print("=" * 70)
    print(f"62010C 真實 DB 渲染驗證  （db={DB}）")
    print("=" * 70)
    print(f"code                : {rule.code}")
    print(f"rule_name           : {rule.name}")
    print(f"payment_text  length: {len(pay)} 字")
    print(f"article_full_text   : {len(art)} 字")
    print(f"payment 含 脂肪瘤/痣切除: {'脂肪瘤' in pay} / {'痣切除' in pay}")
    summ = summarize_payment_text(pay)
    if summ is not None:
        print(f"summarize_payment_text: len={len(summ)}（僅供參考；報表不使用此截斷版）")
    print("-" * 70)

    for label, html_doc in (
        ("Stage1 render_batch_report_html", render_batch_report_html(_build_batch(rule, pay, art))),
        ("Stage2/3 render_aggregated_review_html", render_aggregated_review_html([_build_view(rule, pay, art)], title="x")),
    ):
        _assert_payment_block(html_doc, pay, label)
        det = _assert_details_block(html_doc, art, pay, label)
        _assert_layout_order(html_doc, label)
        print(f"[PASS] {label}")
        print("       (a) payment 區塊 == 完整原文：True；脂肪瘤+痣切除兩大段俱在；無 '…' 截斷")
        print("       (b) 折疊區含 article_full_text：True；payment_text/專屬標記皆已排除")
        print(f"           折疊區含『官方條文全文』出處標頭：{'官方條文全文' in html.unescape(det)}")
    print("=" * 70)
    print("ALL CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    _report()
