"""payment／drug 載入器共用：讀 CSV → 清空並寫入規則表（B-IN-10）。

- 先檢查 CSV 表頭包含必要欄位，缺欄時給出明確訊息（原本拋原生 KeyError）。
- 連線一律以 contextlib.closing 關閉；清空與寫入在同一交易（B-WR-07）。
"""

from __future__ import annotations

import contextlib
import csv

from elc_audit_engine.rule_repository import db
from elc_audit_engine.rule_repository.loaders.dates import parse_flexible_date

_INSERT = {
    "payment_rules": (
        "INSERT OR REPLACE INTO payment_rules "
        "(code, name, payment_text, effective_from, effective_to) VALUES (?, ?, ?, ?, ?)"
    ),
    "drug_rules": (
        "INSERT OR REPLACE INTO drug_rules "
        "(code, name, payment_text, effective_from, effective_to) VALUES (?, ?, ?, ?, ?)"
    ),
}
_DELETE = {"payment_rules": "DELETE FROM payment_rules", "drug_rules": "DELETE FROM drug_rules"}


class RuleCsvFormatError(ValueError):
    """來源 CSV 缺少必要欄位。"""


def load_rule_csv(db_path: str, csv_path: str, table: str, columns: tuple[str, str, str, str, str]) -> int:
    """columns 依序為 (代碼, 名稱, 規定文字, 生效起日, 生效迄日) 的 CSV 欄名。"""
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in columns if c not in (reader.fieldnames or [])]
        if missing:
            raise RuleCsvFormatError(f"{csv_path} 缺少必要欄位：{', '.join(missing)}")
        code_col, name_col, text_col, from_col, to_col = columns
        rows = [
            (
                record[code_col],
                record[name_col],
                record[text_col],
                parse_flexible_date(record[from_col]),
                parse_flexible_date(record[to_col]),
            )
            for record in reader
        ]

    with contextlib.closing(db.get_connection(db_path)) as conn:
        db.init_schema(conn)
        with conn:
            conn.execute(_DELETE[table])
            conn.executemany(_INSERT[table], rows)
    return len(rows)
