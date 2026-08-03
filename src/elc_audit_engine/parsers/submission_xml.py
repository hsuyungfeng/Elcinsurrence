"""申報 XML 解析器（tdata/ddata/pdata）→ SubmissionParseResult。

設計決策（03-CONTEXT.md）：
- D-01 編碼：以 binary 讀檔，先讀 XML 宣告的 encoding，依序嘗試
  big5 → cp950 → big5hkscs → utf-8，全部失敗才拋 SubmissionXmlError。
  原因：真實檔 TOTFA.xml 宣告 encoding="Big5"，而 Python 的 ElementTree
  無法直接解析 Big5（multi-byte encodings not supported），必須先 decode
  成 str 再餵給 parser。
- D-02 未知欄位全數保留於 raw dict，不丟棄。
- D-03 d20-d26 明確認列為次診斷代碼清單（ICD-10）。
- D-04 CRLF 行尾相容（不假設 LF）。
- D-05 致命缺漏僅三種：缺 d1/d2（無法識別案件）、缺 d3（無法對應病歷）、
  整案無 pdata（沒有醫令）。
- D-06 缺 d19（主診斷）只警告不拒收。
- D-07 整檔回傳單一 SubmissionParseResult（成功案＋拒收案＋警告）。
- D-08 警告兩級：只有高出現率欄位（>90%）缺席才發警告；低出現率欄位
  視為正常可空。門檻值取自 TOTFA.xml 實測（03-CONTEXT.md）。
- D-09 不查規則庫、不判斷醫令碼是否存在（Phase 5 職責）。
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET

from .models import OrderRecord, RejectedCase, SubmissionCase, SubmissionParseResult

# 依 D-01 的嘗試順序（宣告編碼優先，其餘為寬容回退）。
_ENCODING_FALLBACKS = ("big5", "cp950", "big5hkscs", "utf-8")

# XML 宣告的 encoding 屬性（單/雙引號皆可）。
_DECLARATION_RE = re.compile(rb"<\?xml[^>]*?encoding\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_DECLARATION_FULL_RE = re.compile(r"<\?xml[^>]*\?>")


class SubmissionXmlError(Exception):
    """申報 XML 無法解析（編碼全失敗或結構不符）時的例外。

    與 Phase 2 的 RuleRepositoryError 同為「基礎設施/輸入故障」語意：
    呼叫端應區分「輸入檔壞掉」（本例外）與「資料查無」（回傳型別內
    的 rejected/warnings），不可混為一談。
    """


# D-08：高出現率欄位（TOTFA.xml 實測 >90%），缺席即警告。
_DBODY_HIGH_OCCURRENCE = frozenset(
    {
        "d3", "d8", "d9", "d11", "d14", "d15", "d17", "d18", "d19",
        "d28", "d29", "d30", "d33", "d35", "d36", "d39", "d40", "d41", "d49", "d57",
    }
)
_PDATA_HIGH_OCCURRENCE = frozenset(
    {"p1", "p3", "p4", "p10", "p11", "p12", "p13", "p17"}
)

# 具名欄位映射：pdata tag → OrderRecord 屬性（僅 C11 記載欄位）。
_PDATA_FIELDS: dict[str, str] = {
    "p1": "days",
    "p2": "dispense",
    "p3": "category",
    "p4": "code",
    "p5": "dose",
    "p7": "frequency",
    "p9": "route",
    "p10": "total_qty",
    "p11": "unit_price",
    "p12": "points",
    "p13": "seq",
    "p14": "start_time",
    "p15": "end_time",
    "p17": "chronic_mark",
}

# 具名欄位映射：dbody/dhead tag → SubmissionCase 屬性。
_DBODY_FIELDS: dict[str, str] = {
    "d1": "case_class",
    "d2": "case_seq",
    "d3": "record_no",
    "d8": "clinic",
    "d9": "visit_date",
    "d10": "treatment_end_date",
    "d11": "birth_date",
    "d14": "pay_category",
    "d15": "copay_code",
    "d17": "refer_hosp",
    "d18": "transferred_out",
    "d19": "primary_diagnosis",
    "d49": "patient_name",
}

# d20-d26：次診斷代碼（D-03），依此順序收集。
_SECONDARY_DIAGNOSIS_TAGS = ("d20", "d21", "d22", "d23", "d24", "d25", "d26")


def _declared_encoding(raw: bytes) -> str | None:
    """從 XML 宣告讀取 encoding 屬性（D-01）。"""
    match = _DECLARATION_RE.search(raw[:512])
    return match.group(1).decode("ascii", errors="ignore") if match else None


def decode_xml_bytes(raw: bytes) -> str:
    """依 D-01 順序把 bytes 解碼為 str。

    Args:
        raw: 申報 XML 的原始 bytes。

    Returns:
        解碼後的 str。

    Raises:
        SubmissionXmlError: 宣告編碼與所有回退編碼皆失敗。
    """
    declared = _declared_encoding(raw)
    candidates: list[str] = []
    if declared:
        candidates.append(declared)
    for enc in _ENCODING_FALLBACKS:
        if enc not in candidates:
            candidates.append(enc)

    errors: list[str] = []
    for enc in candidates:
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError) as exc:
            errors.append(f"{enc}: {exc}")
    raise SubmissionXmlError(
        "申報 XML 無法解碼：嘗試編碼 "
        + ", ".join(c.split(":")[0] for c in errors)
        + f" 皆失敗（宣告={declared!r}）"
    )


def _neutralize_declaration(text: str) -> str:
    """移除/改寫 XML 宣告中的 encoding。

    ElementTree 不接受「帶 encoding 宣告的 str」（ValueError: Unicode
    strings with encoding declaration are not supported），因此解碼後
    需把宣告改成 utf-8（內容已是 str，encoding 只剩裝飾意義）。
    """
    return _DECLARATION_FULL_RE.sub(
        '<?xml version="1.0" encoding="utf-8"?>', text, count=1
    )


def _children_text(element: ET.Element) -> dict[str, str]:
    """收集元素的直接子元素為 {tag: text-or-empty}（不含子樹）。"""
    return {child.tag: (child.text or "") for child in element}


def _parse_orders(pdata_elements: list[ET.Element]) -> list[OrderRecord]:
    """把 pdata 元素清單轉成 OrderRecord 清單（含 raw 保留）。"""
    orders: list[OrderRecord] = []
    for pdata in pdata_elements:
        raw = _children_text(pdata)
        kwargs: dict[str, str | None] = {
            attr: raw.get(tag) for tag, attr in _PDATA_FIELDS.items()
        }
        orders.append(OrderRecord(raw=raw, **kwargs))  # type: ignore[arg-type]
    return orders


def _parse_case(ddata: ET.Element) -> SubmissionCase | RejectedCase:
    """解析單一 ddata，回傳 SubmissionCase 或（致命缺漏時）RejectedCase。

    依 D-05：缺 d1/d2、缺 d3、或整案無 pdata 為致命；其餘皆可容忍。
    """
    dhead = ddata.find("dhead")
    dbody = ddata.find("dbody")

    raw: dict[str, str] = {}
    case_class: str | None = None
    case_seq: str | None = None
    if dhead is not None:
        head_raw = _children_text(dhead)
        raw.update(head_raw)
        case_class = head_raw.get("d1")
        case_seq = head_raw.get("d2")

    dbody_raw: dict[str, str] = {}
    pdata_elements: list[ET.Element] = []
    if dbody is not None:
        for child in dbody:
            if child.tag == "pdata":
                pdata_elements.append(child)
            else:
                dbody_raw[child.tag] = child.text or ""
        raw.update(dbody_raw)

    # D-05 致命檢查
    if not case_class or not case_seq:
        return RejectedCase(
            case_class=case_class,
            case_seq=case_seq,
            reason="缺案件識別欄位（d1/d2）",
            raw=raw,
        )
    record_no = dbody_raw.get("d3")
    if not record_no:
        return RejectedCase(
            case_class=case_class,
            case_seq=case_seq,
            reason="缺病歷號（d3），無法對應病歷",
            raw=raw,
        )
    if not pdata_elements:
        return RejectedCase(
            case_class=case_class,
            case_seq=case_seq,
            reason="整案沒有任何醫令（pdata）",
            raw=raw,
        )

    orders = tuple(_parse_orders(pdata_elements))

    # D-08：高出現率欄位缺席才警告（dbody 層級）
    warnings: list[str] = []
    for tag in sorted(_DBODY_HIGH_OCCURRENCE - {"d19"}):
        if tag not in dbody_raw:
            warnings.append(f"高出現率欄位 {tag} 缺席")
    # D-06：d19 缺漏只警告不拒收
    if "d19" not in dbody_raw:
        warnings.append("主診斷（d19）缺漏")

    secondary = tuple(
        dbody_raw[tag] for tag in _SECONDARY_DIAGNOSIS_TAGS if dbody_raw.get(tag)
    )

    kwargs: dict[str, str | None] = {
        attr: raw.get(tag) for tag, attr in _DBODY_FIELDS.items()
    }
    return SubmissionCase(
        secondary_diagnoses=secondary,
        orders=orders,
        raw=raw,
        warnings=tuple(warnings),
        **kwargs,  # type: ignore[arg-type]
    )


def _parse_decoded_text(text: str) -> SubmissionParseResult:
    """解析已解碼的申報 XML 文字（D-07 回傳形狀，不含編碼偵測）。

    Args:
        text: 已解碼且 encoding 宣告已中性化的申報 XML 文字。

    Returns:
        SubmissionParseResult：header（tdata）＋成功案件＋拒收案件＋警告。

    Raises:
        SubmissionXmlError: 結構無法解析，或根元素不是 <outpatient>。
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SubmissionXmlError(f"申報 XML 結構無法解析: {exc}") from exc

    if root.tag != "outpatient":
        raise SubmissionXmlError(
            f"根元素應為 <outpatient>，實際為 <{root.tag}>"
        )

    tdata = root.find("tdata")
    header = _children_text(tdata) if tdata is not None else {}

    cases: list[SubmissionCase] = []
    rejected: list[RejectedCase] = []
    for ddata in root.findall("ddata"):
        result = _parse_case(ddata)
        if isinstance(result, RejectedCase):
            rejected.append(result)
        else:
            cases.append(result)

    return SubmissionParseResult(
        header=header,
        cases=tuple(cases),
        rejected=tuple(rejected),
        warnings=tuple(),
    )


def parse_submission_xml_bytes(raw: bytes) -> SubmissionParseResult:
    """解析申報 XML 的 bytes 內容（D-01 編碼偵測＋D-07 回傳形狀）。

    Args:
        raw: 申報 XML 的原始 bytes（binary 讀檔結果，含 encoding 宣告）。

    Returns:
        SubmissionParseResult：header（tdata）＋成功案件＋拒收案件＋警告。

    Raises:
        SubmissionXmlError: 編碼全失敗，或根元素不是 <outpatient>。
    """
    text = decode_xml_bytes(raw)
    return _parse_decoded_text(_neutralize_declaration(text))


def parse_submission_xml(path: str | os.PathLike[str]) -> SubmissionParseResult:
    """解析申報 XML 檔（D-13：file-in/file-out 定位的入口）。

    Args:
        path: 申報 XML 檔路徑。

    Returns:
        SubmissionParseResult。

    Raises:
        SubmissionXmlError: 讀檔/編碼/結構任一環節失敗。
    """
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as exc:
        raise SubmissionXmlError(f"無法讀取申報 XML: {exc}") from exc
    return parse_submission_xml_bytes(raw)


def parse_submission_xml_text(text: str) -> SubmissionParseResult:
    """解析已解碼的申報 XML 文字（供測試與內嵌字串使用）。

    直接以 str 解析（不再 encode 後走編碼偵測，避免中文內容被誤解碼）；
    encoding 宣告會被中性化處理。

    Args:
        text: 申報 XML 文字內容（不須含 encoding 宣告，可有可無）。

    Returns:
        SubmissionParseResult。
    """
    return _parse_decoded_text(_neutralize_declaration(text))
