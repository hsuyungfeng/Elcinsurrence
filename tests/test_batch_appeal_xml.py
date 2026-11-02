"""Phase 21-02 測試：全批次電子申復 XML（t38/t39 加總、p6 強制 0、p7、p8/p9 切分與全形、Big5 fail-fast）。"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile

import pytest

from elc_audit_engine.generators.appeal_xml import (
    AppealBatchError,
    AppealXmlEncodingError,
    appeal_root_to_big5_bytes,
    build_batch_appeal_xml,
    wrap_totfa_zip,
)

KEY = {"X-API-Key": "valid-key-123"}


def _item(**overrides) -> dict:
    base = {
        "order_seq": "1",
        "order_code": "14050B",
        "is_appealing": True,
        "claimed_points": 100,
        "has_attachment": False,
        "reason1": "理由一",
        "reason2": "理由二",
    }
    base.update(overrides)
    return base


def _case(case_seq: str, items: list[dict], **overrides) -> dict:
    base = {"case_class": "03", "case_seq": case_seq, "fee_year_month": "202307", "items": items}
    base.update(overrides)
    return base


def _parse(root: ET.Element) -> ET.Element:
    """與健保端一致：Big5 位元組 → 文字 → 解析（stdlib expat 不支援 Big5，需先解碼）。"""
    body = appeal_root_to_big5_bytes(root).decode("big5")
    return ET.fromstring(re.sub(r"^<\?xml[^>]*\?>", "", body).strip())


# ── t38／t39 加總 ───────────────────────────────────────────


def test_t38_counts_items_and_t39_sums_points_across_cases():
    root = build_batch_appeal_xml([
        _case("1", [_item(claimed_points=100), _item(order_seq="2", claimed_points=50)]),
        _case("2", [_item(claimed_points=30)]),
    ])
    tdata = root.find("tdata")
    assert tdata.find("t38").text == "3"
    assert tdata.find("t39").text == "180"
    assert tdata.find("t2").text == "202307"
    assert len(root.findall("ddata")) == 2
    assert len(root.findall("ddata/dbody/pdata")) == 3


def test_t39_excludes_points_of_items_not_appealed():
    root = build_batch_appeal_xml([
        _case("1", [_item(claimed_points=100), _item(order_seq="2", is_appealing=False, claimed_points=999)]),
    ])
    assert root.find("tdata/t39").text == "100"


# ── p6 強制 0、p7 Y/N ───────────────────────────────────────


def test_not_appealed_item_has_p6_zero_and_no_reasons():
    root = build_batch_appeal_xml([
        _case("1", [_item(is_appealing=False, claimed_points=None, reason1="不應出現", reason2="也不應")]),
    ])
    pdata = root.find("ddata/dbody/pdata")
    assert pdata.find("p6").text == "0"
    assert pdata.find("p8") is None
    assert pdata.find("p9") is None


def test_p7_is_y_when_attachment_else_n():
    root = build_batch_appeal_xml([
        _case("1", [_item(has_attachment=True), _item(order_seq="2", has_attachment=False)]),
    ])
    flags = [p.find("p7").text for p in root.findall("ddata/dbody/pdata")]
    assert flags == ["Y", "N"]


def test_appealed_item_without_points_is_rejected():
    with pytest.raises(AppealBatchError, match="p6"):
        build_batch_appeal_xml([_case("1", [_item(claimed_points=None)])])


def test_non_integer_points_are_rejected():
    with pytest.raises(AppealBatchError, match="整數"):
        build_batch_appeal_xml([_case("1", [_item(claimed_points="很多")])])


# ── p8／p9 切分與長度上限 ───────────────────────────────────


def test_overflow_of_first_reason_moves_to_second_field():
    long_reason = "甲" * 1200
    root = build_batch_appeal_xml([_case("1", [_item(reason1=long_reason, reason2="乙")])])
    pdata = root.find("ddata/dbody/pdata")
    assert len(pdata.find("p8").text) == 1000
    assert pdata.find("p9").text == "甲" * 200 + "乙"


def test_combined_reason_over_limit_is_rejected():
    with pytest.raises(AppealBatchError, match="2000"):
        build_batch_appeal_xml([_case("1", [_item(reason1="甲" * 1000, reason2="乙" * 1001)])])


def test_limit_is_counted_in_big5_bytes_not_characters():
    # 1000 個中文字 = 2000 bytes：剛好不溢出
    root = build_batch_appeal_xml([_case("1", [_item(reason1="甲" * 1000, reason2="")])])
    pdata = root.find("ddata/dbody/pdata")
    assert pdata.find("p8").text == "甲" * 1000
    assert pdata.find("p9") is None
    # 1001 個中文字 = 2002 bytes：溢出 2 bytes，末一字順延至 p9
    root = build_batch_appeal_xml([_case("1", [_item(reason1="甲" * 1001, reason2="")])])
    pdata = root.find("ddata/dbody/pdata")
    assert pdata.find("p8").text == "甲" * 1000
    assert pdata.find("p9").text == "甲"


def test_fullwidth_conversion_counts_toward_byte_limit():
    # 半形 "<" 為 1 byte，轉全形「＜」為 2 bytes：1000 個 "<" 轉換後剛好 2000 bytes
    root = build_batch_appeal_xml([_case("1", [_item(reason1="<" * 1000, reason2="")])])
    pdata = root.find("ddata/dbody/pdata")
    assert pdata.find("p8").text == "＜" * 1000
    assert pdata.find("p9") is None
    root = build_batch_appeal_xml([_case("1", [_item(reason1="<" * 1001, reason2="")])])
    assert root.find("ddata/dbody/pdata/p9").text == "＜"


def test_wrap_totfa_zip_contains_exactly_one_totfa_xml():
    with zipfile.ZipFile(io.BytesIO(wrap_totfa_zip(b"<outpatient/>"))) as archive:
        assert archive.namelist() == ["TOTFA.xml"]
        assert archive.read("TOTFA.xml") == b"<outpatient/>"


# ── 全形特殊字元 ────────────────────────────────────────────


def test_special_characters_in_reasons_become_fullwidth():
    root = build_batch_appeal_xml([_case("1", [_item(reason1='a<b>&c\'d"e', reason2="x")])])
    text = root.find("ddata/dbody/pdata/p8").text
    assert text == "a＜b＞＆c＇d＂e"
    for half in "<>&'\"":
        assert half not in text


# ── 批次一致性 ─────────────────────────────────────────────


def test_fee_year_month_must_match_across_cases():
    with pytest.raises(AppealBatchError, match="費用年月"):
        build_batch_appeal_xml([
            _case("1", [_item()]),
            _case("2", [_item()], fee_year_month="202308"),
        ])


def test_missing_case_identity_is_rejected():
    with pytest.raises(AppealBatchError, match="流水號"):
        build_batch_appeal_xml([_case("", [_item()])])


def test_missing_order_identity_is_rejected():
    with pytest.raises(AppealBatchError, match="醫令序號"):
        build_batch_appeal_xml([_case("1", [_item(order_seq=None)])])


def test_empty_batch_is_rejected():
    with pytest.raises(AppealBatchError):
        build_batch_appeal_xml([])


# ── Big5 fail-fast ─────────────────────────────────────────


def test_big5_output_round_trips_and_declares_encoding():
    root = build_batch_appeal_xml([_case("1", [_item(reason1="中文理由")])])
    raw = appeal_root_to_big5_bytes(root)
    assert raw.startswith(b'<?xml version="1.0" encoding="Big5"?>')
    assert _parse(root).find("ddata/dbody/pdata/p8").text == "中文理由"


def test_unencodable_character_fails_fast_and_names_the_codepoint():
    root = build_batch_appeal_xml([_case("1", [_item(reason1="表情😀")])])
    with pytest.raises(AppealXmlEncodingError, match="U\\+1F600"):
        appeal_root_to_big5_bytes(root)


# ── 端點 ───────────────────────────────────────────────────


@pytest.fixture
def api(make_api_app):
    return make_api_app()


@pytest.fixture
def client(api):
    with api.test_client() as c:
        yield c


def test_export_endpoint_is_404_without_appeals(client):
    res = client.get("/api/appeal/export-batch-xml", headers=KEY)
    assert res.status_code == 404


def test_export_endpoint_returns_big5_attachment(client, api):
    store = api.extensions["elc"].case_store
    store.create(
        case_id="APL-T-1",
        kind="appeal",
        payload={
            "case_class": "03", "case_seq": "1", "fee_year_month": "202307",
            "order_seq": "1", "order_code": "14050B", "claimed_points": 120,
            "is_appealing": True, "has_attachment": True,
            "appeal_reason1": "理由", "appeal_reason2": "",
        },
    )
    res = client.get("/api/appeal/export-batch-xml", headers=KEY)
    assert res.status_code == 200
    assert res.headers["Content-Disposition"] == 'attachment; filename="TOTFA.zip"'
    with zipfile.ZipFile(io.BytesIO(res.data)) as archive:
        assert archive.namelist() == ["TOTFA.xml"]
        inner = archive.read("TOTFA.xml")
    root = ET.fromstring(re.sub(r"^<\?xml[^>]*\?>", "", inner.decode("big5")).strip())
    assert root.find("tdata/t38").text == "1"
    assert root.find("tdata/t39").text == "120"
    assert root.find("ddata/dbody/pdata/p7").text == "Y"


def test_export_endpoint_is_422_when_points_not_yet_filled(client, api):
    """Stage2 連動產生的申復案件尚未由醫師填寫申復點數 → 整批拒絕，不以推測值送審。"""
    store = api.extensions["elc"].case_store
    store.create(
        case_id="APL-T-2",
        kind="appeal",
        payload={
            "case_class": "03", "case_seq": "2", "fee_year_month": "202307",
            "order_seq": "1", "order_code": "14050B", "claimed_points": None,
            "appeal_reason1": "", "appeal_reason2": "",
        },
    )
    res = client.get("/api/appeal/export-batch-xml", headers=KEY)
    assert res.status_code == 422
    assert "APL-T-2" not in res.get_json()["message"]  # 訊息點名醫令，不洩漏案件 ID 以外的 PHI
    assert "p6" in res.get_json()["message"]
