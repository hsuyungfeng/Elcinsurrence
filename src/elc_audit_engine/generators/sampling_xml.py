"""健保署電子抽審 XML 導出（Plan 16-03）。

結構依 repo 內 `電子抽審.md` 的上傳必要欄位格式：<outpatient> → <tdata>、<ddata>（<dhead> 與 <dbody>）、<pdata>。
- 只輸出規範欄位。來源未提供的欄位一律省略，不捏造數值。
- 必要欄位缺漏（d1、d2、d3、至少一筆 pdata）→ 拋 SamplingXmlError，不產生殘缺檔。
- SOAP 與附件不屬健保上傳規格，**不寫入上傳檔**（否則可能被健保系統拒收）；由預覽卡片另行呈現。
- 編碼：Big5（與 TOTFA.xml 相同）；無法以 Big5 表示的字元 → 拋錯，不靜默替換。
"""

from __future__ import annotations

import re
from xml.sax.saxutils import escape

_ROC_YM_RE = re.compile(r"^MONTHLY-(\d{4})(\d{2})$")
_DBODY_ORDER = ("d3", "d8", "d9", "d10", "d11", "d14", "d15", "d17", "d18", "d19", "d30", "d33", "d35", "d36", "d39", "d40", "d41", "d49")
_PDATA_ORDER = tuple(f"p{i}" for i in range(1, 18))


class SamplingXmlError(ValueError):
    """抽樣案件無法組成合規的健保抽審 XML（缺必要欄位或無法 Big5 編碼）。"""


def _roc_year_month(batch: str) -> str | None:
    match = _ROC_YM_RE.match(batch or "")
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return f"{year - 1911:03d}{month:02d}"


def _field(tag: str, value: object) -> str:
    return f"<{tag}>{escape(str(value))}</{tag}>"


def _ddata_xml(source: dict, order_raws: list[dict]) -> str:
    d1, d2, d3 = source.get("case_class"), source.get("case_seq"), source.get("record_no")
    missing = [name for name, value in (("d1", d1), ("d2", d2), ("d3", d3)) if not value]
    if not order_raws:
        missing.append("pdata")
    if missing:
        raise SamplingXmlError(f"缺少必要欄位：{', '.join(missing)}")

    dbody_parts = []
    for tag in _DBODY_ORDER:
        if tag == "d3":
            dbody_parts.append(_field("d3", d3))
        elif tag == "d19":
            if source.get("primary_diagnosis"):
                dbody_parts.append(_field("d19", source["primary_diagnosis"]))
        elif tag == "d30":
            if source.get("doctor_code"):
                dbody_parts.append(_field("d30", source["doctor_code"]))
        elif tag == "d39":
            if source.get("total_points"):
                dbody_parts.append(_field("d39", source["total_points"]))
        elif tag == "d49":
            if source.get("patient_name"):
                dbody_parts.append(_field("d49", source["patient_name"]))
        elif tag == "d8":
            if source.get("clinic"):
                dbody_parts.append(_field("d8", source["clinic"]))
        elif tag == "d9":
            if source.get("visit_date"):
                dbody_parts.append(_field("d9", source["visit_date"]))
        elif tag == "d11":
            if source.get("birth_date"):
                dbody_parts.append(_field("d11", source["birth_date"]))
    for index, secondary in enumerate(source.get("secondary_diagnoses") or [], start=20):
        if index > 26:
            break
        dbody_parts.append(_field(f"d{index}", secondary))

    pdata_parts = []
    for raw in order_raws:
        fields = "".join(_field(tag, raw[tag]) for tag in _PDATA_ORDER if raw.get(tag) not in (None, ""))
        pdata_parts.append(f"<pdata>{fields}</pdata>")

    return (
        "<ddata>"
        f"<dhead>{_field('d1', d1)}{_field('d2', d2)}</dhead>"
        f"<dbody>{''.join(dbody_parts)}{''.join(pdata_parts)}</dbody>"
        "</ddata>"
    )


def build_sampling_xml(payload: dict) -> bytes:
    """組裝抽樣案件的健保抽審 XML（Big5 位元組）。

    `payload["monthly_source"]` 為來源申報總檔案件（含 orders 原始欄位），
    由抽樣端點自批次案件帶入；缺此來源即無法組成合規上傳檔。

    Raises:
        SamplingXmlError: 缺來源、缺必要欄位，或含 Big5 無法表示的字元。
    """
    source = payload.get("monthly_source")
    if not isinstance(source, dict):
        raise SamplingXmlError("此抽樣案件缺少申報總檔來源，無法導出健保抽審 XML")
    return _outpatient_document(payload.get("batch") or "", [_ddata_for_source(source)])


def build_batch_sampling_xml(payloads: list[dict]) -> bytes:
    """全批次導出（Plan 20-03）：多案件聚合為單一 `<outpatient>`（Big5）。

    所有案件須屬同一申報批次（tdata 的 t3 年月取自共同批次）；每案一個 `<ddata>`。
    任一案件缺來源或必要欄位即整批拒絕，錯誤訊息點名該案，不產生殘缺檔。

    Raises:
        SamplingXmlError: 無案件、批次不一致、任一案件缺來源或欄位、或含 Big5 無法表示的字元。
    """
    if not payloads:
        raise SamplingXmlError("沒有可導出的抽樣案件")
    batches = {str(p.get("batch") or "") for p in payloads}
    if len(batches) != 1:
        raise SamplingXmlError("全批次導出的案件須屬於同一申報批次")
    ddatas = []
    for payload in payloads:
        label = payload.get("id") or payload.get("case_seq") or "（未知案件）"
        source = payload.get("monthly_source")
        if not isinstance(source, dict):
            raise SamplingXmlError(f"案件 {label} 缺少申報總檔來源，整批無法導出")
        try:
            ddatas.append(_ddata_for_source(source))
        except SamplingXmlError as exc:
            raise SamplingXmlError(f"案件 {label}：{exc}") from exc
    return _outpatient_document(batches.pop(), ddatas)


def _ddata_for_source(source: dict) -> str:
    order_raws = [o for o in (source.get("orders") or []) if isinstance(o, dict)]
    return _ddata_xml(source, order_raws)


def _outpatient_document(batch: str, ddata_parts: list[str]) -> bytes:
    """組裝完整文件（tdata＋多個 ddata）並以 Big5 編碼；無法表示的字元拋錯，不靜默替換。"""
    year_month = _roc_year_month(batch)
    tdata = (
        "<tdata>"
        + (_field("t3", year_month) if year_month else "")
        + _field("t9", 1)
        + _field("t17", 1)
        + _field("t37", 1)
        + "</tdata>"
    )
    body = f"<outpatient>{tdata}{''.join(ddata_parts)}</outpatient>"
    document = f'<?xml version="1.0" encoding="Big5"?>\r\n{body}\r\n'
    try:
        return document.encode("big5")
    except UnicodeEncodeError as exc:
        raise SamplingXmlError("含 Big5 無法表示的字元，請修正後再導出") from exc
