"""B-WR-21：無宣告的 UTF-8 不得被 big5 誤解碼；編碼回退寫入 warnings。"""
from elc_audit_engine.parsers.submission_xml import parse_submission_xml_bytes

BODY = "<outpatient><tdata><t1>30</t1></tdata><ddata><dhead><d1>01</d1><d2>1</d2></dhead><dbody><d3>M1</d3><d49>林小明</d49></dbody></ddata></outpatient>"


def test_undeclared_utf8_decoded_as_utf8_with_warning():
    res = parse_submission_xml_bytes(BODY.encode("utf-8"))
    assert any("未宣告編碼，以 utf-8" in w for w in res.warnings)
    from elc_audit_engine.parsers.submission_xml import _decode_with_info

    text, used, declared = _decode_with_info(BODY.encode("utf-8"))
    assert used == "utf-8" and declared is None
    assert "林小明" in text


def test_declared_big5_no_warning():
    raw = ('<?xml version="1.0" encoding="Big5"?>' + BODY).encode("big5")
    res = parse_submission_xml_bytes(raw)
    assert res.warnings == ()
