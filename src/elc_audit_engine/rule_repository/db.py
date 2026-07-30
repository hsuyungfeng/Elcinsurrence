"""規則庫 SQLite schema 定義與連線/查詢輔助函式。

`payment_rules` 與 `drug_rules` 兩張表刻意保持結構相同（欄位名稱一致），
讓下游（Plan 05 的單一查詢介面）可以用共用邏輯處理兩種代碼來源，
不需要為兩張表各寫一套查詢程式碼。
"""

import os
import sqlite3

SCHEMA_PAYMENT = (
    "CREATE TABLE IF NOT EXISTS payment_rules ("
    "code TEXT PRIMARY KEY, "
    "name TEXT, "
    "payment_text TEXT, "
    "effective_from TEXT, "
    "effective_to TEXT"
    ")"
)

SCHEMA_DRUG = (
    "CREATE TABLE IF NOT EXISTS drug_rules ("
    "code TEXT PRIMARY KEY, "
    "name TEXT, "
    "payment_text TEXT, "
    "effective_from TEXT, "
    "effective_to TEXT"
    ")"
)

_ALLOWED_TABLES = {"payment_rules", "drug_rules"}


def get_connection(db_path: str) -> sqlite3.Connection:
    """建立（或開啟）SQLite 連線，回傳前確保父目錄存在。

    Args:
        db_path: SQLite 檔案路徑。

    Returns:
        `row_factory` 設為 `sqlite3.Row` 的連線物件，方便以欄位名稱取值。
    """
    parent_dir = os.path.dirname(db_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """在給定連線上建立 `payment_rules`/`drug_rules` 兩張表（若不存在）。"""
    conn.execute(SCHEMA_PAYMENT)
    conn.execute(SCHEMA_DRUG)
    conn.commit()


def query_by_code(conn: sqlite3.Connection, table: str, code: str) -> sqlite3.Row | None:
    """依代碼查詢單一資料列。

    Args:
        conn: 既有的 SQLite 連線。
        table: 目標表名，必須是 `payment_rules` 或 `drug_rules`（白名單檢查）。
        code: 醫令代碼／藥品代號，一律透過 `?` 佔位符傳遞，絕不字串內插。

    Returns:
        對應的 `sqlite3.Row`，查無資料時回傳 `None`。

    Raises:
        ValueError: 當 `table` 不在允許的白名單內。
    """
    if table not in _ALLOWED_TABLES:
        raise ValueError(
            f"query_by_code: table {table!r} is not in the allowed set {_ALLOWED_TABLES}"
        )
    # table 已通過白名單檢查，才允許進入 f-string；code 一律走 ? 參數化查詢。
    cursor = conn.execute(f"SELECT * FROM {table} WHERE code = ?", (code,))
    return cursor.fetchone()
