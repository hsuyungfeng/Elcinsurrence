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

from elc_audit_engine.generators._xmltext import xml_safe

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
        # XML 1.0 非法控制字元會讓整份申復 XML 被拒收（A-WR-07）
        child.text = xml_safe(str(val))


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


class AppealBatchError(ValueError):
    """批次申復資料不合規（缺必要欄位、字數超限、費用年月不一致等）；整批拒絕，不產生殘缺檔。"""


_REASON_FIELD_MAX = 1000  # 單欄上限（官方問答集 Q15：p8／p9 各 1000 字）
_REASON_TOTAL_MAX = 2000  # 合計上限（Q15）
_ATTACHMENT_FLAG = {True: "Y", False: "N"}  # p7：有附件 Y，無附件 N（規格兩值皆需填，不可省略）


def _p6_points(item: dict, label: str) -> int:
    """p6 點數受理：不申復的醫令強制 0（規格：不可漏報）；申復者必須填整數點數。"""
    if not item.get("is_appealing", True):
        return 0
    raw = item.get("claimed_points")
    if raw is None or raw == "":
        raise AppealBatchError(f"{label}：申復醫令缺少申復點數（p6）")
    try:
        points = int(raw)
    except (TypeError, ValueError) as exc:
        raise AppealBatchError(f"{label}：申復點數（p6）須為整數") from exc
    if points < 0:
        raise AppealBatchError(f"{label}：申復點數（p6）不得為負數")
    return points


def _reason_fields(item: dict, label: str) -> tuple[str, str]:
    """p8／p9 申復理由切分：不申復者皆空；超過單欄上限的內容順延至 p9，合計超過 2000 字則拒絕。"""
    if not item.get("is_appealing", True):
        return "", ""
    reason1 = str(item.get("reason1") or "")
    reason2 = str(item.get("reason2") or "")
    if len(reason1) > _REASON_FIELD_MAX:
        reason2 = reason1[_REASON_FIELD_MAX:] + reason2
        reason1 = reason1[:_REASON_FIELD_MAX]
    if len(reason2) > _REASON_FIELD_MAX:
        raise AppealBatchError(f"{label}：申復理由超過合計 {_REASON_TOTAL_MAX} 字上限（p8＋p9）")
    return reason1, reason2


def build_batch_appeal_xml(cases_payload: list[dict]) -> ET.Element:
    """全批次申復 XML（Phase 21-02）：多案件聚合為單一 `<outpatient>`。

    cases_payload 每案格式：{case_class(d1), case_seq(d2), fee_year_month(t2), items: [...]}；
    每筆 item 為一個醫令申復項目：{order_seq(p1), order_code(p2), p3, p4, p5, is_appealing,
    claimed_points(p6), has_attachment(p7), reason1(p8), reason2(p9)}。

    tdata 加總：t38＝申復醫令項目總件數（每筆 pdata 計 1 件）；t39＝全部 p6 點數加總。
    全批次的費用年月（t2）必須一致。任何缺漏或超限都拋 AppealBatchError（fail-fast）。
    """
    if not cases_payload:
        raise AppealBatchError("沒有可導出的申復案件")
    fee_months: set[str] = set()
    ddata_list: list[dict] = []
    total_items = 0
    total_points = 0
    for index, case in enumerate(cases_payload, start=1):
        label = f"案件 {case.get('case_seq') or index}"
        if not case.get("case_class") or not case.get("case_seq"):
            raise AppealBatchError(f"{label}：缺少案件分類（d1）或案件流水號（d2）")
        items = case.get("items") or []
        if not items:
            raise AppealBatchError(f"{label}：沒有醫令申復項目")
        fee_months.add(str(case.get("fee_year_month") or ""))

        pdata_list: list[dict] = []
        for position, item in enumerate(items, start=1):
            item_label = f"{label} 第 {position} 筆醫令"
            if not item.get("order_seq") or not item.get("order_code"):
                raise AppealBatchError(f"{item_label}：缺少醫令序號（p1）或醫令代碼（p2）")
            points = _p6_points(item, item_label)
            reason1, reason2 = _reason_fields(item, item_label)
            pdata_list.append({
                "p1": item["order_seq"],
                "p2": item["order_code"],
                "p3": item.get("p3"),
                "p4": item.get("p4"),
                "p5": item.get("p5"),
                "p6": points,
                "p7": _ATTACHMENT_FLAG[bool(item.get("has_attachment"))],
                "p8": reason1,
                "p9": reason2,
            })
            total_items += 1
            total_points += points
        ddata_list.append({
            "dhead": {"d1": case["case_class"], "d2": case["case_seq"]},
            "dbody": {},
            "pdata_list": pdata_list,
        })

    if len(fee_months) != 1 or "" in fee_months:
        raise AppealBatchError("全批次申復的費用年月（t2）須一致且不可空白")
    tdata = {"t2": fee_months.pop(), "t38": total_items, "t39": total_points}
    return build_appeal_xml(tdata, ddata_list)


def appeal_root_to_big5_bytes(root: ET.Element) -> bytes:
    """序列化為 Big5 位元組（含宣告）。無法以 Big5 表示的字元 fail-fast 拋錯，不靜默替換。"""
    body = ET.tostring(root, encoding="unicode")
    try:
        encoded = body.encode("big5")
    except UnicodeEncodeError as exc:
        bad_char = body[exc.start:exc.end]
        raise AppealXmlEncodingError(
            f"XML 內容含有 Big5 無法編碼之字元 '{bad_char}' (U+{ord(bad_char):04X})，無法導出",
        ) from exc
    return b'<?xml version="1.0" encoding="Big5"?>\r\n' + encoded + b"\r\n"


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
