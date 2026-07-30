"""一次性建置腳本：從來源 CSV 產生正式的 `data/db/rules.sqlite3`。

用法：
    uv run python -m elc_audit_engine.rule_repository.scripts.build_sqlite
"""

import glob
import os

from config.settings import DB_DIR, RULE_SOURCE_DIR
from elc_audit_engine.rule_repository import loaders


def _resolve_payment_csv_path() -> str:
    matches = glob.glob(os.path.join(RULE_SOURCE_DIR, "醫療服務給付項目*.csv"))
    if not matches:
        raise FileNotFoundError(
            f"payment CSV not found under {RULE_SOURCE_DIR!r} "
            "(expected glob pattern '醫療服務給付項目*.csv')"
        )
    return matches[0]


def _resolve_drug_csv_path() -> str:
    matches = glob.glob(os.path.join(RULE_SOURCE_DIR, "藥品項查詢項目檔*.csv"))
    if not matches:
        raise FileNotFoundError(
            f"drug CSV not found under {RULE_SOURCE_DIR!r} "
            "(expected glob pattern '藥品項查詢項目檔*.csv')"
        )
    return matches[0]


def main() -> None:
    db_path = os.path.join(DB_DIR, "rules.sqlite3")
    payment_csv_path = _resolve_payment_csv_path()
    drug_csv_path = _resolve_drug_csv_path()

    n_payment = loaders.load_payment_csv(db_path, payment_csv_path)
    n_drug = loaders.load_drug_csv(db_path, drug_csv_path)

    print(f"payment_rules: {n_payment} rows, drug_rules: {n_drug} rows")


if __name__ == "__main__":
    main()
