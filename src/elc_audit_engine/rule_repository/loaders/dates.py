"""共用日期解析工具：民國（ROC）與西元（Gregorian）日期格式判別與正規化。

背景：規則庫的兩份 CSV 來源使用不同曆法慣例，且欄位名稱本身不提供任何線索：
- 給付項目（payment）CSV 的 `生效起日`/`生效迄日` 為 8 碼西元格式 `YYYYMMDD`
  （例如 `20160401` -> 2016-04-01）。
- 藥品項目（drug）CSV 的 `有效起日`/`有效迄日` 為 7 碼民國格式 `RRRMMDD`
  （例如 `1121001` -> 民國 112 年 = 西元 2023 年 10 月 1 日）。

呼叫端必須依照來源 CSV 選擇正確的假設；本模組僅依「字串長度」
（7 碼 = 民國、8 碼 = 西元）做格式判別，不嘗試用其他方式猜測。
"""

import warnings
from datetime import date

_EMPTY_SENTINELS = {"", "null", "0", "99991231"}

_ROC_EPOCH_OFFSET = 1911


def parse_flexible_date(raw: str) -> str | None:
    """將原始日期字串正規化為 ISO 8601 (`YYYY-MM-DD`)，或在無效/無日期時回傳 None。

    Args:
        raw: 原始欄位字串。可能是 8 碼西元 `YYYYMMDD`、7 碼民國 `RRRMMDD`，
            或代表「無日期」的哨兵值（空字串、`"null"`、`"0"`、`"99991231"`）。

    Returns:
        ISO 8601 格式的日期字串（`YYYY-MM-DD`），或 `None`（哨兵值/無法解析）。
    """
    if raw is None:
        return None

    stripped = raw.strip()

    if stripped in _EMPTY_SENTINELS:
        return None

    if len(stripped) == 8 and stripped.isdigit():
        # 8 碼 -> 西元 YYYYMMDD（給付項目 CSV）
        year = int(stripped[0:4])
        month = int(stripped[4:6])
        day = int(stripped[6:8])
    elif len(stripped) == 7 and stripped.isdigit():
        # 7 碼 -> 民國 RRRMMDD（藥品項目 CSV），年份需 +1911 轉為西元
        roc_year = int(stripped[0:3])
        year = roc_year + _ROC_EPOCH_OFFSET
        month = int(stripped[3:5])
        day = int(stripped[5:7])
    else:
        warnings.warn(
            f"parse_flexible_date: unrecognized date format, raw value={raw!r}",
            stacklevel=2,
        )
        return None

    try:
        return date(year, month, day).isoformat()
    except ValueError:
        warnings.warn(
            f"parse_flexible_date: invalid calendar date, raw value={raw!r}",
            stacklevel=2,
        )
        return None
