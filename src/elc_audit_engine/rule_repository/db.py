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

# rule_mapping：D-04/D-05 的一次性 LLM 輔助建置預編譯快取表。
# 查詢階段（Phase 3-5）只對這張表做查表，絕不在查詢路徑呼叫 LLM。
# `source_version`：來源語料版本（來源 CSV 檔名 + docx 語料 hash），供
# 增量建置判斷「規則來源是否更新」——來源換版時該碼的 mapping 必須重算
# （P1-4）。既有資料庫升版時由 `init_schema` 補欄位（NULL 視為舊版待重建）。
SCHEMA_RULE_MAPPING = (
    "CREATE TABLE IF NOT EXISTS rule_mapping ("
    "code TEXT PRIMARY KEY, "
    "article_location TEXT, "
    "article_full_text TEXT, "
    "article_source TEXT, "
    "source_version TEXT"
    ")"
)

_ALLOWED_TABLES = {"payment_rules", "drug_rules", "rule_mapping"}

# 靜態、非動態組裝的查詢語句表 —— table 名稱固定寫死於此，供 `query_by_code` 使用。
_SELECT_BY_CODE_QUERIES = {
    "payment_rules": "SELECT * FROM payment_rules WHERE code = ?",
    "drug_rules": "SELECT * FROM drug_rules WHERE code = ?",
    "rule_mapping": "SELECT * FROM rule_mapping WHERE code = ?",
}


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
    """在給定連線上建立 `payment_rules`/`drug_rules`/`rule_mapping` 三張表（若不存在）。

    既有資料庫（schema 建於 P1-4 之前）的 `rule_mapping` 沒有
    `source_version` 欄位，這裡以 `ALTER TABLE` 補欄位（新列預設 NULL，
    代表「舊版、待增量重建」），避免升版需要整庫重建。
    """
    conn.execute(SCHEMA_PAYMENT)
    conn.execute(SCHEMA_DRUG)
    conn.execute(SCHEMA_RULE_MAPPING)
    _migrate_rule_mapping_source_version(conn)
    conn.commit()


def _migrate_rule_mapping_source_version(conn: sqlite3.Connection) -> None:
    """為舊版 `rule_mapping` 表補上 `source_version` 欄位（若缺）。"""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(rule_mapping)").fetchall()}
    if "source_version" not in columns:
        conn.execute("ALTER TABLE rule_mapping ADD COLUMN source_version TEXT")


def query_by_code(conn: sqlite3.Connection, table: str, code: str) -> sqlite3.Row | None:
    """依代碼查詢單一資料列。

    Args:
        conn: 既有的 SQLite 連線。
        table: 目標表名，必須是 `payment_rules`／`drug_rules`／`rule_mapping`
            其中之一（白名單檢查）。
        code: 醫令代碼／藥品代號，一律透過 `?` 佔位符傳遞，絕不字串內插。

    Returns:
        對應的 `sqlite3.Row`，查無資料時回傳 `None`。

    Raises:
        ValueError: 當 `table` 不在允許的白名單內。
    """
    if table not in _ALLOWED_TABLES:
        raise ValueError(
            "query_by_code: table " + repr(table) + " is not in the allowed set " + repr(_ALLOWED_TABLES)
        )
    # 靜態、非動態組裝的查詢語句表 —— table 名稱固定寫死於此（已通過白名單檢查）；
    # code 一律走 ? 參數化查詢，絕不字串內插。
    query = _SELECT_BY_CODE_QUERIES[table]
    cursor = conn.execute(query, (code,))
    return cursor.fetchone()


def upsert_rule_mapping(
    conn: sqlite3.Connection,
    code: str,
    article_location: str | None,
    article_full_text: str | None,
    article_source: str | None,
    source_version: str | None = None,
) -> None:
    """寫入（或覆寫）一筆 `rule_mapping` 快取列。

    一律透過 `?` 佔位符參數化查詢，絕不字串內插（T-02-08 mitigation）。

    Args:
        conn: 既有的 SQLite 連線。
        code: 醫令代碼／藥品代號（主鍵）。
        article_location: 條文位置（CSV 來源用 `CSV:{table}.payment_text`
            標記；docx 來源用 tree node 的 `path`）。
        article_full_text: 條文全文（或摘要）。
        article_source: 來源標記，`"csv"` / `"docx"` / `None`（無法比對或
            LLM 未通過 smoke test 而優雅降級時）。
        source_version: 建置此筆 mapping 時的來源語料版本
            （`{CSV版本}:{docx語料hash}`）。供增量建置判斷該碼是否
            需要因來源換版而重算；`None` 表示舊版/無版本（P1-4）。
    """
    conn.execute(
        "INSERT OR REPLACE INTO rule_mapping "
        "(code, article_location, article_full_text, article_source, source_version) "
        "VALUES (?, ?, ?, ?, ?)",
        (code, article_location, article_full_text, article_source, source_version),
    )
