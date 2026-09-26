"""Warning 第一批：判定與補強內容正確性（B-WR-05/06/09/10/11/12）。"""
import json
from datetime import date
from unittest import mock

from elc_audit_engine.comparator import compare_case
from elc_audit_engine.comparator.evidence import _timeline_block
from elc_audit_engine.comparator.judger import LLMJudger
from elc_audit_engine.comparator.models import (
    SUPPORT_NONE,
    CheckItem,
    Judgment,
    VERDICT_MANUAL,
    VERDICT_UNSUPPORTED,
)
from elc_audit_engine.comparator.narratives import create_generator
from elc_audit_engine.parsers.models import OrderRecord, SubmissionCase
from elc_audit_engine.record_aggregator.models import PatientTimeline, VisitRecord
from elc_audit_engine.record_aggregator.providers import _get_bool_or_none
from elc_audit_engine.rule_repository.models import RuleResult


def _rule(text="須記載檢驗理由"):
    return RuleResult(
        code="X", found=True, source="payment", name="n", payment_text=text,
        effective_from=None, effective_to=None, article_location=None,
        article_full_text=None, article_source=None,
    )


def test_fabricated_quote_downgraded_to_manual():
    """B-WR-09：支持判定的引文不在病歷中 → 待人工。"""
    reply = json.dumps({"verdict": "支持", "quote": "病歷中根本沒有這句", "reason": "r"}, ensure_ascii=False)
    with mock.patch("elc_audit_engine.comparator.judger.chat_completion", return_value=reply):
        j = LLMJudger().judge(CheckItem("規則"), "S: 頭痛三天")
    assert j.verdict == VERDICT_MANUAL


def test_quote_match_ignores_whitespace():
    reply = json.dumps({"verdict": "支持", "quote": "頭痛 三天", "reason": "r"}, ensure_ascii=False)
    with mock.patch("elc_audit_engine.comparator.judger.chat_completion", return_value=reply):
        j = LLMJudger().judge(CheckItem("規則"), "S: 頭痛三天")
    assert j.verdict == "支持"


def test_string_false_prompt_only_and_unsupported_claim_forced_to_prompt():
    """B-WR-10：字串 "false" 不是真；與病歷無重疊的事實敘述強制為提示型。"""
    reply = json.dumps(
        [{"text": "病人已接受三次復健治療", "prompt_only": "false"}], ensure_ascii=False
    )
    with mock.patch("elc_audit_engine.comparator.narratives.chat_completion", return_value=reply):
        items = create_generator()(CheckItem("規則"), "S: 頭痛", SUPPORT_NONE)
    assert items[0].prompt_only is True
    assert items[0].text.startswith("若實際有執行，請補充：")


def test_narrative_failure_flagged_on_order_judgment():
    case = SubmissionCase(orders=(OrderRecord(code="X"),))

    def boom(*a):
        raise RuntimeError("down")

    result = compare_case(
        case, None, None,
        rule_lookup=lambda c: _rule(),
        judge_fn=lambda item, ev: Judgment(VERDICT_UNSUPPORTED),
        narrative_fn=boom,
    )
    oj = result.order_judgments[0]
    assert oj.support_level == SUPPORT_NONE
    assert oj.narrative_error is True


def test_empty_rule_text_is_not_sent_to_judge():
    """B-WR-06"""
    called = []
    case = SubmissionCase(orders=(OrderRecord(code="X"),))
    result = compare_case(
        case, None, None,
        rule_lookup=lambda c: _rule(text=""),
        judge_fn=lambda item, ev: called.append(1) or Judgment("支持", "q"),
        narrative_fn=lambda *a: [],
    )
    assert called == []
    assert result.order_judgments[0].judgment.verdict == VERDICT_MANUAL


def test_blank_order_code_is_reported_not_skipped():
    """B-WR-05"""
    case = SubmissionCase(orders=(OrderRecord(code="  "),))
    result = compare_case(case, None, None, rule_lookup=lambda c: _rule(),
                          judge_fn=lambda *a: Judgment("支持", "q"), narrative_fn=lambda *a: [])
    assert len(result.order_judgments) == 1
    assert "醫令代碼缺漏" in result.order_judgments[0].note
    assert result.unknown_orders == ("",)


def test_evidence_uses_most_recent_visits():
    """B-WR-11"""
    visits = tuple(
        VisitRecord(patient_id="P", date=date(2026, m, 1), clinic="內科", soap_text=f"第{m}月")
        for m in range(1, 7)
    )
    tl = PatientTimeline(patient_id="P", window_start=date(2026, 1, 1), window_end=date(2026, 7, 1),
                         visits=visits, labs=(), exams=(), imaging=(), source_provider="t")
    text = "\n".join(_timeline_block(tl))
    assert "第6月" in text and "第4月" in text
    assert "第1月" not in text


def test_bool_strings_parsed_strictly():
    """B-WR-12"""
    assert _get_bool_or_none({"a": "false"}, "a") is False
    assert _get_bool_or_none({"a": "N"}, "a") is False
    assert _get_bool_or_none({"a": "Y"}, "a") is True
    assert _get_bool_or_none({"a": "maybe"}, "a") is None
    assert _get_bool_or_none({"a": True}, "a") is True
