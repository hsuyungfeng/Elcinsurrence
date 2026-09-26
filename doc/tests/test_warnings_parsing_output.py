"""Warning 第一批（續）：解析與送件文字正確性（B-WR-01/02/03/04、A-WR-07/10）。"""
import xml.etree.ElementTree as ET

import pytest

from elc_audit_engine.generators._xmltext import set_odf_paragraph_text, xml_safe
from elc_audit_engine.generators.appeal import MAX_TOTAL_CHARS, build_appeal_draft
from elc_audit_engine.parsers.deduction import AmountParseError, _parse_int, parse_deduction_file
from elc_audit_engine.parsers.models import DeductionRecord
from elc_audit_engine.parsers.soap import parse_soap_text


@pytest.mark.parametrize("raw, expected", [("0000000300", 300), ("1,200", 1200), ("300.0", 300), ("", None)])
def test_parse_int_accepts_integer_forms(raw, expected):
    assert _parse_int(raw) == expected


@pytest.mark.parametrize("raw", ["300.7", "inf", "1e400", "abc"])
def test_parse_int_rejects_non_integer(raw):
    with pytest.raises(AmountParseError):
        _parse_int(raw)


def _row(amount="0000000300", note="院所說明"):
    cells = [amount, "01015C", "202607", "20260801", "01", "12", "20260710", "19800101",
             "A12345****", "1", "64140C", "20260710", "北區", "300", "20260901",
             "追扣原因", "A-說明", note]
    return cells


def test_row_with_fractional_amount_is_rejected_not_truncated(tmp_path):
    f = tmp_path / "d.csv"
    f.write_text(",".join(_row()) + "\n" + ",".join(_row("300.7")) + "\n", encoding="utf-8")
    res = parse_deduction_file(str(f))
    assert [r.non_reimbursed_amount for r in res.records] == [300]
    assert len(res.rejected) == 1 and "非整數" in res.rejected[0].reason


def test_semicolons_in_free_text_do_not_flip_delimiter(tmp_path):
    """B-WR-02"""
    f = tmp_path / "d.csv"
    rows = [",".join(_row(note="說明;補充;再補充;又補充")) for _ in range(3)]
    f.write_text("\n".join(rows) + "\n", encoding="utf-8")
    res = parse_deduction_file(str(f))
    assert res.delimiter_used == ","
    assert len(res.records) == 3


def test_pulse_line_is_not_plan_marker():
    """B-WR-03"""
    doc = parse_soap_text("S: 頭痛\nO: BP 120/80\nP: 88/min\nP: 兩週後回診")
    assert doc.sections["P"] == ("兩週後回診",)
    assert "P: 88/min" in doc.sections["O"][0]


def test_decimal_numbers_not_split_into_sentences():
    """B-WR-04"""
    texts = [s.text for s in parse_soap_text("體溫36.5度. 開立藥物").segments]
    assert texts == ["體溫36.5度", "開立藥物"]


def test_xml_safe_strips_control_chars():
    """A-WR-07"""
    assert xml_safe("a\x00b\x0bc\td\ne") == "abc\td\ne"


def test_odf_paragraph_uses_line_breaks():
    """A-WR-10：ODT 換行以 text:line-break 表示。"""
    p = ET.Element("{urn:oasis:names:tc:opendocument:xmlns:text:1.0}p")
    set_odf_paragraph_text(p, "第一行\n第二行\x01")
    assert p.text == "第一行"
    assert len(p) == 1 and p[0].tail == "第二行"


def test_appeal_reason_keeps_section_labels_and_limit():
    """A-WR-10：p8 保留段落標籤；含標籤仍不超過 2000 字。"""
    record = DeductionRecord(case_seq="1", order_code="64140C", non_reimbursed_amount=300)
    draft = build_appeal_draft(
        record, claimed_points=300, rule_text="條文", rule_location="處",
        evidence=[{"text": "證" * 40, "rule_location": None} for _ in range(80)],
    )
    full = draft.reason1 + draft.reason2
    assert "①案情摘要：" in full and "\n③規則依據：" in full
    assert draft.total_chars == len(full) <= MAX_TOTAL_CHARS
