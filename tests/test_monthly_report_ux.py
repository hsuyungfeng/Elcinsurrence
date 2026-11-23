"""當月申報預審與工作台 UX 改進回歸測試：
1. 主診斷代碼中文映射（S6702XA -> 左手拇指壓傷，初期就診）。
2. 完整給付規定條文：給付規定（payment_text）預設展開顯示；條文全文（article_full_text）維持可點擊折疊。
3. 工作台分頁順序重排：1. 當月申報預審、2. 抽樣事前預審、3. 核減事後申復。
4. 左側列表欄位寬度縮小至 280px。
"""

from __future__ import annotations


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
    from tests.workbench_source import read_workbench_source
    html = read_workbench_source()
    # 左側欄寬度由 CSS 變數 --sidebar-width 控制（Phase 23 縮半為 140px）
    assert "--sidebar-width: 140px;" in html
    assert "grid-template-columns: var(--sidebar-width) 1fr;" in html
    # 工作台分頁按鈕順序：1. 當月申報檔預審在最前
    pos_m = html.find("id=\"tabMode3\"")
    pos_s = html.find("id=\"tabMode1\"")
    pos_a = html.find("id=\"tabMode2\"")
    assert pos_m != -1 and pos_s != -1 and pos_a != -1
    assert pos_m < pos_s < pos_a, "按鈕順序應為 tabMode3 (當月申報) -> tabMode1 (抽樣事前) -> tabMode2 (核減事後)"
    # 初始化預設進入 soap (Phase 31+) 或 monthly
    assert "switchWorkflowMode('soap')" in html or "switchWorkflowMode('monthly')" in html


def test_payment_text_summary_is_concise_and_distinct_from_fulltext():
    """給付規定（payment_text）預覽區必須簡潔，不可與下方完整給付規定條文相同。"""
    import re
    from elc_audit_engine.services.rule_summary import summarize_payment_text

    full_62010c = (
        "(手術)62010C - 臉部以外皮膚及皮下腫瘤摘除術－小於二公分 審查原則：(2025-01-01) 版 1.0\n\n"
        "1. **申報條件**\n"
        "   - 病患於面部以外部位，經臨床檢查、影像或病理確診為皮膚或皮下腫瘤，腫瘤直徑＜2 cm。\n"
        "   - 必須為惡性腫瘤（或高度懷疑惡性）或因病理風險需完全切除。\n\n"
        "2. **應檢附文件**\n"
        "   - 病患手術同意書（含麻醉同意）。\n"
        "   - 具體手術紀錄表（含腫瘤大小、部位、切除方式、邊緣深度）。\n"
        "   - 病理報告（含腫瘤類型、大小、邊緣狀態、分級）。\n\n"
        "3. **重複申報限制**\n"
        "   - 同一病患於同一腫瘤部位，若已於 30 天內完成本項目，不能再次申報。\n\n"
        "> **備註**：以上審查原則依據官方公告。"
    )
    summary = summarize_payment_text(full_62010c)
    assert summary is not None
    assert summary != full_62010c
    assert len(summary) < 200
    assert "**" not in summary
    assert "申報條件" in summary and "應檢附文件" in summary

    case = CaseAudit(
        case_id="MON-62010c",
        batch="MONTHLY-202307",
        case_seq="27",
        department="03",
        doctor_code="D1",
        visit_date="1120708",
        primary_diagnosis="D234",
        secondary_diagnoses=(),
        total_points="17533",
        findings=(
            OrderFinding(
                order_seq="1",
                code="62010C",
                category="2",
                unit_price="1623",
                points="4966",
                flags=("points_over_350",),
                rule_status=STATUS_RESTRICTION,
                rule_name="臉部以外皮膚及皮下腫瘤摘除術",
                source_texts=(("payment_text", full_62010c),),
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
    m_pay = re.search(r'<div class="rule-payment-text">(.*?)</div>', html, re.S)
    m_full = re.search(r'<pre class="rule-text">(.*?)</pre>', html, re.S)
    assert m_pay and m_full
    assert m_pay.group(1) != m_full.group(1)
    assert len(m_pay.group(1)) < len(m_full.group(1)) // 2

    # 單句極短文字不可在兩處重複顯示
    assert summarize_payment_text("一般說明文字。") is None
