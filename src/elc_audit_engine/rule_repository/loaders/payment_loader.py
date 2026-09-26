"""給付項目（payment）CSV -> SQLite `payment_rules` 表載入器。

來源 CSV 欄位對應（D-01/D-02 核心欄位）：
    診療項目代碼 -> code
    中文項目名稱 -> name
    支付規定     -> payment_text
    生效起日     -> effective_from（8 碼西元 YYYYMMDD）
    生效迄日     -> effective_to（8 碼西元 YYYYMMDD）
"""

from elc_audit_engine.rule_repository.loaders._csv_table import load_rule_csv


def load_payment_csv(db_path: str, csv_path: str) -> int:
    """讀取給付項目 CSV 並寫入 `payment_rules` 表。

    Args:
        db_path: 目標 SQLite 檔案路徑。
        csv_path: 來源 CSV 檔案路徑（`utf-8-sig` 編碼，含 BOM）。

    Returns:
        實際插入的資料列數。
    """
    return load_rule_csv(db_path, csv_path, "payment_rules", ('診療項目代碼', '中文項目名稱', '支付規定', '生效起日', '生效迄日'))
