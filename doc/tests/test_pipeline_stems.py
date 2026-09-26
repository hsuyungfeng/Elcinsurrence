"""A-WR-09：同流水號同醫令碼多筆（不同醫令序）不得互相覆寫。"""
import os

from elc_audit_engine.comparator.models import Judgment
from elc_audit_engine.parsers.models import DeductionRecord, SubmissionCase
from elc_audit_engine.pipeline import run_case_pipeline


def test_same_code_different_order_seq_distinct_files(tmp_path):
    records = [
        DeductionRecord(case_seq="12", order_seq=str(i), order_code="64140C", non_reimbursed_amount=100)
        for i in (1, 2, 3)
    ]
    from elc_audit_engine.rule_repository.models import not_found

    result = run_case_pipeline(
        SubmissionCase(record_no="R1"), None, None, records, output_dir=str(tmp_path),
        rule_lookup=not_found,
        judge_fn=lambda *a: Judgment("支持", "q"), narrative_fn=lambda *a: [],
    )
    json_paths = [j for _, j in result.appeal_paths]
    assert len(set(json_paths)) == 3
    assert all(os.path.exists(p) for p in json_paths)


def test_ocr_rejects_non_code_words():
    """B-WR-19：TOTAL／金額／Page1 不得被當成醫令代碼。"""
    from elc_audit_engine.ingest.ocr_rows import parse_sampling_ocr_text

    res = parse_sampling_ocr_text("TOTAL 合計 12345\nPage1\n14050B 糖化血色素\nP4401B 特材")
    assert [r.order_code for r in res.records] == ["14050B", "P4401B"]
    assert len(res.rejected) == 2
