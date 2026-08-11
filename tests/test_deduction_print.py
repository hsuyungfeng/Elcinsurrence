import os
import pytest
from elc_audit_engine.generators.deduction_print.template import (
    verify_template_hash,
    _load_expected_sha256,
)
from elc_audit_engine.generators.deduction_print.field_mapping import (
    build_deduction_header,
    build_deduction_rows,
)

PRINT_BASE_ODT = os.path.join(
    os.path.dirname(__file__),
    "../officialdocument/電子申復文件格式/RCPI2012R01_核減明細表_print_base.odt",
)

def test_verify_template_hash():
    # Wave 0 test skeleton
    if os.path.isfile(PRINT_BASE_ODT):
        expected = _load_expected_sha256(PRINT_BASE_ODT)
        verify_template_hash(PRINT_BASE_ODT, expected)

def test_deduction_print_mapping():
    records = [{
        "institution_code": "000001",
        "fee_year_month": "202310",
        "submit_date": "20231105",
        "case_class": "01",
        "chart_no": "A001",
        "visit_date": "20231001",
        "id_number": "A123456789",
        "birth_date": "19900101",
        "order_seq": "001",
        "order_code": "12345C",
        "claimed_points": "100",
        "total_qty": "1",
        "non_reimbursed_amount": "50",
        "appeal_item_code": "X01",
        "appeal_item_desc": "Not needed"
    }]
    facility = {"facility_name": "Test Clinic"}
    
    header = build_deduction_header(records, facility)
    assert header["醫療院所名稱"] == "Test Clinic"
    assert header["費用年月"] == "112年10月"
    assert header["申請申報日期"] == "112年11月5日"
    assert header["核減件數"] == "1"
    assert header["總核減點數"] == "50"
    
    rows, warnings = build_deduction_rows(records)
    assert len(rows) == 1
    assert "缺病患姓名" in warnings[0]
    assert "缺醫令名稱" in warnings[1]
    
    row = rows[0]
    assert "****" in row["身分證號/出生日期"]
    assert "A12345****" in row["身分證號/出生日期"]
    assert row["案件分類/病歷號"] == "01 / A001"
    assert row["不予核銷金額/核減點數"] == "50"

def test_deduction_print_odt():
    # Placeholder for -k odt
    pytest.skip("Not implemented yet")

def test_deduction_print_e2e():
    # Placeholder for -k e2e
    pytest.skip("Not implemented yet")

def test_deduction_print_security():
    # Placeholder for -k security
    pytest.skip("Not implemented yet")
