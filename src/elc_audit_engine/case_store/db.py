"""案件狀態機 SQLite schema 定義與連線輔助函式。

沿用 `rule_repository/db.py` 既有慣例：schema 以模組層常數字串定義、
表名以白名單管控（不動態組裝 SQL 表名）、查詢一律走 `?` 參數化。
"""

from __future__ import annotations

import os
import sqlite3

# cases：案件目前狀態與最新 payload 快照。
#
# 欄位說明：
# - `kind`：`"sampling"`（抽樣預審）或 `"appeal"`（核減申復），對應
#   pipeline 兩個入口（`run_presubmission_check` / `run_case_pipeline`）。
# - `payload_json`：案件資料原樣 JSON（含 PHI：SOAP／病歷號／姓名等）；
#   因此 `data/db/cases.sqlite3` 必須被 `.gitignore` 排除，絕不進版控。
# - `failure_reason`：**只在 state='failed' 時有值**。與 `payload_json`
#   內的業務結論（如 `support_level`）分屬不同欄位，不可用同一欄表達
#   「系統失敗」與「判定裸奔」——此為 P1-1 教訓的直接延伸：系統故障
#   必須與業務結論可區分，不得混在一起讓下游誤判。
SCHEMA_CASES = (
    "CREATE TABLE IF NOT EXISTS cases ("
    "case_id TEXT PRIMARY KEY, "
    "kind TEXT NOT NULL, "
    "state TEXT NOT NULL, "
    "case_seq TEXT, "
    "order_code TEXT, "
    "payload_json TEXT, "
    "created_at TEXT NOT NULL, "
    "updated_at TEXT NOT NULL, "
    "failure_reason TEXT"
    ")"
)

# case_transitions：每次成功轉換留一列，供申復流程可追溯。
#
# - `from_state` 為 NULL 代表建案（初始寫入 imported 的那一列）。
# - `actor` 記錄推進者識別（09-03 會傳入 `g.caller_id`）；**不記 PHI**，
#   與審計日誌（`AUDIT_LOG_PATH`）同一原則：只記識別碼層級的存取事實。
SCHEMA_TRANSITIONS = (
    "CREATE TABLE IF NOT EXISTS case_transitions ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "case_id TEXT NOT NULL, "
    "from_state TEXT, "
    "to_state TEXT NOT NULL, "
    "reason TEXT, "
    "actor TEXT, "
    "created_at TEXT NOT NULL"
    ")"
)

# 同步版任務佇列的主查詢路徑：依 (state, kind) 取件。
SCHEMA_INDEX_CASES_STATE_KIND = (
    "CREATE INDEX IF NOT EXISTS idx_cases_state_kind ON cases (state, kind)"
)
# 依 case_id 取歷史，依 id 升冪即為時間順序。
SCHEMA_INDEX_TRANSITIONS_CASE = (
    "CREATE INDEX IF NOT EXISTS idx_transitions_case ON case_transitions (case_id, id)"
)

# SQL 表名一律寫死於靜態語句，不動態組裝——與 rule_repository 同慣例
# （T-09-13 mitigation）。目前本模組內部查詢皆為靜態字串，此白名單
# 供未來新增查詢介面時比照 rule_repository 的防線沿用。
_ALLOWED_TABLES = {"cases", "case_transitions"}


def get_connection(db_path: str) -> sqlite3.Connection:
    """建立（或開啟）SQLite 連線，回傳前確保父目錄存在。

    Args:
        db_path: SQLite 檔案路徑。

    Returns:
        `row_factory` 設為 `sqlite3.Row` 的連線物件，並已啟用外鍵約束。
    """
    parent_dir = os.path.dirname(db_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(db_path: str) -> None:
    """在 `db_path` 指向的資料庫建立 `cases`／`case_transitions` 兩表與索引（冪等）。"""
    conn = get_connection(db_path)
    try:
        conn.execute(SCHEMA_CASES)
        conn.execute(SCHEMA_TRANSITIONS)
        conn.execute(SCHEMA_INDEX_CASES_STATE_KIND)
        conn.execute(SCHEMA_INDEX_TRANSITIONS_CASE)
        conn.commit()
    finally:
        conn.close()
