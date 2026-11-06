"""當月申報預審與工作台 UX 改進回歸測試：
1. 主診斷代碼中文映射（S6702XA -> 左手拇指壓傷，初期就診）。
2. 完整給付規定條文：給付規定（payment_text）預設展開顯示；條文全文（article_full_text）維持可點擊折疊。
3. 工作台分頁順序重排：1. 當月申報預審、2. 抽樣事前預審、3. 核減事後申復。
4. 左側列表欄位寬度縮小至 280px。
"""

from __future__ import annotations

from pathlib import Path

from elc_audit_engine.monthly_audit import (
    BatchAudit,
    CaseAudit,
    OrderFinding,
    STATUS_RESTRICTION,
)
from elc_audit_engine.monthly_report_html import render_batch_report_html
from elc_audit_engine.rule_repository.icd_titles import get_icd_chinese_title


def test_icd_chinese_title_lookup():
    # S6702XA 完全符合
    assert get_icd_chinese_title("S6702XA") == "左手拇指壓傷，初期就診"
    assert get_icd_chinese_title("S67.02XA") == "左手拇指壓傷，初期就診"
    assert get_icd_chinese_title("S90221A") == "右腳大腳趾挫傷併指甲受損，初期就診"
    assert get_icd_chinese_title("L720") == "表皮樣囊腫 (粉瘤)"
    # 未知代碼回退 None
    assert get_icd_chinese_title("UNKNOWN_CODE") is None
    assert get_icd_chinese_title(None) is None


def test_case_header_shows_icd_chinese_title():
    case = CaseAudit(
        case_id="MON-test",
        batch="MONTHLY-202307",
        case_seq="1",
        department="03",
        doctor_code="D1",
        visit_date="1120718",
        primary_diagnosis="S6702XA",
        secondary_diagnoses=(),
        patient_id="A123456789",
        patient_name="張三",
        birth_date="0500101",
        total_points="1500",
        findings=(
            OrderFinding(
                order_seq="1",
                code="64140C",
                category="2",
                unit_price="521",
                points="521",
                flags=("points_over_350",),
                rule_status=STATUS_RESTRICTION,
                rule_name="甲床與手指重建術",
                source_texts=(
                    ("payment_text", "限拇指壓傷或嚴重損傷使用。需檢附術前術後照片"),
                    ("article_full_text", "第一條 手術費用支付標準..."),
                ),
            ),
        ),
    )
    batch = BatchAudit(
        batch="MONTHLY-202307",
        cases_total=1,
        cases=(case,),
        report={
            "totals": {"cases_flagged": 1, "findings": 1, "rule_status": {STATUS_RESTRICTION: 1}},
            "by_department": {"03": {"cases_flagged": 1, "findings": 1, "rule_status": {STATUS_RESTRICTION: 1}}},
            "by_doctor": {"D1": {"cases_flagged": 1, "findings": 1, "rule_status": {STATUS_RESTRICTION: 1}}},
        },
    )
    html = render_batch_report_html(batch)
    # 檢查主診斷是否附帶中文名稱
    assert "S6702XA (左手拇指壓傷，初期就診)" in html
    # 檢查給付規定（payment_text）直接展開顯示
    assert "📜 給付規定（payment_text）" in html
    assert "限拇指壓傷或嚴重損傷使用" in html
    # 檢查條文全文可折疊 details
    assert '<details class="rule-fulltext">' in html
    assert "📜 檢視完整給付規定條文" in html


def test_index_html_tab_order_and_sidebar_width():
    html = Path("static/index.html").read_text(encoding="utf-8")
    # 左側欄寬度由 CSS 變數 --sidebar-width 控制（Phase 23 縮半為 140px）
    assert "--sidebar-width: 140px;" in html
    assert "grid-template-columns: var(--sidebar-width) 1fr;" in html
    # 工作台分頁按鈕順序：1. 當月申報檔預審在最前
    pos_m = html.find("id=\"tabMode3\"")
    pos_s = html.find("id=\"tabMode1\"")
    pos_a = html.find("id=\"tabMode2\"")
    assert pos_m != -1 and pos_s != -1 and pos_a != -1
    assert pos_m < pos_s < pos_a, "按鈕順序應為 tabMode3 (當月申報) -> tabMode1 (抽樣事前) -> tabMode2 (核減事後)"
    # 初始化預設進入 monthly
    assert "switchWorkflowMode('monthly')" in html
