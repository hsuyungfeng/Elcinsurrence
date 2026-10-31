"""Plan 18-02 測試骨架：第 2、3 階審查報告統一格式。

- 公開常數（區塊順序、階段標題）為一般測試。
- 渲染與建模流程為 strict xfail（raises=NotImplementedError）：實作完成後會變成
  XPASS 並使測試失敗，屆時移除 xfail 標記即可。
"""

from __future__ import annotations

import pytest

from elc_audit_engine import unified_review_report as report

pending_impl = pytest.mark.xfail(
    raises=NotImplementedError,
    strict=True,
    reason="Plan 18-02 尚未實作",
)


# ── 已實作：公開契約 ─────────────────────────────────────────


def test_section_order_matches_monthly_202307_layout():
    assert report.SECTION_ORDER == ("kpi", "header", "rule", "soap", "vault")


def test_stage_titles_cover_stage_2_and_3():
    assert set(report.STAGE_TITLES) == {2, 3}
    assert "抽審事前預審" in report.STAGE_TITLES[2]
    assert "核減事後申復" in report.STAGE_TITLES[3]


def test_review_case_view_defaults_to_no_soap_and_no_vault():
    view = report.ReviewCaseView(case_id="C-1", stage=2)
    assert view.soap is None
    assert view.soap_source == "none"
    assert view.vault_key is None
    assert view.vault_files == {}


# ── 待實作：建模與渲染（strict xfail） ───────────────────────


@pending_impl
def test_build_view_prefers_case_soap_over_template():
    report.build_review_case_view(
        2,
        "C-1",
        {"soap": "S: 主訴\nO: 數值\nA: 診斷\nP: 計畫"},
        soap_template={"s": "範本", "o": "", "a": "", "p": ""},
    )


@pending_impl
def test_build_view_falls_back_to_template_and_marks_source():
    view = report.build_review_case_view(
        3,
        "C-2",
        {},
        soap_template={"s": "範本主訴", "o": "範本數值", "a": "範本診斷", "p": "範本計畫"},
    )
    assert view.soap_source == "template"


@pending_impl
def test_render_escapes_external_text():
    view = report.ReviewCaseView(
        case_id="C-3",
        stage=2,
        header={"姓名": "<script>alert(1)</script>"},
    )
    html = report.render_unified_review_html(view)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


@pending_impl
def test_render_omits_empty_sections():
    view = report.ReviewCaseView(case_id="C-4", stage=2)
    html = report.render_unified_review_html(view)
    assert "佐證庫" not in html
    assert "SOAP" not in html


@pending_impl
def test_render_follows_section_order():
    view = report.ReviewCaseView(
        case_id="C-5",
        stage=3,
        kpis={"申復理由": 2},
        header={"就醫日": "20260715"},
        rules=(report.RuleBlock(label="給付規定", text="原文", is_payment_text=True),),
        soap={"s": "S", "o": "O", "a": "A", "p": "P"},
        vault_key="A123456789-2607",
        vault_files={"images": ("x.jpg",)},
    )
    html = report.render_unified_review_html(view)
    positions = [html.index(marker) for marker in ("申復理由", "就醫日", "原文", "SOAP", "A123456789-2607")]
    assert positions == sorted(positions)


@pending_impl
def test_stage_3_header_uses_stage_title():
    view = report.ReviewCaseView(case_id="C-6", stage=3)
    html = report.render_unified_review_html(view)
    assert report.STAGE_TITLES[3] in html
