"""事前預審抽樣清單解析（CSV 為主，欄位契約自訂 — 2026-08-04 使用者裁示）。

欄位契約（對齊既有 UI 與引擎欄位；取得官方抽樣樣本檔後可再調整）：
  流水號(case_seq)／病歷號(record_no)／病患姓名(patient_name)／
  醫令代碼(order_code, 必填)／醫令名稱(order_name)／就醫日期(visit_date)／
  科別(clinic)／SOAP(soap_text, 可選)

CSV 表頭以別名對映（中英皆可），表頭列自動偵測；編碼 utf-8-sig→big5→cp950
自動偵測（與核減明細 parser 同策略）。純資料轉換：無 LLM、無規則庫查詢。
"""

from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass, field
from typing import Sequence

from elc_audit_engine.rule_repository.loaders.dates import parse_flexible_date

# 欄位 → 可接受的表頭別名（依序嘗試；命中即對映該欄位 index）。
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "case_seq": ("流水號", "抽樣流水號", "case_seq", "案件流水號"),
    "record_no": ("病歷號", "病歷號碼", "病歷編號", "record_no"),
    "patient_name": ("病患姓名", "病人姓名", "姓名", "patient_name"),
    "order_code": ("醫令代碼", "醫令號碼", "代碼", "order_code"),
    "order_name": ("醫令名稱", "名稱", "order_name"),
    "visit_date": ("就醫日期", "就診日期", "visit_date"),
    "clinic": ("科別", "clinic"),
    "soap_text": ("SOAP", "soap", "soap_text", "病歷"),
}

# 必填欄位：無醫令代碼無法查規則庫／比對。
REQUIRED_FIELDS: tuple[str, ...] = ("order_code",)

_ENCODING_FALLBACKS = ("utf-8-sig", "big5", "cp950")


class SamplingImportError(Exception):
    """抽樣清單無法讀取／解碼（輸入故障語意）。"""


@dataclass(frozen=True)
class SamplingCaseRecord:
    """單筆抽樣案件（CSV 或 OCR 來源）。"""

    order_code: str
    case_seq: str | None = None
    record_no: str | None = None
    patient_name: str | None = None
    order_name: str | None = None
    visit_date: str | None = None  # ISO YYYY-MM-DD（解析失敗保留原值）
    clinic: str | None = None
    soap_text: str | None = None
    # 來源元資料：csv / ocr；ocr 附原始辨識行。
    source: str = "csv"
    ocr_line: str | None = None
    raw: tuple[str, ...] = ()


@dataclass(frozen=True)
class SamplingRejectedRow:
    """被拒絕的列（缺必填／欄數異常），附原因供前端顯示。"""

    row_number: int
    reason: str
    raw: tuple[str, ...]


@dataclass(frozen=True)
class SamplingImportResult:
    """抽樣清單解析結果。"""

    records: tuple[SamplingCaseRecord, ...]
    rejected: tuple[SamplingRejectedRow, ...]
    header: tuple[str, ...] = ()
    encoding_used: str | None = None
    source: str = "csv"  # csv / ocr


def _decode(raw: bytes, encoding: str | None) -> tuple[str, str]:
    """解碼抽樣清單 bytes；encoding 為 None 時自動偵測。"""
    candidates = [encoding] if encoding else list(_ENCODING_FALLBACKS)
    errors: list[str] = []
    for enc in candidates:
        try:
            return raw.decode(enc), enc
        except (LookupError, UnicodeDecodeError) as exc:
            errors.append(f"{enc}: {exc}")
    raise SamplingImportError(
        "抽樣清單無法解碼：嘗試編碼 "
        + ", ".join(e.split(":")[0] for e in errors)
        + " 皆失敗"
    )


def _match_alias(cell: str) -> str | None:
    """把表頭儲存格對映到契約欄位名；無匹配回 None。"""
    normalized = (cell or "").strip().lower()
    if not normalized:
        return None
    for field_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if normalized == alias.lower():
                return field_name
    return None


def _looks_like_header(row: Sequence[str]) -> bool:
    """表頭列偵測：任一儲存格命中醫令代碼／流水號等契約別名。"""
    return any(_match_alias(cell) is not None for cell in row)


def _row_to_record(
    cells: list[str], mapping: dict[str, int], source: str, ocr_line: str | None = None
) -> SamplingCaseRecord:
    """依欄位→index 對映把單列轉成記錄。"""

    def col(field: str) -> str | None:
        idx = mapping.get(field)
        if idx is None:
            return None
        value = cells[idx].strip() if idx < len(cells) else ""
        return value or None

    visit_raw = col("visit_date")
    visit = parse_flexible_date(visit_raw) if visit_raw else None
    return SamplingCaseRecord(
        order_code=col("order_code") or "",
        case_seq=col("case_seq"),
        record_no=col("record_no"),
        patient_name=col("patient_name"),
        order_name=col("order_name"),
        visit_date=visit or visit_raw,
        clinic=col("clinic"),
        soap_text=col("soap_text"),
        source=source,
        ocr_line=ocr_line,
        raw=tuple(cells),
    )


def parse_sampling_csv(
    raw: bytes, *, encoding: str | None = None
) -> SamplingImportResult:
    """解析抽樣清單 CSV bytes → SamplingImportResult。

    表頭列自動偵測（命中契約別名）；缺 order_code 的列進入 rejected。
    """
    text, encoding_used = _decode(raw, encoding)
    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader if any((c or "").strip() for c in row)]
    if not rows:
        return SamplingImportResult(
            records=(), rejected=(), encoding_used=encoding_used, source="csv"
        )

    # 找表頭列：第一個命中別名的列。
    header_idx = next(
        (i for i, row in enumerate(rows) if _looks_like_header(row)), None
    )
    if header_idx is None:
        raise SamplingImportError(
            "找不到表頭列（需含「醫令代碼」或 order_code 等欄位名稱）"
        )

    header = tuple(rows[header_idx])
    mapping: dict[str, int] = {}
    for field_name, aliases in COLUMN_ALIASES.items():
        for cell in header:
            if (cell or "").strip().lower() in {a.lower() for a in aliases}:
                mapping[field_name] = header.index(cell)
                break

    records: list[SamplingCaseRecord] = []
    rejected: list[SamplingRejectedRow] = []
    for idx, row in enumerate(rows[header_idx + 1 :], start=header_idx + 2):
        rec = _row_to_record(row, mapping, source="csv")
        if not rec.order_code:
            rejected.append(
                SamplingRejectedRow(
                    row_number=idx,
                    reason="缺少必填欄位「醫令代碼」",
                    raw=tuple(row),
                )
            )
            continue
        records.append(rec)

    return SamplingImportResult(
        records=tuple(records),
        rejected=tuple(rejected),
        header=header,
        encoding_used=encoding_used,
        source="csv",
    )


def parse_sampling_csv_path(path: str | os.PathLike[str]) -> SamplingImportResult:
    """讀檔版 parse_sampling_csv（供端點與 CLI 使用）。"""
    try:
        with open(path, "rb") as f:
            return parse_sampling_csv(f.read())
    except OSError as exc:
        raise SamplingImportError(f"無法讀取抽樣清單: {exc}") from exc
