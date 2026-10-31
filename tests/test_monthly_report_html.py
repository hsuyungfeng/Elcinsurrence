"""精簡版 HTML 報告：只列有給付規定且超過門檻的醫令；案件醫療總點數 > 1000 才納入；
推理樹與 SOAP 清單不輸出；身分證字號標示正確；轉義、無外部資源、主題。

規則文字皆為合成字串（代碼 TST 開頭）。
"""

from __future__ import annotations

from elc_audit_engine.monthly_audit import BatchAudit, aggregate_batch, audit_case
from elc_audit_engine.monthly_report_html import render_batch_report_html
from elc_audit_engine.rule_repository.models import RuleResult, not_found

XSS_TEXT = "限使用 <script>alert(1)</script> 條件。需檢附證明"
PLAIN_TEXT = "一般說明文字。"


def _rule(code: str) -> RuleResult:
    texts = {
        "TSTX": XSS_TEXT,  # 有給付限制條文
        "TSTY": XSS_TEXT,  # 藥品，有限制條文
        "TSTP": PLAIN_TEXT,  # 有給付文字但無限制用語
    }
    if code in texts:
        return RuleResult(
            code=code, source="payment", name='名稱 "<b>x</b>"' if code == "TSTX" else f"合成{code}",
            payment_text=texts[code], effective_from="2023-01-01", effective_to="2910-12-31",
            article_location=None, article_full_text=None, article_source=None, found=True,
        )
    return not_found(code)  # TSTN 等：查無規則


def _payload(orders: list[dict], *, seq: str = "1", doctor: str = "D1", dept: str = "03",
             total: str | None = "2000", **identity) -> dict:
    data = {
        "batch": "MONTHLY-202307",
        "case_seq": seq,
        "record_no": "M220518024",
        "patient_name": "陳李媚",
        "birth_date": "0450108",
        "total_points": total,
        "clinic": dept,
        "doctor_code": doctor,
        "visit_date": "1120718",
        "primary_diagnosis": "S00123A",
        "secondary_diagnoses": ["K57"],
        "orders": orders,
    }
    data.update(identity)
    return data


def _po(code: str, *, cat: str = "2", unit: str = "1", points: str = "400", seq: str = "1") -> dict:
    return {"p3": cat, "p4": code, "p10": "1.0", "p11": unit, "p12": points, "p13": seq}


def _batch(payloads: list[tuple[str, dict]]) -> BatchAudit:
    cases = tuple(audit_case(cid, payload, lookup=_rule) for cid, payload in payloads)
    flagged = tuple(c for c in cases if c.findings)
    return BatchAudit(
        batch="MONTHLY-202307",
        cases_total=len(cases),
        cases=flagged,
        report=aggregate_batch(len(cases), flagged),
    )


def _sample_html() -> str:
    batch = _batch([
        # 案 1：TSTX（有規則）＋TSTN（查無規則，應隱藏）＋藥品 TSTY（單價缺漏，有規則）
        ("MON-a", _payload([
            _po("TSTX", seq="1"),
            _po("TSTN", seq="2"),
            _po("TSTY", cat="4", unit="0", points="0", seq="3"),
        ], seq="1", doctor="D1")),
        # 案 2：醫療總點數 500 ≤ 1000，即使有規則也不納入
        ("MON-b", _payload([_po("TSTX", seq="1")], seq="2", doctor="D2", dept="01", total="500")),
        # 案 3：總點數 2000，有規則醫令
        ("MON-c", _payload([_po("TSTX", seq="1")], seq="3", doctor="D2", dept="01", total="2000")),
    ])
    return render_batch_report_html(batch)


# ── 結構與安全 ──────────────────────────────────────────────────


def test_document_shape_and_charset():
    html = _sample_html()
    assert html.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in html
    assert 'name="viewport"' in html
    assert "<title>當月申報預審 MONTHLY-202307</title>" in html


def test_no_external_resources_or_scripts_loaded():
    html = _sample_html()
    assert "http://" not in html
    assert "https://" not in html
    assert "<script src" not in html
    assert "<link " not in html
    # 只允許一段內嵌的複製腳本（無外部來源）；使用者資料仍須轉義（見下方測試）
    assert html.lower().count("<script>") == 1


def test_rule_text_is_escaped_never_rendered_as_markup():
    html = _sample_html()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


# ── 精簡：不輸出推理樹／SOAP，不列查無規則醫令 ─────────────────────


def test_reasoning_tree_and_soap_blocks_are_not_rendered():
    html = _sample_html()
    for forbidden in ("推理樹", "Tree of Criteria", "SOAP", 'class="tree"', 'class="checklist"', "補強"):
        assert forbidden not in html


def test_not_found_items_are_hidden_entirely():
    html = _sample_html()
    assert "TSTN" not in html  # 查無規則
    assert "TSTY" in html  # 有規則的藥品保留


def test_only_items_with_regulation_get_fulltext_expander():
    html = _sample_html()
    # 案 1 的 TSTX、TSTY；案 3 的 TSTX（案 2 因總點數不足不納入）
    assert html.count('<details class="rule-fulltext">') == 3
    assert "📜 檢視完整給付規定條文" in html


def test_item_card_shows_amount_line_and_expander_only():
    html = _sample_html()
    assert '<div class="amounts">單價: 1 元 · 點數: 400 點 · 總量: 1.0</div>' in html
    assert "<details class=\"rule-fulltext\"><summary>📜 檢視完整給付規定條文</summary>" in html


def test_no_regulation_text_block_when_rule_has_no_text():
    batch = _batch([("MON-n", _payload([_po("TSTNONE", points="400")]))])
    html = render_batch_report_html(batch)
    assert "TSTNONE" not in html  # 無規則：整列隱藏
    assert '<details class="rule-fulltext">' not in html


def test_no_markers_rule_is_included_because_official_text_exists():
    batch = _batch([("MON-p", _payload([_po("TSTP", points="400")]))])
    html = render_batch_report_html(batch)
    assert "TSTP" in html
    assert '<details class="rule-fulltext">' in html


# ── 納入門檻：醫療總點數 > 1000 ──────────────────────────────────


def test_case_with_total_points_at_or_below_1000_is_excluded():
    html = _sample_html()
    assert "醫療總費用: 500 點" not in html
    assert "流水號 2" not in html


def test_case_total_points_shown_in_header():
    html = _sample_html()
    assert "醫療總費用: 2000 點" in html


def test_case_with_missing_total_points_is_excluded():
    batch = _batch([("MON-m", _payload([_po("TSTX")], total=None))])
    html = render_batch_report_html(batch)
    assert "本批次無符合條件" in html


def test_empty_batch_renders_placeholder():
    empty = BatchAudit(batch="MONTHLY-202307", cases_total=0, cases=(), report=aggregate_batch(0, ()))
    html = render_batch_report_html(empty)
    assert "本批次無符合條件" in html
    assert '<details class="case">' not in html


# ── 身分證字號標示與案件標題 ──────────────────────────────────────


def test_identity_is_labelled_as_national_id_not_medical_record_number():
    html = _sample_html()
    assert "身分證字號 M220518024" in html
    assert "病歷號" not in html


def test_case_header_fields_appear_in_requested_order():
    html = _sample_html()
    start = html.index('class="case-head"')
    header = html[start: html.index("</span>", start)]
    expected = [
        "流水號 1", "身分證字號 M220518024", "姓名 陳李媚", "出生日期 0450108",
        "醫療總費用: 2000 點", "科別 03", "醫師 D1", "就醫日 1120718", "主診斷 S00123A",
    ]
    positions = [header.index(part) for part in expected]
    assert positions == sorted(positions)


def test_missing_identity_fields_are_hidden_not_shown_as_placeholders():
    batch = _batch([("MON-h", _payload([_po("TSTX")], record_no=None, patient_name=None, birth_date=None))])
    html = render_batch_report_html(batch)
    header = html[html.index('class="case-head"'): html.index("</span>", html.index('class="case-head"'))]
    assert "身分證字號" not in header  # 標題列不顯示缺漏欄位
    assert "姓名" not in header
    assert "未記錄" not in html


def test_no_secondary_diagnosis_line_when_absent():
    payload = _payload([_po("TSTX")], secondary_diagnoses=[])
    html = render_batch_report_html(_batch([("MON-nosec", payload)]))
    assert "次診斷" not in html


# ── 摘要與主題 ───────────────────────────────────────────────────


def test_summary_kpis_reflect_included_cases_only():
    html = _sample_html()
    # 納入案件 2 件（案 1、案 3）；納入醫令 3 筆（案 1 的 TSTX、TSTY；案 3 的 TSTX）
    assert '<div class="num">2</div><div class="lbl">納入報告案件' in html
    assert '<div class="num">3</div><div class="lbl">納入醫令' in html


def test_dark_and_light_theme_css_present():
    html = _sample_html()
    assert "prefers-color-scheme: dark" in html
    assert ':root[data-theme="dark"]' in html
    assert "grid-template-columns: repeat(auto-fit" in html  # KPI 格狀版面響應式


def test_disclaimer_states_no_compliance_conclusion_and_pii_notice():
    html = _sample_html()
    assert "不產生支持／裸奔或給付判定" in html
    assert "身分證字號、姓名與出生日期" in html
