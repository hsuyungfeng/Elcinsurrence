"""無給付規定（占位文字）的醫令與藥令不得納入預審報告。

例：AC43152151 的 payment_text 為「目前無」，並無任何限制條文，應判定為 no_text 並由 report_view 排除。
規則文字皆為合成字串（代碼 TST 開頭）。
"""

from __future__ import annotations

from datetime import date

import pytest

from elc_audit_engine.monthly_audit import (
    STATUS_NO_TEXT,
    STATUS_RESTRICTION,
    BatchAudit,
    aggregate_batch,
    audit_case,
    evaluate_order,
    report_view,
)
from elc_audit_engine.parsers.models import OrderRecord
from elc_audit_engine.rule_repository.models import RuleResult


def _rule(code: str, *, payment: str | None, article: str | None = None) -> RuleResult:
    return RuleResult(
        code=code, source="drug", name=f"合成{code}", payment_text=payment,
        effective_from="2023-01-01", effective_to="2910-12-31", article_location=None,
        article_full_text=article, article_source="docx" if article else None, found=True,
        unit_price="6.00",
    )


def _drug(code: str) -> OrderRecord:
    return OrderRecord(code=code, category="4", unit_price="0.00", points="0", seq="1", raw={})


def _judge(code: str, rule: RuleResult):
    return evaluate_order(_drug(code), case_diagnoses=("S1",), visit_date=date(2023, 7, 18),
                          lookup=lambda c: rule)


@pytest.mark.parametrize("placeholder", ["目前無", "無資訊", "無", "null", "NULL", "None", "none", " 目前無 ", "未找到給付規定"])
def test_placeholder_payment_text_is_no_text(placeholder):
    finding = _judge("TSTA", _rule("TSTA", payment=placeholder))
    assert finding is not None  # 官方價 6.00 > 5 → 仍為旗標醫令
    assert finding.rule_status == STATUS_NO_TEXT
    assert finding.rule_full_text is None


def test_placeholder_with_real_article_text_is_still_usable():
    finding = _judge("TSTB", _rule("TSTB", payment="目前無", article="限具適應症者使用。"))
    assert finding.rule_status == STATUS_RESTRICTION
    assert finding.rule_full_text == "限具適應症者使用。"


def test_report_view_excludes_placeholder_only_items():
    rule_none = _rule("TSTC", payment="目前無")
    payload = {
        "batch": "MONTHLY-202307", "case_seq": "1", "visit_date": "1120718", "total_points": "2000",
        "primary_diagnosis": "S1", "secondary_diagnoses": [],
        "orders": [{"p3": "4", "p4": "TSTC", "p10": "9.0", "p11": "0.00", "p12": "0", "p13": "1"}],
    }
    case = audit_case("CASE-NONE", payload, lookup=lambda c: rule_none)
    assert case.findings and case.findings[0].rule_status == STATUS_NO_TEXT
    batch = BatchAudit(batch="MONTHLY-202307", cases_total=1, cases=(case,),
                       report=aggregate_batch(1, (case,)))
    view = report_view(batch)
    assert view.cases == ()
    assert view.report["totals"]["findings"] == 0


def test_report_view_keeps_real_regulation_next_to_placeholder_item():
    payload = {
        "batch": "MONTHLY-202307", "case_seq": "2", "visit_date": "1120718", "total_points": "2000",
        "primary_diagnosis": "S1", "secondary_diagnoses": [],
        "orders": [
            {"p3": "4", "p4": "TSTC", "p10": "9.0", "p11": "0.00", "p12": "0", "p13": "1"},
            {"p3": "4", "p4": "TSTD", "p10": "9.0", "p11": "0.00", "p12": "0", "p13": "2"},
        ],
    }
    rules = {"TSTC": _rule("TSTC", payment="無資訊"), "TSTD": _rule("TSTD", payment="限治療糖尿病使用。")}
    case = audit_case("CASE-MIX", payload, lookup=lambda c: rules[c])
    batch = BatchAudit(batch="MONTHLY-202307", cases_total=1, cases=(case,),
                       report=aggregate_batch(1, (case,)))
    view = report_view(batch)
    assert [f.code for f in view.cases[0].findings] == ["TSTD"]
