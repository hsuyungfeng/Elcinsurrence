"""核減／申復明細資料檔解析器（D-14d 的 18 欄）→ DeductionParseResult。

設計決策（03-CONTEXT.md）：
- D-14b-rev：欄位順序已定（D-14d 官方範例 18 欄），直接依真實欄位順序
  實作；但 reader 層（編碼／分隔符／表頭）因尚未取得實體檔，設計為可
  注入參數 — 取得實體檔後只調參數，不改欄位映射。
- D-14d 關鍵事實：
  1. 日期全為西元 8 碼（YYYYMMDD）→ 重用 parse_flexible_date 的 8 碼分支。
  2. 兩種數字格式並存：欄 1 零填補定寬 10 碼 vs 欄 14 純數字，皆 int() 正規化。
  3. 欄 9 身分證號已遮罩後 4 碼；欄 8 出生日期未遮罩（PHI，比照 D-20/D-21）。
  4. 欄 17「院所申復事項」為 `代碼-說明` 複合欄，拆成 code/description。
  5. 欄 16「追扣原因」為自由中文，原樣保留（Phase 5/7 主要輸入訊號）。
  6. 欄 5/6/10/11 為與申報 XML 的 join key（d1/d2/p13/p4）。
- D-15：欄 1 不予核銷金額＝申復值域上界，必須取出（Phase 7 合法性檢查）。
- 本解析器為純資料轉換：無 LLM、無規則庫查詢。
"""

from __future__ import annotations

import csv
import io
import os
from typing import Sequence

from elc_audit_engine.rule_repository.loaders.dates import parse_flexible_date

from .models import DeductionParseResult, DeductionRecord, RejectedRow

# D-14d 的 18 欄，依官方範例左→右順序（唯一定義，reader 參數不得改此順序）。
COLUMN_NAMES: tuple[str, ...] = (
    "不予核銷金額",   # 1  零填補定寬數字（0000000300＝300）
    "醫事機構代碼",   # 2  10 碼
    "費用年月",       # 3  西元 YYYYMM（6 碼，非日期）
    "申請申報日期",   # 4  西元 YYYYMMDD
    "案件分類",       # 5  對應申報 XML d1
    "流水號",         # 6  對應 d2（無零填補）
    "就醫日期",       # 7  西元 YYYYMMDD
    "出生日期",       # 8  西元 YYYYMMDD（未遮罩，PHI）
    "身分證號",       # 9  已遮罩後 4 碼（PHI）
    "醫令序號",       # 10 對應申報 XML p13（D-14d 指申復 XML p1）
    "醫令代碼",       # 11 對應 p4／get_rule() 查詢鍵
    "執行時間起",     # 12 西元 YYYYMMDD
    "分區別",         # 13
    "拆帳金額",       # 14 純數字（與欄 1 同值不同格式）
    "核付日期",       # 15 西元 YYYYMMDD
    "追扣原因",       # 16 自由中文（原樣保留）
    "院所申復事項",   # 17 `代碼-說明` 複合欄，需拆
    "院所說明",       # 18 自由中文
)

# 8 碼西元日期欄（欄 4/7/8/12/15），依 D-14d 全為西元，走 parse_flexible_date
# 的 8 碼分支（7 碼民國分支在此檔不會觸發，測試釘住此假設）。
_DATE_COLUMNS: tuple[int, ...] = (4, 7, 8, 12, 15)
# 整數欄（欄 1 零填補、欄 14 純數字，雙格式皆 int() 正規化）。
_INT_COLUMNS: tuple[int, ...] = (1, 14)

_ENCODING_FALLBACKS = ("utf-8-sig", "big5", "cp950")

# 表頭偵測關鍵字：任一中文字詞出現即視為表頭列。
_HEADER_KEYWORDS = ("不予核銷金額", "醫事機構代碼", "費用年月", "追扣原因")


class DeductionFileError(Exception):
    """核減明細檔無法讀取／解碼時的例外（輸入故障語意）。"""


def _decode(raw: bytes, encoding: str | None) -> tuple[str, str]:
    """解碼核減檔 bytes。encoding 為 None 時自動偵測（utf-8-sig→big5→cp950）。

    Returns:
        (解碼後文字, 實際使用的編碼)。
    """
    candidates = [encoding] if encoding else list(_ENCODING_FALLBACKS)
    errors: list[str] = []
    for enc in candidates:
        try:
            return raw.decode(enc), enc
        except (LookupError, UnicodeDecodeError) as exc:
            errors.append(f"{enc}: {exc}")
    raise DeductionFileError(
        "核減明細檔無法解碼：嘗試編碼 "
        + ", ".join(e.split(":")[0] for e in errors)
        + " 皆失敗"
    )


def _looks_like_header(row: Sequence[str]) -> bool:
    """依欄位名稱關鍵字判斷該列是否為表頭列。

    實體檔尚未取得（D-18），表頭列有無未知；此偵測讓有/無表頭皆可解析。
    """
    return any(any(kw in (cell or "") for kw in _HEADER_KEYWORDS) for cell in row[:6])


def _parse_int(value: str | None) -> int | None:
    """把欄位值正規化為 int；空值/非數字回傳 None。

    欄 1 為零填補定寬（"0000000300"）、欄 14 為純數字（"300"），兩者皆
    直接 int()；容許浮點字串（"300.0"）以防其他 HIS 匯出格式。
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError:
        pass
    try:
        return int(float(stripped))
    except ValueError:
        return None


def _split_appeal_item(value: str | None) -> tuple[str | None, str | None]:
    """拆分欄 17「院所申復事項」的 `代碼-說明` 複合格式。

    `A-檢驗結果確實於時效內上傳` → ("A", "檢驗結果確實於時效內上傳")。
    無 `-` 時（例如整串即代碼）→ (整串, None)。
    """
    if value is None:
        return None, None
    stripped = value.strip()
    if not stripped:
        return None, None
    if "-" in stripped:
        code, desc = stripped.split("-", 1)
        return (code.strip() or None), (desc.strip() or None)
    return stripped, None


def _row_to_record(cells: list[str]) -> DeductionRecord:
    """依 D-14d 欄序把單列 18 欄轉成 DeductionRecord（1-based 欄號）。"""
    raw = tuple(cells)

    def col(n: int) -> str | None:
        # n 為 1-based 欄號，對應 raw 的 n-1 index
        value = raw[n - 1].strip() if len(raw) >= n else None
        return value or None

    amounts = {n: _parse_int(col(n)) for n in _INT_COLUMNS}
    dates = {n: parse_flexible_date(col(n)) for n in _DATE_COLUMNS}
    appeal_code, appeal_desc = _split_appeal_item(col(17))

    return DeductionRecord(
        non_reimbursed_amount=amounts[1],
        institution_code=col(2),
        fee_year_month=col(3),
        submit_date=dates[4],
        case_class=col(5),
        case_seq=col(6),
        visit_date=dates[7],
        birth_date=dates[8],
        id_number=col(9),
        order_seq=col(10),
        order_code=col(11),
        exec_start=dates[12],
        region=col(13),
        split_amount=amounts[14],
        pay_date=dates[15],
        deduction_reason=col(16),
        appeal_item_code=appeal_code,
        appeal_item_desc=appeal_desc,
        institution_note=col(18),
        raw=raw,
    )


def parse_deduction_file(
    path: str | os.PathLike[str],
    *,
    encoding: str | None = None,
    delimiter: str | None = None,
    has_header: bool | None = None,
) -> DeductionParseResult:
    """解析核減／申復明細資料檔（D-14b-rev 的可注入 reader 層）。

    Args:
        path: 檔案路徑。
        encoding: 指定編碼；None 時自動偵測（utf-8-sig→big5→cp950）。
        delimiter: 指定分隔符；None 時以 csv.Sniffer 偵測（預設逗號）。
        has_header: 是否含表頭列；None 時自動偵測（欄位名稱關鍵字）。

    Returns:
        DeductionParseResult：records＋rejected（欄數不符列）＋header＋
        實際使用的編碼與分隔符。

    Raises:
        DeductionFileError: 讀檔或解碼失敗。
    """
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as exc:
        raise DeductionFileError(f"無法讀取核減明細檔: {exc}") from exc

    text, encoding_used = _decode(raw, encoding)

    if delimiter is None:
        sample = text[:4096]
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",\t;").delimiter
        except csv.Error:
            delimiter = ","

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [row for row in reader if any(cell.strip() for cell in row)]

    header: tuple[str, ...] = ()
    data_rows: list[list[str]] = []
    if rows:
        first = rows[0]
        if has_header is True or (has_header is None and _looks_like_header(first)):
            header = tuple(first)
            data_rows = rows[1:]
        else:
            data_rows = rows

    records: list[DeductionRecord] = []
    rejected: list[RejectedRow] = []
    for idx, row in enumerate(data_rows, start=1):
        if len(row) != len(COLUMN_NAMES):
            rejected.append(
                RejectedRow(
                    row_number=idx,
                    reason=(
                        f"欄數不符：實際 {len(row)} 欄，預期 {len(COLUMN_NAMES)} 欄"
                    ),
                    raw=tuple(row),
                )
            )
            continue
        records.append(_row_to_record(row))

    return DeductionParseResult(
        records=tuple(records),
        rejected=tuple(rejected),
        header=header,
        encoding_used=encoding_used,
        delimiter_used=delimiter,
    )
