"""三方比對器測試（05-01-PLAN Task 1-3）。

涵蓋：C1 逐檢核項判定＋引用原文、D7/D-04 三級分類純函式、C2/D-05 候選
補強、D-02 證據組裝（含截斷/病歷缺席）、D-06 RuleRepositoryError 穿透、
未知醫令（C5）、D-07 病歷缺席降級、D-08 注入替身零 LLM 依賴、judger/
narratives 的 JSON 解析與重試邏輯（mock，不需真實 server）。
"""

import json
from datetime import date
from unittest import mock

import pytest

from elc_audit_engine.comparator import (
    SUPPORT_NONE,
    SUPPORT_SUFFICIENT,
    SUPPORT_WEAK,
    VERDICT_MANUAL,
    VERDICT_PARTIAL,
    VERDICT_SUPPORTED,
    VERDICT_UNSUPPORTED,
    CaseComparisonResult,
    CheckItem,
    Judgment,
    LLMJudger,
    OrderJudgment,
    build_evidence_blocks,
    classify_support,
    compare_case,
    create_generator,
    create_judger,
)
from elc_audit_engine.comparator.models import CandidateNarrative
from elc_audit_engine.parsers.models import OrderRecord, SOAPDocument, SubmissionCase
from elc_audit_engine.record_aggregator.models import (
    ImagingRecord,
    LabRecord,
    PatientTimeline,
    VisitRecord,
)
from elc_audit_engine.rule_repository.errors import RuleRepositoryError
from elc_audit_engine.rule_repository.models import RuleResult, not_found


def _rule(
    code="64140C",
    article_full_text="應記載檢驗結果及臨床處置",
    article_location="西醫基層-內科 > 一",
    article_source="docx",
    source="payment",
):
    return RuleResult(
        code=code,
        source=source,
        name="測試項目",
        payment_text="測試支付規定",
        effective_from=None,
        effective_to=None,
        article_location=article_location,
        article_full_text=article_full_text,
        article_source=article_source,
        found=True,
    )


def _case(orders=("64140C",), record_no="M220518024"):
    return SubmissionCase(
        case_class="02",
        case_seq="1",
        record_no=record_no,
        primary_diagnosis="S90221A",
        secondary_diagnoses=("S67191A",),
        orders=tuple(
            OrderRecord(code=code, seq=str(i + 1)) for i, code in enumerate(orders)
        ),
    )


def _soap_doc():
    return SOAPDocument(
        sections={
            "S": ("右手腕扭傷後疼痛三天",),
            "O": ("局部腫脹、壓痛",),
            "A": ("手腕扭傷",),
            "P": ("衛教休息",),
        },
        segments=(),
        method="marker",
        confidence="high",
    )


def _timeline():
    return PatientTimeline(
        patient_id="M220518024",
        window_start=date(2026, 2, 1),
        window_end=date(2026, 8, 1),
        visits=(VisitRecord(patient_id="M220518024", date=date(2026, 7, 20), clinic="骨科",
                            soap_text="主訴：手腕疼痛", diagnoses=("S6300XA",)),),
        labs=(LabRecord(patient_id="M220518024", date=date(2026, 2, 15),
                        test_name="HbA1c", result="7.2", unit="%", abnormal=True),),
        exams=(),
        imaging=(ImagingRecord(patient_id="M220518024", date=date(2026, 6, 1),
                               modality="CT", body_part="胸部", impression="無異常"),),
        source_provider="local:test",
    )


# ---------------------------------------------------------------- 三級分類（D-04）

def test_classify_support_sufficient():
    level, manual = classify_support([Judgment(VERDICT_SUPPORTED, "有記載")])
    assert level == SUPPORT_SUFFICIENT
    assert manual is False


def test_classify_support_weak():
    level, manual = classify_support([
        Judgment(VERDICT_SUPPORTED, "a"),
        Judgment(VERDICT_UNSUPPORTED, ""),
    ])
    assert level == SUPPORT_WEAK
    assert manual is False


def test_classify_support_none():
    level, manual = classify_support([Judgment(VERDICT_UNSUPPORTED, "")])
    assert level == SUPPORT_NONE
    assert manual is False


def test_classify_support_partial_counts_as_support():
    level, _ = classify_support([Judgment(VERDICT_PARTIAL, "部分")])
    assert level == SUPPORT_SUFFICIENT


def test_classify_support_manual_flags_review():
    level, manual = classify_support([Judgment(VERDICT_MANUAL, "")])
    assert manual is True
    assert level == SUPPORT_NONE


def test_classify_support_empty_is_none():
    level, manual = classify_support([])
    assert level == SUPPORT_NONE
    assert manual is False


# ---------------------------------------------------------------- 證據組裝（D-02）

def test_evidence_contains_soap_and_timeline():
    evidence = build_evidence_blocks(_case(), _soap_doc(), _timeline())
    assert "【當次 SOAP】" in evidence
    assert "[S] 右手腕扭傷後疼痛三天" in evidence
    assert "【半年病史" in evidence
    assert "[檢驗 2026-02-15] HbA1c = 7.2 %（異常）" in evidence
    assert "[影像 2026-06-01] CT 胸部：無異常" in evidence
    assert "M220518024" in evidence


def test_evidence_without_timeline_uses_soap_only():
    evidence = build_evidence_blocks(_case(), _soap_doc(), None)
    assert "【當次 SOAP】" in evidence
    assert "【半年病史" not in evidence


def test_evidence_truncates_long_text():
    long_soap = "症狀" * 600
    soap = SOAPDocument(sections={"S": (long_soap,)}, method="marker", confidence="high")
    evidence = build_evidence_blocks(_case(), soap, None)
    assert len(evidence) < 3000
    assert "…" in evidence


# ---------------------------------------------------------------- 主流程（compare_case）

def test_compare_case_sufficient():
    result = compare_case(
        _case(),
        _soap_doc(),
        _timeline(),
        rule_lookup=lambda code: _rule(),
        judge_fn=lambda item, ev: Judgment(VERDICT_SUPPORTED, "病歷有記載"),
    )
    assert result.records_degraded is False
    assert len(result.order_judgments) == 1
    oj = result.order_judgments[0]
    assert oj.rule_found is True
    assert oj.support_level == SUPPORT_SUFFICIENT
    assert oj.judgment.quote == "病歷有記載"
    assert oj.narratives == ()
    assert result.unknown_orders == ()
    assert result.manual_review_orders == ()


def test_compare_case_unsupported_generates_narratives():
    result = compare_case(
        _case(),
        _soap_doc(),
        _timeline(),
        rule_lookup=lambda code: _rule(),
        judge_fn=lambda item, ev: Judgment(VERDICT_UNSUPPORTED, ""),
        narrative_fn=lambda item, ev, level: [
            CandidateNarrative(
                text="依病歷記載補強檢驗結果",
                rule_location=item.rule_location,
                prompt_only=False,
            )
        ],
    )
    oj = result.order_judgments[0]
    assert oj.support_level == SUPPORT_NONE
    assert len(oj.narratives) == 1
    assert oj.narratives[0].rule_location == "西醫基層-內科 > 一"


def test_compare_case_unknown_order():
    result = compare_case(
        _case(orders=("99999X",)),
        _soap_doc(),
        _timeline(),
        rule_lookup=lambda code: not_found(code),
    )
    oj = result.order_judgments[0]
    assert oj.rule_found is False
    assert oj.support_level is None
    assert "查無規則依據" in oj.note
    assert result.unknown_orders == ("99999X",)


def test_compare_case_rule_repository_error_propagates():
    def broken_lookup(code):
        raise RuleRepositoryError("db is locked")

    with pytest.raises(RuleRepositoryError):
        compare_case(_case(), _soap_doc(), _timeline(), rule_lookup=broken_lookup)


def test_compare_case_records_degraded_when_timeline_none():
    result = compare_case(
        _case(),
        _soap_doc(),
        None,
        rule_lookup=lambda code: _rule(),
        judge_fn=lambda item, ev: Judgment(VERDICT_SUPPORTED, "x"),
    )
    assert result.records_degraded is True


def test_compare_case_manual_review_flag():
    result = compare_case(
        _case(),
        _soap_doc(),
        _timeline(),
        rule_lookup=lambda code: _rule(),
        judge_fn=lambda item, ev: Judgment(VERDICT_MANUAL, ""),
    )
    assert result.manual_review_orders == ("64140C",)
    assert result.order_judgments[0].manual_review is True


def test_compare_case_multiple_orders_mixed():
    def lookup(code):
        return _rule(code=code) if code == "64140C" else not_found(code)

    result = compare_case(
        _case(orders=("64140C", "99999X")),
        _soap_doc(),
        _timeline(),
        rule_lookup=lookup,
        judge_fn=lambda item, ev: Judgment(VERDICT_SUPPORTED, "x"),
    )
    assert len(result.order_judgments) == 2
    assert result.order_judgments[0].rule_found is True
    assert result.order_judgments[1].rule_found is False
    assert result.unknown_orders == ("99999X",)


def test_compare_case_default_uses_real_get_rule_signature():
    """預設 rule_lookup=get_rule（不注入）；此測試只驗證簽名相容（不實際查 DB）。"""
    import inspect

    sig = inspect.signature(compare_case)
    assert "rule_lookup" in sig.parameters
    assert "judge_fn" in sig.parameters
    assert "narrative_fn" in sig.parameters


# ---------------------------------------------------------------- judger（JSON/重試）

def _verdict_json(verdict="支持", quote="有記載", reason="理由"):
    return json.dumps({"verdict": verdict, "quote": quote, "reason": reason}, ensure_ascii=False)


def test_judger_parses_valid_json():
    judger = LLMJudger()
    with mock.patch(
        "elc_audit_engine.comparator.judger.chat_completion",
        return_value=_verdict_json(),
    ) as mocked:
        judgment = judger.judge(CheckItem("規則"), "病歷")
    assert judgment.verdict == VERDICT_SUPPORTED
    assert judgment.quote == "有記載"
    mocked.assert_called_once()


def test_judger_tolerates_code_fence_wrapping():
    judger = LLMJudger()
    wrapped = "```json\n" + _verdict_json("部分支持", "部分記載") + "\n```"
    with mock.patch(
        "elc_audit_engine.comparator.judger.chat_completion", return_value=wrapped
    ):
        judgment = judger.judge(CheckItem("規則"), "病歷")
    assert judgment.verdict == VERDICT_PARTIAL


def test_judger_retries_once_then_manual():
    judger = LLMJudger()
    with mock.patch(
        "elc_audit_engine.comparator.judger.chat_completion",
        side_effect=["不是 JSON", _verdict_json("無記載")],
    ) as mocked:
        judgment = judger.judge(CheckItem("規則"), "病歷")
    assert mocked.call_count == 2  # 換措辭重試一次（C1）
    assert judgment.verdict == VERDICT_UNSUPPORTED


def test_judger_double_failure_degrades_to_manual():
    judger = LLMJudger()
    with mock.patch(
        "elc_audit_engine.comparator.judger.chat_completion",
        side_effect=["垃圾", "還是垃圾"],
    ):
        judgment = judger.judge(CheckItem("規則"), "病歷")
    assert judgment.verdict == VERDICT_MANUAL
    assert "待人工" in judgment.reason


def test_judger_invalid_verdict_retries():
    judger = LLMJudger()
    with mock.patch(
        "elc_audit_engine.comparator.judger.chat_completion",
        side_effect=[
            _verdict_json("完全不對"),  # verdict 非法
            _verdict_json(),
        ],
    ):
        judgment = judger.judge(CheckItem("規則"), "病歷")
    assert judgment.verdict == VERDICT_SUPPORTED


def test_judger_network_error_degrades_to_manual():
    judger = LLMJudger()
    with mock.patch(
        "elc_audit_engine.comparator.judger.chat_completion",
        side_effect=RuntimeError("connection refused"),
    ):
        judgment = judger.judge(CheckItem("規則"), "病歷")
    assert judgment.verdict == VERDICT_MANUAL


def test_create_judger_injection():
    injected = create_judger(lambda item, ev: Judgment(VERDICT_SUPPORTED, "q"))
    assert injected(CheckItem("x"), "ev").verdict == VERDICT_SUPPORTED
    # 未注入 → LLMJudger（可呼叫）
    assert callable(create_judger())


# ---------------------------------------------------------------- narratives（C2）

def test_generator_parses_json_array():
    gen = create_generator()
    with mock.patch(
        "elc_audit_engine.comparator.narratives.chat_completion",
        return_value=json.dumps(
            [
                {"text": "病歷已記載疼痛，可補強執行紀錄", "prompt_only": False},
                {"text": "若實際有執行，請補充：檢驗日期", "prompt_only": True},
            ],
            ensure_ascii=False,
        ),
    ):
        items = gen(CheckItem("規則", rule_location="loc"), "病歷", SUPPORT_WEAK)
    assert len(items) == 2
    assert items[0].rule_location == "loc"
    assert items[0].prompt_only is False
    assert items[1].prompt_only is True


def test_generator_caps_at_three():
    gen = create_generator()
    payload = json.dumps(
        [{"text": f"敘述{i}", "prompt_only": False} for i in range(5)],
        ensure_ascii=False,
    )
    with mock.patch(
        "elc_audit_engine.comparator.narratives.chat_completion", return_value=payload
    ):
        items = gen(CheckItem("規則"), "病歷", SUPPORT_NONE)
    assert len(items) == 3


def test_generator_no_narratives_for_sufficient():
    gen = create_generator()
    items = gen(CheckItem("規則"), "病歷", SUPPORT_SUFFICIENT)
    assert items == []


def test_generator_failure_returns_empty():
    gen = create_generator()
    with mock.patch(
        "elc_audit_engine.comparator.narratives.chat_completion",
        side_effect=RuntimeError("timeout"),
    ):
        items = gen(CheckItem("規則"), "病歷", SUPPORT_NONE)
    assert items == []


def test_generator_skips_empty_text():
    gen = create_generator()
    with mock.patch(
        "elc_audit_engine.comparator.narratives.chat_completion",
        return_value=json.dumps([{"text": "  ", "prompt_only": False}]),
    ):
        items = gen(CheckItem("規則"), "病歷", SUPPORT_NONE)
    assert items == []
