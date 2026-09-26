"""A-CR-06：核減明細表頭必須讀 facility.json 的 code／name，並相容 deduct_amount payload。"""
from elc_audit_engine.generators.deduction_print.field_mapping import (
    build_deduction_header,
    build_deduction_rows,
)

FACILITY = {"code": "01015C", "name": "示例醫療院所"}


def test_header_uses_facility_json_keys():
    h = build_deduction_header([{"case_seq": "1", "non_reimbursed_amount": 10}], FACILITY)
    assert h["機構代碼"] == "01015C"
    assert h["醫療院所名稱"] == "示例醫療院所"


def test_header_totals_from_appeal_payload_deduct_amount():
    records = [{"case_seq": "1", "deduct_amount": 3200}, {"case_seq": "2", "deduct_amount": 150}]
    h = build_deduction_header(records, FACILITY)
    assert h["總核減點數"] == "3350"
    rows, _ = build_deduction_rows(records)
    assert rows[0]["不予核銷金額/核減點數"] == "3200"


def test_case_count_no_concat_collision_and_none_safe():
    records = [
        {"case_class": "1", "case_seq": "23"},
        {"case_class": "12", "case_seq": "3"},
        {"case_class": None, "case_seq": "5"},
    ]
    assert build_deduction_header(records, FACILITY)["核減件數"] == "3"


def test_non_numeric_amount_does_not_raise():
    h = build_deduction_header([{"non_reimbursed_amount": "1,200"}, {"non_reimbursed_amount": "abc"}], FACILITY)
    assert h["總核減點數"] == "1200"
