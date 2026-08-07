"""Unit tests for appeal_xml generator."""

import xml.etree.ElementTree as ET
import pytest

from elc_audit_engine.generators.appeal_xml import (
    AppealXmlEncodingError,
    _to_fullwidth_specials,
    build_appeal_xml,
    draft_json_to_appeal_xml_fields,
    write_appeal_xml,
)


def test_to_fullwidth_specials_converts_five_characters():
    raw = "<tagattr='foo'&\"bar\">"
    res = _to_fullwidth_specials(raw)
    assert res == "＜tagattr=＇foo＇＆＂bar＂＞"


def test_to_fullwidth_specials_none_and_empty():
    assert _to_fullwidth_specials(None) == ""
    assert _to_fullwidth_specials("") == ""


def test_build_appeal_xml_omits_none_fields():
    tdata = {"t1": "100", "t2": None, "t3": ""}
    ddata_list = [
        {
            "dhead": {"d1": "01", "d2": None},
            "dbody": {},
            "pdata_list": [{"p1": "1", "p2": None, "p8": "申復理由<1>"}],
        }
    ]
    root = build_appeal_xml(tdata, ddata_list)
    assert root.tag == "outpatient"

    tdata_el = root.find("tdata")
    assert tdata_el is not None
    assert tdata_el.find("t1") is not None
    assert tdata_el.find("t2") is None
    assert tdata_el.find("t3") is None

    pdata_el = root.find("ddata/dbody/pdata")
    assert pdata_el is not None
    assert pdata_el.find("p1").text == "1"
    assert pdata_el.find("p2") is None
    assert pdata_el.find("p8").text == "申復理由＜1＞"  # converted to fullwidth


def test_write_appeal_xml_big5_roundtrip(tmp_path):
    tdata = {"t1": "9999", "t2": "11507"}
    ddata_list = [
        {
            "dhead": {"d1": "01", "d2": "101"},
            "dbody": {},
            "pdata_list": [{"p1": "1", "p2": "14050B", "p8": "醫師主張測試病患醫療必要性"}],
        }
    ]
    root = build_appeal_xml(tdata, ddata_list)
    output_file = str(tmp_path / "test_appeal.xml")
    write_appeal_xml(root, output_file)

    with open(output_file, "r", encoding="big5") as f:
        xml_text = f.read()
        assert "encoding" in xml_text.lower() and "big5" in xml_text.lower()
        parsed_root = ET.fromstring(xml_text)

    assert parsed_root.find("tdata/t1").text == "9999"
    assert parsed_root.find("ddata/dbody/pdata/p8").text == "醫師主張測試病患醫療必要性"


def test_write_appeal_xml_raises_on_unencodable_char(tmp_path):
    tdata = {"t1": "100"}
    # Emoji or rare character not present in Big5
    ddata_list = [
        {
            "dhead": {"d1": "01"},
            "dbody": {},
            "pdata_list": [{"p1": "1", "p8": "測試 🚀 emoji"}],
        }
    ]
    root = build_appeal_xml(tdata, ddata_list)
    output_file = str(tmp_path / "test_fail.xml")
    with pytest.raises(AppealXmlEncodingError) as exc_info:
        write_appeal_xml(root, output_file)
    assert "Big5 無法編碼" in str(exc_info.value)


def test_draft_json_to_appeal_xml_fields():
    appeal_json = {
        "case_class": "01",
        "case_seq": "201",
        "fee_year_month": "11507",
        "p1_order_seq": "1",
        "p2_order_code": "14050B",
        "p3_change_seq": None,
        "p4_rate": None,
        "p5_quantity": None,
        "p6_points": 0,
        "p7_attachment": "N",
        "p8_reason1": "理由一",
        "p9_reason2": "理由二",
    }
    tdata, ddata_list = draft_json_to_appeal_xml_fields(appeal_json)
    assert tdata["t2"] == "11507"
    assert len(ddata_list) == 1
    dhead = ddata_list[0]["dhead"]
    assert dhead["d1"] == "01"
    assert dhead["d2"] == "201"
    pdata = ddata_list[0]["pdata_list"][0]
    assert pdata["p1"] == "1"
    assert pdata["p2"] == "14050B"
    assert pdata["p3"] is None
    assert pdata["p8"] == "理由一"


def test_cli_build_appeal_xml_success(tmp_path):
    import json
    from scripts.build_appeal_xml import main

    json_file = tmp_path / "appeal_18.json"
    appeal_json = {
        "case_class": "01",
        "case_seq": "18",
        "fee_year_month": "11507",
        "p1_order_seq": "1",
        "p2_order_code": "14050B",
        "p8_reason1": "申復理由",
    }
    json_file.write_text(json.dumps(appeal_json), encoding="utf-8")

    ret = main([str(json_file)])
    assert ret == 0

    xml_file = tmp_path / "appeal_18.xml"
    assert xml_file.exists()
    with open(xml_file, "r", encoding="big5") as f:
        root = ET.fromstring(f.read())
        assert root.find("ddata/dhead/d2").text == "18"


def test_cli_build_appeal_xml_missing_args():
    from scripts.build_appeal_xml import main
    assert main([]) == 1


def test_cli_build_appeal_xml_nonexistent_file():
    from scripts.build_appeal_xml import main
    assert main(["nonexistent.json"]) == 1


def test_cli_build_appeal_xml_invalid_json(tmp_path):
    from scripts.build_appeal_xml import main
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not json", encoding="utf-8")
    assert main([str(bad_file)]) == 1


def test_cli_build_appeal_xml_custom_output_path(tmp_path):
    import json
    from scripts.build_appeal_xml import main

    json_file = tmp_path / "input.json"
    out_file = tmp_path / "custom_output.xml"
    json_file.write_text(json.dumps({"case_class": "01"}), encoding="utf-8")

    ret = main([str(json_file), str(out_file)])
    assert ret == 0
    assert out_file.exists()
