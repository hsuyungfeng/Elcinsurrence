"""Plan 18-02：第 2、3 階審查報告統一格式（建模與 HTML 渲染）。"""

from __future__ import annotations

from elc_audit_engine import unified_review_report as report

# ── 公開契約 ─────────────────────────────────────────────────


def test_section_order_matches_monthly_202307_layout():
    assert report.SECTION_ORDER == (
        "warning", "kpi", "header", "rule", "soap", "lab", "cloud", "vault",
    )


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


# ── 建模 ─────────────────────────────────────────────────────


def test_build_view_prefers_case_soap_over_template():
    view = report.build_review_case_view(
        2,
        "C-1",
        {"soap": "S: 主訴\nO: 數值\nA: 診斷\nP: 計畫"},
        soap_template={"s": "範本", "o": "", "a": "", "p": ""},
    )
    assert view.soap_source == "case"
    assert view.soap == {"s": "主訴", "o": "數值", "a": "診斷", "p": "計畫"}


def test_build_view_falls_back_to_template_and_marks_source():
    view = report.build_review_case_view(
        3,
        "C-2",
        {},
        soap_template={"s": "範本主訴", "o": "範本數值", "a": "範本診斷", "p": "範本計畫"},
    )
    assert view.soap_source == "template"
    assert view.soap["p"] == "範本計畫"


def test_build_view_keeps_unmarked_soap_text_as_raw():
    view = report.build_review_case_view(2, "C-2b", {"soap": "沒有標記的一段病歷"})
    assert view.soap == {"raw": "沒有標記的一段病歷"}


def test_build_view_without_any_soap_source():
    view = report.build_review_case_view(2, "C-2c", {})
    assert view.soap is None
    assert view.soap_source == "none"


def test_header_labels_record_no_as_national_id():
    view = report.build_review_case_view(2, "C-2d", {"record_no": "L221543164"})
    assert view.header["身分證字號"] == "L221543164"
    assert "病歷號" not in view.header


def test_header_falls_back_to_patient_id_for_national_id():
    view = report.build_review_case_view(2, "C-2e", {"patient_id": "L221543164"})
    assert view.header["身分證字號"] == "L221543164"


def test_build_view_maps_vault_listing_and_counts_kpis():
    view = report.build_review_case_view(
        2,
        "C-3",
        {"record_no": "A123456789", "visit_date": "2026-07-15"},
        rules=(report.RuleBlock(label="給付規定", text="原文"),),
        vault_listing={"images": [{"filename": "a.jpg"}, {"filename": "b.jpg"}], "audio": []},
    )
    assert view.vault_files == {"images": ("a.jpg", "b.jpg")}
    assert view.vault_key == "A123456789-2607"
    assert view.kpis == {"給付規定段落": 1, "佐證檔案": 2}


# ── 渲染 ─────────────────────────────────────────────────────


def test_render_escapes_external_text():
    view = report.ReviewCaseView(
        case_id="C-3",
        stage=2,
        header={"姓名": "<script>alert(1)</script>"},
    )
    html = report.render_unified_review_html(view)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_omits_empty_sections():
    view = report.ReviewCaseView(case_id="C-4", stage=2)
    html = report.render_unified_review_html(view)
    assert "佐證庫" not in html
    assert "SOAP" not in html


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


def test_render_stage_3_uses_stage_title():
    view = report.ReviewCaseView(case_id="C-6", stage=3)
    html = report.render_unified_review_html(view)
    assert report.STAGE_TITLES[3] in html


def test_render_marks_template_soap_for_physician_review():
    view = report.ReviewCaseView(
        case_id="C-7",
        stage=2,
        soap={"s": "範本", "o": "", "a": "", "p": ""},
        soap_source="template",
    )
    html = report.render_unified_review_html(view)
    assert "須醫師審核" in html


def test_build_view_reads_warnings_labs_cloud_from_payload():
    payload = {
        "review": {"warnings": ["⚠ 本案未取得半年病史佐證（病歷缺席）。"]},
        "lab_results": [{"name": "HbA1c", "value": "8.5", "unit": "%"}, {"value": "x"}],
        "cloud_records": "  健保跨院病歷正常  ",
    }
    view = report.build_review_case_view(2, "C-9", payload, attachments=("wound.png",))
    assert view.warnings == ("⚠ 本案未取得半年病史佐證（病歷缺席）。",)
    assert view.labs == ({"name": "HbA1c", "value": "8.5", "unit": "%"},)
    assert view.cloud_text == "健保跨院病歷正常"
    assert view.attachments == ("wound.png",)


def test_render_shows_warnings_labs_cloud_and_attachments():
    view = report.ReviewCaseView(
        case_id="C-10",
        stage=2,
        warnings=("⚠ 病歷缺席",),
        labs=({"name": "HbA1c", "value": "8.5", "unit": "%"},),
        cloud_text="健保跨院病歷正常",
        attachments=("wound.png",),
    )
    html = report.render_unified_review_html(view)
    assert "⚠ 病歷缺席" in html
    assert "8.5 %" in html
    assert "健保跨院病歷正常" in html
    assert "wound.png" in html


def test_render_is_self_contained_without_external_resources():
    view = report.ReviewCaseView(case_id="C-8", stage=2, soap={"s": "S"}, soap_source="case")
    html = report.render_unified_review_html(view)
    assert "<link" not in html
    assert "src=" not in html
