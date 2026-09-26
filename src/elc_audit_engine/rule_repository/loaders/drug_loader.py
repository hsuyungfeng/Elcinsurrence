"""藥品項目（drug）CSV -> SQLite `drug_rules` 表載入器。

來源 CSV 欄位對應（D-01/D-02 核心欄位）：
    藥品代號     -> code
    藥品中文名稱 -> name
    給付規定     -> payment_text
    有效起日     -> effective_from（7 碼民國 RRRMMDD）
    有效迄日     -> effective_to（7 碼民國 RRRMMDD）
"""

from elc_audit_engine.rule_repository.loaders._csv_table import load_rule_csv


def load_drug_csv(db_path: str, csv_path: str) -> int:
    """讀取藥品項目 CSV 並寫入 `drug_rules` 表。

    Args:
        db_path: 目標 SQLite 檔案路徑。
        csv_path: 來源 CSV 檔案路徑（`utf-8-sig` 編碼，含 BOM）。

    Returns:
        實際插入的資料列數。
    """
    return load_rule_csv(db_path, csv_path, "drug_rules", ('藥品代號', '藥品中文名稱', '給付規定', '有效起日', '有效迄日'))
