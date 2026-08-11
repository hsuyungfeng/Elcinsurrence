import os
import pytest
from elc_audit_engine.generators.deduction_print.template import (
    verify_template_hash,
    _load_expected_sha256,
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
    # Placeholder for -k mapping
    pytest.skip("Not implemented yet")

def test_deduction_print_odt():
    # Placeholder for -k odt
    pytest.skip("Not implemented yet")

def test_deduction_print_e2e():
    # Placeholder for -k e2e
    pytest.skip("Not implemented yet")

def test_deduction_print_security():
    # Placeholder for -k security
    pytest.skip("Not implemented yet")
