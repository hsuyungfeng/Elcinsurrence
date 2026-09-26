"""一次性建置腳本：從來源 CSV 產生正式的 `data/db/rules.sqlite3`。

用法：
    uv run python -m elc_audit_engine.rule_repository.scripts.build_sqlite
"""

import glob
import sys
import re
import os

from config.settings import DB_DIR, RULE_SOURCE_DIR
from elc_audit_engine.rule_repository import loaders


def _pick_latest(matches: list[str]) -> str:
    """多版 CSV 並存時取檔名版本日期（首個 6 位數字）最新者，並印出實際使用檔名（B-WR-16）。

    glob 不保證順序；原本取 matches[0] 可能載入舊版規則且毫無提示。
    """
    def tag(path: str) -> str:
        m = re.search(r"\d{6}", os.path.basename(path))
        return m.group(0) if m else ""

    ordered = sorted(matches, key=lambda p: (tag(p), os.path.basename(p)))
    chosen = ordered[-1]
    if len(matches) > 1:
        print(
            f"[build_sqlite] 找到 {len(matches)} 個版本，使用最新：{os.path.basename(chosen)}",
            file=sys.stderr,
        )
    return chosen


def _resolve_payment_csv_path() -> str:
    matches = glob.glob(os.path.join(RULE_SOURCE_DIR, "醫療服務給付項目*.csv"))
    if not matches:
        raise FileNotFoundError(
            f"payment CSV not found under {RULE_SOURCE_DIR!r} "
            "(expected glob pattern '醫療服務給付項目*.csv')"
        )
    return _pick_latest(matches)


def _resolve_drug_csv_path() -> str:
    matches = glob.glob(os.path.join(RULE_SOURCE_DIR, "藥品項查詢項目檔*.csv"))
    if not matches:
        raise FileNotFoundError(
            f"drug CSV not found under {RULE_SOURCE_DIR!r} "
            "(expected glob pattern '藥品項查詢項目檔*.csv')"
        )
    return _pick_latest(matches)


def main() -> None:
    db_path = os.path.join(DB_DIR, "rules.sqlite3")
    payment_csv_path = _resolve_payment_csv_path()
    drug_csv_path = _resolve_drug_csv_path()

    n_payment = loaders.load_payment_csv(db_path, payment_csv_path)
    n_drug = loaders.load_drug_csv(db_path, drug_csv_path)

    print(f"payment_rules: {n_payment} rows, drug_rules: {n_drug} rows")


if __name__ == "__main__":
    main()
