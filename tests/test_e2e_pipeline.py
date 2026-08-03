"""端到端管線測試（08-01-PLAN Task 3，C6-4）。

三案例（充分/薄弱/裸奔）走真實管線 run_case_pipeline：
compare_case → write_report（補強報告＋審核軌跡）→ decisions（醫師審核）
→ build_appeal_draft → write_appeal。注入層（rule_lookup/judge_fn/
narrative_fn/decisions）可替換＝真實樣本替換空間（C6-5）。
"""

import json
import os
from datetime import date

import pytest

from elc_audit_engine.comparator.models import (
    SUPPORT_NONE,
    SUPPORT_SUFFICIENT,
    SUPPORT_WEAK,
    VERDICT_PARTIAL,
    VERDICT_SUPPORTED,
    VERDICT_UNSUPPORTED,
    CandidateNarrative,
    Judgment,
)
from elc_audit_engine.generators import STATUS_ADOPT, STATUS_ADOPT_EDITED
from elc_audit_engine.parsers.models import DeductionRecord, OrderRecord, SOAPDocument, SubmissionCase
from elc_audit_engine.pipeline import run_case_pipeline
from elc_audit_engine.record_aggregator.models import (
    ImagingRecord,
    LabRecord,
    PatientTimeline,
    VisitRecord,
)
from elc_audit_engine.rule_repository.errors import RuleRepositoryError
from elc_audit_engine.rule_repository.models import RuleResult, not_found


def _case(order_codes=("64140C",), record_no="M220518024"):
    return SubmissionCase(
        case_class="02",
        case_seq="1",
        record_no=record_no,
        primary_diagnosis="S90221A",
        orders=tuple(
            OrderRecord(code=code, seq=str(i + 1)) for i, code in enumerate(order_codes)
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
        visits=(VisitRecord(patient_id="M220518024", date=date(2026, 7, 20),
                            clinic="骨科", soap_text="主訴：手腕疼痛", diagnoses=()),),
        labs=(LabRecord(patient_id="M220518024", date=date(2026, 2, 15),
                        test_name="HbA1c", result="7.2", unit="%", abnormal=True),),
        exams=(),
        imaging=(),
        source_provider="local:test",
    )


def _rule(code="64140C"):
    return RuleResult(
        code=code,
        source="payment",
        name="測試項目",
        payment_text="應記載檢驗結果及臨床處置",
        effective_from=None,
        effective_to=None,
        article_location="西醫基層-內科 > 一",
        article_full_text="應記載檢驗結果及臨床處置",
        article_source="docx",
        found=True,
    )


def _deduction(order_code="64140C", case_seq="18", amount=300):
    return DeductionRecord(
        non_reimbursed_amount=amount,
        institution_code="1234567890",
        fee_year_month="202106",
        submit_date="2021-08-03",
        case_class="D2",
        case_seq=case_seq,
        visit_date="2021-06-23",
        order_seq="1",
        order_code=order_code,
        exec_start="2021-06-23",
        region="1",
        split_amount=amount,
        pay_date="2021-08-20",
        deduction_reason="VPN資料複核不通過",
        appeal_item_code="A",
        appeal_item_desc="檢驗結果確實於時效內上傳",
        institution_note="檢附VPN佐證資料。",
    )


def _narrative_fn():
    return lambda item, ev, level: [
        CandidateNarrative(
            text=f"候選補強：{item.rule_text}",
            rule_location=item.rule_location,
            prompt_only=level == "裸奔",
        )
    ]


def _assert_common_outputs(result, tmp_path, expected_badge):
    # 補強報告＋審核軌跡
    assert result.report_path == str(tmp_path / "病歷補強報告_M220518024.md")
    assert result.tracking_path == str(tmp_path / "審核軌跡_M220518024.json")
    report = open(result.report_path, encoding="utf-8").read()
    assert "# 病歷補強報告" in report
    assert expected_badge in report
    tracking = json.load(open(result.tracking_path, encoding="utf-8"))
    assert tracking["case_record_no"] == "M220518024"
    return report, tracking


def _run(tmp_path, verdict, *, decisions, expected_badge, expected_level):
    judge_fn = lambda item, ev: Judgment(verdict=verdict, quote="病歷有記載", reason="r")
    result = run_case_pipeline(
        _case(),
        _soap_doc(),
        _timeline(),
        [_deduction()],
        output_dir=str(tmp_path),
        rule_lookup=lambda code: _rule(code),
        judge_fn=judge_fn,
        narrative_fn=_narrative_fn(),
        decisions=decisions,
        reviewed_at="2026-08-03T10:00:00+00:00",
        appeal_options={"claimed_points": 300, "has_attachment": True},
    )
    report, tracking = _assert_common_outputs(result, tmp_path, expected_badge)
    assert result.comparison.order_judgments[0].support_level == expected_level
    # 申復草稿
    assert len(result.appeal_paths) == 1
    assert len(result.appeal_drafts) == 1
    md_path, json_path = result.appeal_paths[0]
    assert md_path == str(tmp_path / "申復草稿_18.md")
    assert json_path == str(tmp_path / "appeal_18.json")
    appeal_md = open(md_path, encoding="utf-8").read()
    assert "# 申復理由草稿" in appeal_md
    appeal = json.load(open(json_path, encoding="utf-8"))
    assert appeal["p2_order_code"] == "64140C"
    assert appeal["p6_points"] == 300
    assert appeal["p7_attachment"] == "Y"
    assert len(appeal["sections"]) == 4
    return report, tracking, appeal_md, appeal


# ── 案例 1：充分（支持）──────────────────────────────────────


def test_e2e_sufficient(tmp_path):
    report, tracking, appeal_md, appeal = _run(
        tmp_path,
        VERDICT_SUPPORTED,
        decisions={},  # 無缺口 → 無候選可審
        expected_badge="✅ 充分",
        expected_level=SUPPORT_SUFFICIENT,
    )
    assert "候選補強敘述" not in report
    assert tracking["entries"] == []  # 無敘述 → 軌跡空
    assert "尚無醫師採用的補強敘述" in appeal_md


# ── 案例 2：薄弱（部分支持，E2E-01 修正後可達）────────────────


def test_e2e_weak(tmp_path):
    report, tracking, appeal_md, appeal = _run(
        tmp_path,
        VERDICT_PARTIAL,
        decisions={0: (STATUS_ADOPT, None)},
        expected_badge="⚠️ 薄弱",
        expected_level=SUPPORT_WEAK,
    )
    assert "候選補強：應記載檢驗結果及臨床處置" in report
    assert tracking["entries"][0]["status"] == "採用"
    # 採用敘述流入 appeal ④
    assert "候選補強：應記載檢驗結果及臨床處置" in appeal_md
    evidence_section = next(s for s in appeal["sections"] if s["key"] == "evidence")
    assert "候選補強：應記載檢驗結果及臨床處置" in evidence_section["text"]


# ── 案例 3：裸奔（無記載）────────────────────────────────────


def test_e2e_none(tmp_path):
    report, tracking, appeal_md, appeal = _run(
        tmp_path,
        VERDICT_UNSUPPORTED,
        decisions={0: (STATUS_ADOPT_EDITED, "編輯後：檢驗結果確實於時效內上傳並留存回執。")},
        expected_badge="❌ 裸奔",
        expected_level=SUPPORT_NONE,
    )
    assert "提示型" in report  # 裸奔無線索 → prompt_only 候選
    assert tracking["entries"][0]["status"] == "編輯後採用"
    assert "編輯後：檢驗結果確實於時效內上傳並留存回執。" in appeal_md
    evidence_section = next(s for s in appeal["sections"] if s["key"] == "evidence")
    assert "編輯後：檢驗結果確實於時效內上傳並留存回執。" in evidence_section["text"]


# ── 真實樣本替換空間／邊界 ────────────────────────────────────


def test_e2e_unknown_order_is_honest(tmp_path):
    result = run_case_pipeline(
        _case(order_codes=("99999X",)),
        _soap_doc(),
        _timeline(),
        [_deduction(order_code="99999X")],
        output_dir=str(tmp_path),
        rule_lookup=lambda code: not_found(code),
        judge_fn=lambda item, ev: Judgment(VERDICT_SUPPORTED, "x"),
        narrative_fn=_narrative_fn(),
        decisions={},
    )
    assert result.comparison.unknown_orders == ("99999X",)
    appeal_md = open(result.appeal_paths[0][0], encoding="utf-8").read()
    assert "查無規則依據，建議人工查核" in appeal_md


def test_e2e_same_case_seq_two_records_no_overwrite(tmp_path):
    result = run_case_pipeline(
        _case(order_codes=("64140C", "48010C")),
        _soap_doc(),
        _timeline(),
        [_deduction(order_code="64140C", case_seq="18"),
         _deduction(order_code="48010C", case_seq="18", amount=150)],
        output_dir=str(tmp_path),
        rule_lookup=lambda code: _rule(code),
        judge_fn=lambda item, ev: Judgment(VERDICT_SUPPORTED, "x"),
        narrative_fn=_narrative_fn(),
        decisions={},
        appeal_options={"claimed_points": 300},
    )
    paths = [md for md, _ in result.appeal_paths]
    assert paths[0] == str(tmp_path / "申復草稿_18.md")          # C7 預設命名
    assert paths[1] == str(tmp_path / "申復草稿_18_48010C.md")    # 多筆防覆寫
    assert len(set(paths)) == 2
    assert (tmp_path / "appeal_18.json").exists()
    assert (tmp_path / "appeal_18_48010C.json").exists()


def test_e2e_rule_repository_error_propagates_from_compare():
    # P0-2：比對階段的規則庫故障必須穿透（不得吞成查無規則）
    def broken_lookup(code):
        raise RuleRepositoryError("db is locked")

    with pytest.raises(RuleRepositoryError):
        run_case_pipeline(
            _case(),
            _soap_doc(),
            _timeline(),
            [_deduction()],
            output_dir="/tmp/never-written",
            rule_lookup=broken_lookup,
            judge_fn=lambda item, ev: Judgment(VERDICT_SUPPORTED, "x"),
            narrative_fn=_narrative_fn(),
            decisions={},
        )


def test_e2e_appeal_rule_error_degraded_per_record(tmp_path):
    # appeal 階段查詢的醫令不在比對範圍（compare 已成功）→ 單筆故障降級
    # 為查無規則，不阻斷整案（C5 精神）。
    calls = {"n": 0}

    def flaky_lookup(code):
        calls["n"] += 1
        if calls["n"] <= 1:  # compare 階段成功
            return _rule(code)
        raise RuleRepositoryError("db is locked")  # appeal 階段故障

    result = run_case_pipeline(
        _case(order_codes=("64140C",)),
        _soap_doc(),
        _timeline(),
        [_deduction()],
        output_dir=str(tmp_path),
        rule_lookup=flaky_lookup,
        judge_fn=lambda item, ev: Judgment(VERDICT_SUPPORTED, "x"),
        narrative_fn=_narrative_fn(),
        decisions={},
    )
    assert result.report_path.endswith("病歷補強報告_M220518024.md")
    appeal_md = open(result.appeal_paths[0][0], encoding="utf-8").read()
    assert "查無規則依據，建議人工查核" in appeal_md
