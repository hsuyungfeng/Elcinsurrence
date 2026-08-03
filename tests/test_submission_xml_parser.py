"""申報 XML 解析器測試（03-01-PLAN Task 1/4）。

涵蓋：D-01 編碼偵測與回退、D-02 未知欄位保留、D-03 次診斷清單、
D-04 CRLF、D-05 致命缺漏三種、D-06 d19 只警告、D-07 回傳形狀、
D-08 高出現率欄位警告、D-09 不查規則庫、真實檔回放（選用 skip）。
"""

import os
import re

import pytest

from elc_audit_engine.parsers.submission_xml import (
    SubmissionXmlError,
    decode_xml_bytes,
    parse_submission_xml,
    parse_submission_xml_bytes,
    parse_submission_xml_text,
)

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "submission_sample.xml"
)
REAL_FILE = os.path.join(os.path.dirname(__file__), "..", "TOTFA.xml")

_BIG5_XML = (
    '<?xml version="1.0" encoding="Big5"?>\r\n'
    "<outpatient>\r\n"
    "<tdata><t2>3503250461</t2></tdata>\r\n"
    "<ddata><dhead><d1>02</d1><d2>1</d2></dhead><dbody>"
    "<d3>M220518024</d3><d19>S90221A</d19><d49>陳李媚</d49>"
    "<pdata><p1>3</p1><p4>AC37603100</p4><p13>1</p13></pdata>"
    "</dbody></ddata>\r\n"
    "</outpatient>\r\n"
)


def test_decode_big5_with_chinese_name():
    """D-01：Big5 宣告 + 中文姓名可正確解碼（ElementTree 原生無法處理 Big5）。"""
    decoded = decode_xml_bytes(_BIG5_XML.encode("big5"))
    assert "陳李媚" in decoded


def test_decode_fallback_utf8_without_declaration():
    """D-01：無 encoding 宣告的 utf-8 內容可回退解碼。"""
    raw = (
        '<?xml version="1.0"?><outpatient><tdata></tdata></outpatient>'
    ).encode("utf-8")
    assert "outpatient" in decode_xml_bytes(raw)


def test_decode_total_failure_raises():
    """D-01：全部編碼皆失敗時拋 SubmissionXmlError，不靜默回傳亂碼。"""
    with pytest.raises(SubmissionXmlError):
        decode_xml_bytes(b"\xff\xfe\x00\x01\x02invalid-bytes\xff\xff\xff\xff")


def test_parse_fixture_counts_and_header():
    """D-07：fixture（4 案）解析：cases=4、rejected=0、tdata 14 欄。"""
    result = parse_submission_xml(FIXTURE)
    assert len(result.cases) == 4
    assert result.rejected == ()
    assert result.header["t2"] == "3503250461"
    assert result.header["t3"] == "11207"


def test_parse_fixture_secondary_diagnoses():
    """D-03：d20-d22 次診斷依序收集為 secondary_diagnoses。"""
    result = parse_submission_xml(FIXTURE)
    by_key = {(c.case_class, c.case_seq): c for c in result.cases}
    case = by_key[("02", "2")]
    assert case.secondary_diagnoses == ("S67191A", "S61102A", "S61301A")
    assert case.primary_diagnosis == "S6702XA"


def test_parse_fixture_single_order_case():
    """單醫令案（d1=09, d2=28）：orders=1、p4=48010C。"""
    result = parse_submission_xml(FIXTURE)
    by_key = {(c.case_class, c.case_seq): c for c in result.cases}
    case = by_key[("09", "28")]
    assert len(case.orders) == 1
    assert case.orders[0].code == "48010C"
    assert case.orders[0].seq == "1"


def test_parse_fixture_patient_name_deidentified():
    """D-20：fixture 的 d49 姓名已置換為測試姓名（不應殘留真實姓名）。"""
    result = parse_submission_xml(FIXTURE)
    names = {c.patient_name for c in result.cases}
    assert names == {"測試患者甲", "測試患者乙", "測試患者丙", "測試患者丁"}


def test_parse_fixture_raw_preserves_unknown_fields():
    """D-02：未知欄位（d57/p24/p8）保留於 raw，不丟棄。"""
    result = parse_submission_xml(FIXTURE)
    by_key = {(c.case_class, c.case_seq): c for c in result.cases}

    case_multi = by_key[("02", "2")]
    assert case_multi.raw["d57"] == "150"

    case_p24 = by_key[("03", "1")]
    assert any("p24" in o.raw for o in case_p24.orders)
    assert case_p24.treatment_end_date is None  # 該案無 d10（正常可空）

    case_p8 = by_key[("02", "1")]
    assert any("p8" in o.raw for o in case_p8.orders)


def test_parse_big5_bytes_with_declaration():
    """D-01/D-04：Big5 宣告 + CRLF 內容直接以 bytes 解析。"""
    result = parse_submission_xml_bytes(_BIG5_XML.encode("big5"))
    assert len(result.cases) == 1
    case = result.cases[0]
    assert case.record_no == "M220518024"
    assert case.patient_name == "陳李媚"
    assert case.orders[0].code == "AC37603100"
    assert case.orders[0].days == "3"


def test_parse_rejects_missing_d1_d2():
    """D-05：缺 d1/d2 → rejected，原因明確。"""
    xml = (
        "<outpatient><tdata></tdata><ddata><dhead><d1></d1></dhead>"
        "<dbody><d3>X</d3><pdata><p4>A</p4></pdata></dbody></ddata></outpatient>"
    )
    result = parse_submission_xml_text(xml)
    assert len(result.rejected) == 1
    assert "d1/d2" in result.rejected[0].reason
    assert result.cases == ()


def test_parse_rejects_missing_d3():
    """D-05：缺 d3 → rejected（無法對應病歷）。"""
    xml = (
        "<outpatient><tdata></tdata><ddata><dhead><d1>02</d1><d2>1</d2></dhead>"
        "<dbody><d19>S90221A</d19><pdata><p4>A</p4></pdata></dbody></ddata></outpatient>"
    )
    result = parse_submission_xml_text(xml)
    assert len(result.rejected) == 1
    assert "d3" in result.rejected[0].reason


def test_parse_rejects_no_pdata():
    """D-05：整案無 pdata → rejected（沒有醫令就沒有東西可比對）。"""
    xml = (
        "<outpatient><tdata></tdata><ddata><dhead><d1>02</d1><d2>1</d2></dhead>"
        "<dbody><d3>M1</d3><d19>S90221A</d19></dbody></ddata></outpatient>"
    )
    result = parse_submission_xml_text(xml)
    assert len(result.rejected) == 1
    assert "pdata" in result.rejected[0].reason


def test_missing_d19_warns_but_accepts():
    """D-06：缺 d19 只警告不拒收。"""
    xml = (
        "<outpatient><tdata></tdata><ddata><dhead><d1>02</d1><d2>1</d2></dhead>"
        "<dbody><d3>M1</d3><pdata><p4>A</p4></pdata></dbody></ddata></outpatient>"
    )
    result = parse_submission_xml_text(xml)
    assert len(result.cases) == 1
    assert any("d19" in w for w in result.cases[0].warnings)


def test_high_occurrence_missing_warns():
    """D-08：高出現率欄位（如 d8 就醫科別）缺席發警告。"""
    xml = (
        "<outpatient><tdata></tdata><ddata><dhead><d1>02</d1><d2>1</d2></dhead>"
        "<dbody><d3>M1</d3><d19>S90221A</d19><pdata><p4>A</p4></pdata></dbody></ddata></outpatient>"
    )
    result = parse_submission_xml_text(xml)
    assert len(result.cases) == 1
    assert any("d8" in w for w in result.cases[0].warnings)


def test_mixed_rejected_and_accepted():
    """D-07：一檔中 1 案壞掉不阻斷其他案。"""
    xml = (
        "<outpatient><tdata></tdata>"
        "<ddata><dhead><d1>02</d1><d2>1</d2></dhead>"
        "<dbody><d3>M1</d3><d19>S1</d19><pdata><p4>A</p4></pdata></dbody></ddata>"
        "<ddata><dhead><d1>02</d1></dhead>"
        "<dbody><d3>M2</d3><d19>S1</d19><pdata><p4>B</p4></pdata></dbody></ddata>"
        "</outpatient>"
    )
    result = parse_submission_xml_text(xml)
    assert len(result.cases) == 1
    assert len(result.rejected) == 1


def test_crlf_content_parses():
    """D-04：CRLF 行尾不影響解析。"""
    xml = (
        "<outpatient>\r\n<tdata><t2>X</t2></tdata>\r\n"
        "<ddata><dhead><d1>02</d1><d2>1</d2></dhead><dbody>"
        "<d3>M1</d3><d19>S1</d19><pdata><p4>A</p4><p13>1</p13></pdata>"
        "</dbody></ddata>\r\n</outpatient>\r\n"
    )
    result = parse_submission_xml_text(xml)
    assert len(result.cases) == 1
    assert result.cases[0].orders[0].code == "A"


def test_wrong_root_element_raises():
    """結構錯誤（根元素非 outpatient）拋 SubmissionXmlError。"""
    with pytest.raises(SubmissionXmlError):
        parse_submission_xml_text("<hospital></hospital>")


def test_missing_file_raises():
    """讀檔失敗拋 SubmissionXmlError。"""
    with pytest.raises(SubmissionXmlError):
        parse_submission_xml("/nonexistent/path/foo.xml")


def test_parser_does_not_import_rule_repository():
    """D-09：解析器不 import rule_repository（純轉換層）。"""
    import sys

    src = os.path.join(os.path.dirname(__file__), "..", "src")
    sys.path.insert(0, src)
    try:
        import elc_audit_engine.parsers.submission_xml as mod

        source = open(mod.__file__, encoding="utf-8").read()
        assert "rule_repository" not in source
        assert "get_rule" not in source
    finally:
        sys.path.remove(src)


@pytest.mark.skipif(
    not os.path.isfile(REAL_FILE), reason="真實 TOTFA.xml 未在專案根目錄（gitignored）"
)
def test_real_file_replay_counts():
    """真實檔回放：633 案 / 0 拒收 / 2624 醫令 / tdata 14 欄。"""
    result = parse_submission_xml(REAL_FILE)
    assert len(result.cases) == 633
    assert result.rejected == ()
    assert sum(len(c.orders) for c in result.cases) == 2624
    assert len(result.header) == 14


def test_parse_text_with_chinese_no_declaration():
    """parse_submission_xml_text 直接以 str 解析中文內容（不經編碼偵測，避免誤解碼）。"""
    xml = (
        "<outpatient><tdata></tdata><ddata><dhead><d1>02</d1><d2>1</d2></dhead>"
        "<dbody><d3>M1</d3><d19>S90221A</d19><d49>測試患者</d49>"
        "<pdata><p4>A</p4></pdata></dbody></ddata></outpatient>"
    )
    result = parse_submission_xml_text(xml)
    assert len(result.cases) == 1
    assert result.cases[0].patient_name == "測試患者"
