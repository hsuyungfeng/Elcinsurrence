"""民國（ROC）與西元日期的標準化工具（Phase 22-04，P2-2）。

取代原本散落於 monthly_audit、monthly_patient_service、evidence_vault、parsers/totfa、
generators/*/field_mapping 等處、各自以字串切片與 `+ 1911` 實作的重複邏輯。

格式約定：
- 民國七碼 `RRRMMDD`（如 `1120718`，即 2023-07-18）。
- 西元 ISO `YYYY-MM-DD`；西元八碼 `YYYYMMDD` 於 roc_date_text 亦接受。
- 民國年月 `YYY年M月`、民國年月日 `YYY年M月D日`（列印模板用）。
"""

from __future__ import annotations

import re
from datetime import date

ROC_OFFSET = 1911  # 西元 = 民國 + 1911

_ROC7_RE = re.compile(r"\d{7}")
_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def roc7_to_date(value: str | None) -> date | None:
    """民國七碼（RRRMMDD）→ date；格式或日期不合法回 None（不拋例外）。"""
    text = (value or "").strip()
    if not _ROC7_RE.fullmatch(text):
        return None
    try:
        return date(int(text[:3]) + ROC_OFFSET, int(text[3:5]), int(text[5:7]))
    except ValueError:
        return None


def roc_to_iso(roc_str: str) -> str:
    """民國七碼 → 西元 ISO：`1120718` → `2023-07-18`。不合法拋 ValueError。"""
    converted = roc7_to_date((roc_str or "").strip())
    if converted is None:
        raise ValueError(f"非法的民國七碼日期：{roc_str!r}")
    return converted.isoformat()


def iso_to_roc(iso_str: str) -> str:
    """西元 ISO（YYYY-MM-DD）→ 民國七碼：`2023-07-18` → `1120718`。不合法拋 ValueError。"""
    match = _ISO_RE.fullmatch((iso_str or "").strip())
    if match is None:
        raise ValueError(f"非法的西元 ISO 日期：{iso_str!r}")
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    date(year, month, day)  # 驗證曆法合法性
    return f"{year - ROC_OFFSET:03d}{month:02d}{day:02d}"


def roc_year_month(ym_str: str) -> str:
    """西元 `YYYYMM` → 民國 `YYY年M月`：`202307` → `112年7月`。

    非六碼數字者原樣回傳（列印備援的誠實降級，不猜測）。
    """
    if len(ym_str) != 6 or not ym_str.isdigit():
        return ym_str
    return f"{int(ym_str[:4]) - ROC_OFFSET}年{int(ym_str[4:6])}月"


def roc_date_text(iso_str: str) -> str:
    """西元日期 → 民國 `YYY年M月D日`：`2023-07-18` → `112年7月18日`。

    同時接受西元八碼 `20230718`。無法辨識者原樣回傳（誠實降級，不猜測）。
    """
    parts = iso_str.split("-")
    if len(parts) != 3:
        if len(iso_str) == 8 and iso_str.isdigit():
            return f"{int(iso_str[:4]) - ROC_OFFSET}年{int(iso_str[4:6])}月{int(iso_str[6:8])}日"
        return iso_str
    year, month, day = parts
    if not (year.isdigit() and month.isdigit() and day.isdigit()):
        return iso_str
    return f"{int(year) - ROC_OFFSET}年{int(month)}月{int(day)}日"


__all__ = [
    "ROC_OFFSET",
    "iso_to_roc",
    "roc7_to_date",
    "roc_date_text",
    "roc_to_iso",
    "roc_year_month",
]
