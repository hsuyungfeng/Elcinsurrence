"""藥品項目（drug）CSV -> SQLite `drug_rules` 表載入器。

來源 CSV 欄位對應（D-01/D-02 核心欄位）：
    藥品代號     -> code
    藥品中文名稱 -> name
    給付規定     -> payment_text
    有效起日     -> effective_from（7 碼民國 RRRMMDD）
    有效迄日     -> effective_to（7 碼民國 RRRMMDD）
"""

import contextlib
import csv
from decimal import Decimal, InvalidOperation

from elc_audit_engine.rule_repository import db
from elc_audit_engine.rule_repository.loaders._csv_table import (
    RuleCsvFormatError,
    load_rule_csv,
)
from elc_audit_engine.rule_repository.loaders.dates import parse_flexible_date

# 來源 CSV 中代表「沒有官方給付規定」的占位字串（實測 2631 列，約 19%）。
_PLACEHOLDER_TEXTS = frozenset({"", "未找到給付規定", "null", "None"})

_REQUIRED_COLUMNS = (
    "藥品代號", "藥品中文名稱", "給付規定", "有效起日", "有效迄日", "支付價", "AI-note",
)

_INSERT_FULL = (
    "INSERT OR REPLACE INTO drug_rules "
    "(code, name, payment_text, effective_from, effective_to, unit_price, ai_note) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)


def _official_text(raw: str) -> str | None:
    """官方給付規定：占位字串一律回 None（不以 AI 摘要替代）。"""
    text = (raw or "").strip()
    return None if text in _PLACEHOLDER_TEXTS else text


def _official_price(raw: str) -> str | None:
    """官方支付價：必須是有限、非負的數字；欄位錯位（如 '單方'、'MG'）回 None。"""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return text if value.is_finite() and value >= 0 else None


def load_drug_csv_full(db_path: str, csv_path: str, *, replace: bool = True) -> int:
    """讀取藥品項目 CSV（含支付價與 AI 摘要）並整表取代 `drug_rules`。

    欄位對應：藥品代號→code、藥品中文名稱→name、給付規定→payment_text（占位即 NULL）、
    有效起／迄日→effective_from／to、支付價→unit_price、AI-note→ai_note（非官方）。

    整檔讀完並驗證後才開交易寫入；讀取或格式錯誤時既有資料不受影響。

    Raises:
        RuleCsvFormatError: 缺少必要欄位。
    """
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in _REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise RuleCsvFormatError(f"{csv_path} 缺少必要欄位：{', '.join(missing)}")
        rows: dict[str, tuple] = {}
        for record in reader:
            code = (record["藥品代號"] or "").strip().upper()
            if not code:
                continue
            ai_note = (record["AI-note"] or "").strip() or None
            rows[code] = (  # 重複代碼以最後一列為準（與 INSERT OR REPLACE 語意一致）
                code,
                (record["藥品中文名稱"] or "").strip(),
                _official_text(record["給付規定"]),
                parse_flexible_date(record["有效起日"]),
                parse_flexible_date(record["有效迄日"]),
                _official_price(record["支付價"]),
                ai_note,
            )

    with contextlib.closing(db.get_connection(db_path)) as conn:
        db.init_schema(conn)
        with conn:
            if replace:
                conn.execute("DELETE FROM drug_rules")
            conn.executemany(_INSERT_FULL, list(rows.values()))
    return len(rows)


def load_drug_csv(db_path: str, csv_path: str) -> int:
    """讀取藥品項目 CSV 並寫入 `drug_rules` 表。

    Args:
        db_path: 目標 SQLite 檔案路徑。
        csv_path: 來源 CSV 檔案路徑（`utf-8-sig` 編碼，含 BOM）。

    Returns:
        實際插入的資料列數。
    """
    return load_rule_csv(db_path, csv_path, "drug_rules", ('藥品代號', '藥品中文名稱', '給付規定', '有效起日', '有效迄日'))
