"""SQLite payment_rules/drug_rules 可查詢性測試（REQ-rule-repository 驗收標準 1）。

Wave 0 預期紅燈：`db`/`loaders` 模組尚未實作（Plan 02 落地），
本檔案應以 ImportError/ModuleNotFoundError 收集失敗，而非語法錯誤。
"""

import glob
import os

from config.settings import RULE_SOURCE_DIR
from elc_audit_engine.rule_repository import db, loaders


def _payment_csv_path() -> str:
    matches = glob.glob(os.path.join(RULE_SOURCE_DIR, "醫療服務給付項目*.csv"))
    assert matches, "payment CSV not found via glob"
    return matches[0]


def _drug_csv_path() -> str:
    matches = glob.glob(os.path.join(RULE_SOURCE_DIR, "藥品項查詢項目檔*.csv"))
    assert matches, "drug CSV not found via glob"
    return matches[0]


def test_payment_rules_table_created_with_core_columns(tmp_rule_db_path):
    loaders.load_payment_csv(tmp_rule_db_path, _payment_csv_path())
    conn = db.get_connection(tmp_rule_db_path)
    cursor = conn.execute("PRAGMA table_info(payment_rules)")
    columns = {row[1] for row in cursor.fetchall()}
    expected = {"code", "name", "payment_text", "effective_from", "effective_to"}
    assert expected.issubset(columns)


def test_drug_rules_table_created_with_core_columns(tmp_rule_db_path):
    loaders.load_drug_csv(tmp_rule_db_path, _drug_csv_path())
    conn = db.get_connection(tmp_rule_db_path)
    cursor = conn.execute("PRAGMA table_info(drug_rules)")
    columns = {row[1] for row in cursor.fetchall()}
    expected = {"code", "name", "payment_text", "effective_from", "effective_to"}
    assert expected.issubset(columns)


def test_query_known_payment_code_64140C_returns_row(tmp_rule_db_path):
    loaders.load_payment_csv(tmp_rule_db_path, _payment_csv_path())
    conn = db.get_connection(tmp_rule_db_path)
    cursor = conn.execute(
        "SELECT * FROM payment_rules WHERE code = ?", ("64140C",)
    )
    row = cursor.fetchone()
    assert row is not None


def test_query_known_drug_code_AC10398100_returns_row(tmp_rule_db_path):
    loaders.load_drug_csv(tmp_rule_db_path, _drug_csv_path())
    conn = db.get_connection(tmp_rule_db_path)
    cursor = conn.execute(
        "SELECT * FROM drug_rules WHERE code = ?", ("AC10398100",)
    )
    row = cursor.fetchone()
    assert row is not None
