"""Package Builder — 申復 XML 序列化器與格式轉換。

把 appeal_{流水號}.json（Phase 7 產出，含 p1-p9 醫令段欄位）序列化為
健保署申復上傳格式 XML（<outpatient><tdata>...</tdata><ddata><dhead>...
</dhead><dbody>...<pdata>...</pdata></dbody></ddata></outpatient>）。

範圍限 tdata+ddata+pdata（單筆醫令申復，不含 edata 統扣段——2026-08-07 使用者裁示）。
產出方式為背景腳本 scripts/build_appeal_xml.py。
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

_FULLWIDTH_MAP = str.maketrans({
    "<": "＜",
    ">": "＞",
    "&": "＆",
    "'": "＇",
    '"': "＂",
})


class AppealXmlEncodingError(ValueError):
    """Big5 無法編碼時拋出此例外（包含欄位脈絡與字元碼位，不包含 PHI 全文）。"""

    def __init__(self, message: str, field_name: str | None = None):
        super().__init__(message)
        self.field_name = field_name


def _to_fullwidth_specials(text: str | None) -> str:
    """將半形特殊字元 (< > & ' ") 轉換為全形 (＜ ＞ ＆ ＇ ＂)。

    依據官方【表8】特殊字元處理規則。
    """
    if text is None:
        return ""
    return str(text).translate(_FULLWIDTH_MAP)


def _add_fields(parent: ET.Element, fields: dict[str, object]) -> None:
    """將 fields 逐鍵新增為 parent 的子元素。

    規則：若值為 None 或空字串，跳過不輸出標籤（無資料不輸出標籤規則）。
    """
    for key, val in fields.items():
        if val is None or val == "":
            continue
        child = ET.SubElement(parent, key)
        child.text = str(val)


def build_appeal_xml(
    tdata: dict,
    ddata_list: list[dict],
    *,
    fullwidth_fields: frozenset[str] = frozenset({"p8", "p9"}),
) -> ET.Element:
    """建構申復 XML ElementTree (outpatient 根節點)。

    tdata: 包含 t1-t5 (或 t1-t37) 欄位的字典。
    ddata_list: 包含 dhead, dbody, pdata_list 的字典清單。
    """
    root = ET.Element("outpatient")

    tdata_el = ET.SubElement(root, "tdata")
    _add_fields(tdata_el, tdata)

    for entry in ddata_list:
        ddata_el = ET.SubElement(root, "ddata")

        dhead = entry.get("dhead", {})
        if dhead:
            dhead_el = ET.SubElement(ddata_el, "dhead")
            _add_fields(dhead_el, dhead)

        dbody = entry.get("dbody", {})
        dbody_el = ET.SubElement(ddata_el, "dbody")
        if dbody:
            _add_fields(dbody_el, dbody)

        for pdata in entry.get("pdata_list", []):
            pdata_el = ET.SubElement(dbody_el, "pdata")
            pdata_processed = {}
            for k, v in pdata.items():
                if k in fullwidth_fields and v is not None and v != "":
                    pdata_processed[k] = _to_fullwidth_specials(str(v))
                else:
                    pdata_processed[k] = v
            _add_fields(pdata_el, pdata_processed)

    return root


def write_appeal_xml(root: ET.Element, path: str) -> None:
    """將 ElementTree 寫入為 Big5 編碼的 XML 檔案 (宣告 <?xml version="1.0" encoding="Big5"?>)。

    如果含有 Big5 無法編碼的字元，fail-fast 拋出 AppealXmlEncodingError。
    """
    # 先測試全樹的 Big5 編碼相容性
    xml_unicode = ET.tostring(root, encoding="unicode")
    try:
        xml_unicode.encode("big5")
    except UnicodeEncodeError as exc:
        bad_char = xml_unicode[exc.start:exc.end]
        code_point = f"U+{ord(bad_char):04X}"
        raise AppealXmlEncodingError(
            f"XML 內容含有 Big5 無法編碼之字元 '{bad_char}' ({code_point})，無法寫檔",
        ) from exc

    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    tree = ET.ElementTree(root)
    tree.write(path, encoding="big5", xml_declaration=True)


def draft_json_to_appeal_xml_fields(appeal_json: dict) -> tuple[dict, list[dict]]:
    """將 render_appeal_json() 產出的 JSON dict 轉換為 build_appeal_xml() 的入參。"""
    tdata = {
        "t2": appeal_json.get("fee_year_month"),
    }

    pdata = {
        "p1": appeal_json.get("p1_order_seq") or appeal_json.get("order_seq"),
        "p2": appeal_json.get("p2_order_code") or appeal_json.get("order_code"),
        "p3": appeal_json.get("p3_change_seq"),
        "p4": appeal_json.get("p4_rate"),
        "p5": appeal_json.get("p5_quantity"),
        "p6": appeal_json.get("p6_points"),
        "p7": appeal_json.get("p7_attachment"),
        "p8": appeal_json.get("p8_reason1"),
        "p9": appeal_json.get("p9_reason2"),
    }

    dhead = {
        "d1": appeal_json.get("case_class"),
        "d2": appeal_json.get("case_seq"),
    }

    entry = {
        "dhead": dhead,
        "dbody": {},
        "pdata_list": [pdata],
    }

    return tdata, [entry]
