"""需求增補：患者識別欄位、申報金額由高到低排序（p12 點數，缺漏退回 p11 單價）、
規則全文展開、無內容項目隱藏。

規則文字為合成字串；代碼以 TST 開頭。
"""

from __future__ import annotations

from datetime import date

from elc_audit_engine.monthly_audit import (
    BatchAudit,
    aggregate_batch,
    audit_case,
    evaluate_order,
)
from elc_audit_engine.monthly_reasoning import build_reasoning_tree
from elc_audit_engine.monthly_report_html import render_batch_report_html
from elc_audit_engine.parsers.models import OrderRecord
from elc_audit_engine.parsers.totfa import declared_amount
from elc_audit_engine.rule_repository.models import RuleResult, not_found

LONG_TEXT = "限下列適應症使用。" + "說明一段很長的給付規定條文內容。" * 30 + "需檢附病歷。"


def _rule(code: str, *, payment: str | None = None, article: str | None = None) -> RuleResult:
    return RuleResult(
        code=code, source="payment", name=f"合成{code}", payment_text=payment,
        effective_from="2023-01-01", effective_to="2910-12-31", article_location=None,
        article_full_text=article, article_source="csv" if article else None, found=True,
    )


RULES: dict[str, RuleResult] = {
    "TSTLONG": _rule("TSTLONG", payment=LONG_TEXT),
    "TSTART": _rule("TSTART", payment=None, article="條文全文：限具適應症者使用。"),
    "TSTBOTH": _rule("TSTBOTH", payment="給付規定：限使用。", article="條文全文：另一版本。"),
    "TSTNULL": _rule("TSTNULL", payment="null", article=None),
    "TSTDIAG": _rule("TSTDIAG", payment="限治療糖尿病使用。"),
    "TSTICD": _rule("TSTICD", payment="ICD‑10 S00.1、S00.2 等診斷需附病歷。"),
}


def _lookup(code: str) -> RuleResult:
    return RULES.get(code, not_found(code))


def _order(code: str, *, cat: str = "2", unit: str | None = "1", points: str | None = "400", seq: str = "1") -> dict:
    return {"p3": cat, "p4": code, "p10": "1.0", "p11": unit, "p12": points, "p13": seq}


def _payload(orders: list[dict], **extra) -> dict:
    base = {
        "batch": "MONTHLY-202307",
        "case_seq": "7",
        "record_no": "M220518024",
        "patient_name": "陳李媚",
        "birth_date": "0450108",
        "total_points": "2000",
        "clinic": "03",
        "doctor_code": "D1",
        "visit_date": "1120718",
        "primary_diagnosis": "S00123A",
        "secondary_diagnoses": [],
        "orders": orders,
    }
    base.update(extra)
    return base


# ── 患者識別欄位 ─────────────────────────────────────────────────


def test_patient_fields_exposed_on_case_and_dict():
    case = audit_case("MON-p", _payload([_order("TSTLONG")]), lookup=_lookup)
    assert case.patient_id == "M220518024"  # d3 病歷號
    assert case.patient_name == "陳李媚"  # d49 姓名
    assert case.birth_date == "0450108"  # d11 出生年月日（民國七碼）
    data = case.to_dict()
    assert data["patient_id"] == "M220518024"
    assert data["patient_name"] == "陳李媚"
    assert data["birth_date"] == "0450108"


def test_patient_fields_default_to_none_when_absent():
    payload = _payload([_order("TSTLONG")])
    for key in ("record_no", "patient_name", "birth_date"):
        payload.pop(key)
    case = audit_case("MON-q", payload, lookup=_lookup)
    assert (case.patient_id, case.patient_name, case.birth_date) == (None, None, None)


# ── 申報金額排序 ─────────────────────────────────────────────────


def test_declared_amount_prefers_points_then_unit_price():
    assert declared_amount(OrderRecord(points="12.5", unit_price="99", raw={})) == 12.5
    assert declared_amount(OrderRecord(points=None, unit_price="3", raw={})) == 3
    assert declared_amount(OrderRecord(points="", unit_price=None, raw={})) is None


def test_findings_sorted_by_points_descending_with_unit_price_fallback():
    orders = [
        _order("TSTA", points="400", seq="1"),  # 400
        _order("TSTB", points="9000", seq="2"),  # 9000（最高）
        _order("TSTC", cat="4", points=None, unit="6.00", seq="3"),  # 無點數 → 退回單價 6.00
        _order("TSTD", cat="4", points="0", unit="0.00", seq="4"),  # 0（單價缺漏）
        _order("TSTE", points="500", unit="9999", seq="5"),  # 點數 500 優先於單價 9999
    ]
    case = audit_case("MON-s", _payload(orders), lookup=_lookup)
    assert [f.code for f in case.findings] == ["TSTB", "TSTE", "TSTA", "TSTC", "TSTD"]


def test_findings_without_any_amount_sort_last():
    orders = [
        _order("TSTX", cat="4", points=None, unit=None, seq="1"),  # 無金額 → 排最後
        _order("TSTY", points="400", seq="2"),
    ]
    case = audit_case("MON-n", _payload(orders), lookup=_lookup)
    assert [f.code for f in case.findings] == ["TSTY", "TSTX"]


def test_sorted_order_is_visible_in_json_as_well():
    orders = [_order("TSTA", points="400", seq="1"), _order("TSTB", points="9000", seq="2")]
    case = audit_case("MON-j", _payload(orders), lookup=_lookup)
    assert [f["code"] for f in case.to_dict()["findings"]] == ["TSTB", "TSTA"]


# ── 規則全文 ─────────────────────────────────────────────────────


def _finding_for(code: str, **kwargs):
    order = OrderRecord(code=code, category=kwargs.get("cat", "2"), unit_price="1", points="400", seq="1", raw={})
    return evaluate_order(order, case_diagnoses=("S00123A",), visit_date=date(2023, 7, 18), lookup=_lookup)


def test_rule_full_text_is_the_complete_verbatim_payment_text():
    finding = _finding_for("TSTLONG")
    assert finding.rule_full_text == LONG_TEXT  # 不截斷、逐字


def test_rule_full_text_falls_back_to_article_text():
    assert _finding_for("TSTART").rule_full_text == "條文全文：限具適應症者使用。"


def test_rule_full_text_prefers_payment_text_when_both_exist():
    assert _finding_for("TSTBOTH").rule_full_text == "給付規定：限使用。"


def test_rule_full_text_is_none_when_rule_has_no_text():
    assert _finding_for("TSTNULL").rule_full_text is None


def test_rule_full_text_is_serialized_only_on_request():
    case = audit_case("MON-f", _payload([_order("TSTLONG")]), lookup=_lookup)
    assert "rule_full_text" not in case.to_dict()["findings"][0]
    assert case.to_dict(include_rule_text=True)["findings"][0]["rule_full_text"] == LONG_TEXT


def test_html_expandable_block_contains_full_regulation_text():
    case = audit_case("MON-h", _payload([_order("TSTLONG")]), lookup=_lookup)
    batch = BatchAudit(batch="MONTHLY-202307", cases_total=1, cases=(case,), report=aggregate_batch(1, (case,)))
    html = render_batch_report_html(batch)
    assert '<details class="rule-fulltext"><summary>📜 檢視完整給付規定條文</summary>' in html
    assert LONG_TEXT in html


# ── 空項目隱藏 ─────────────────────────────────────────────────


def test_diagnosis_fact_hidden_when_rule_lists_no_icd():
    finding = _finding_for("TSTDIAG")
    tree = build_reasoning_tree(finding, case_dx="S00123A")
    labels = [child.label for child in tree.children]
    assert not any(label.startswith("診斷比對") for label in labels)


def test_diagnosis_fact_shown_when_rule_lists_icd():
    finding = _finding_for("TSTICD")
    tree = build_reasoning_tree(finding, case_dx="S00123A")
    facts = [child.label for child in tree.children if child.kind == "fact"]
    assert any(label.startswith("診斷比對：") and "S00.1" in label for label in facts)
