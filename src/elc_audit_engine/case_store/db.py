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
# - `kind`：`"sampling"`（抽樣預審）、`"appeal"`（核減申復）或 `"monthly"`
#   （當月申報檔預審，case_id 為內容雜湊 `MON-...`，批次見 payload.batch）。
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

# case_artifacts：案件衍生產物（目前為 appeal_draft：/api/appeal/generate
# 產出的 render_appeal_json 契約），供佐證包列印等下游讀取（A-CR-04）。
# 每案每種產物一列，重新生成即覆寫（updated_at 記最後生成時間）。
# 內容含 PHI，與 cases.payload_json 同屬 cases.sqlite3，不進版控。
SCHEMA_ARTIFACTS = (
    "CREATE TABLE IF NOT EXISTS case_artifacts ("
    "case_id TEXT NOT NULL, "
    "name TEXT NOT NULL, "
    "content_json TEXT NOT NULL, "
    "updated_at TEXT NOT NULL, "
    "PRIMARY KEY (case_id, name)"
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
# 地端橋接任務查詢（kind='bridge'，依 payload.status 篩選後按 created_at 排序）。
# 取代舊的「讀 1000 筆再於 Python 過濾」寫法（P1-1），避免歷史紀錄超過上限時靜默丟件。
SCHEMA_INDEX_CASES_BRIDGE_STATUS = (
    "CREATE INDEX IF NOT EXISTS idx_cases_bridge_status "
    "ON cases (kind, json_extract(payload_json, '$.status'), created_at)"
)
# 當月申報批次查詢（kind='monthly'，payload.batch 如 MONTHLY-202307）。
# 表達式索引不需遷移既有資料表；IF NOT EXISTS 對舊 DB 冪等。
SCHEMA_INDEX_CASES_BATCH = (
    "CREATE INDEX IF NOT EXISTS idx_cases_batch "
    "ON cases (kind, json_extract(payload_json, '$.batch'))"
)

# SQL 表名一律寫死於靜態語句，不動態組裝——與 rule_repository 同慣例
# （T-09-13 mitigation）。若日後新增依表名查詢的介面，再比照
# rule_repository 加白名單。


# soap_templates：通用處置／手術範例病歷快取（Plan 15-04）。
# 鍵為 (order_code, primary_diagnosis)：同一醫令＋同一主診斷共用一份範本，避免重複呼叫 LLM。
# `soap_json` 為 {"s","o","a","p"}；`source` 記錄來源（llm_validated／physician_edited）。
SCHEMA_SOAP_TEMPLATES = (
    "CREATE TABLE IF NOT EXISTS soap_templates ("
    "order_code TEXT NOT NULL, "
    "primary_diagnosis TEXT NOT NULL, "
    "soap_json TEXT NOT NULL, "
    "source TEXT NOT NULL, "
    "quality_score INTEGER, "
    "created_at TEXT NOT NULL, "
    "PRIMARY KEY (order_code, primary_diagnosis)"
    ")"
)

# Phase 29: soap_drafts（LLM 預生成 SOAP 草稿、醫師審核與 HIS 回填進度）
SCHEMA_SOAP_DRAFTS = (
    "CREATE TABLE IF NOT EXISTS soap_drafts ("
    "draft_id TEXT PRIMARY KEY, "
    "case_id TEXT NOT NULL, "
    "order_code TEXT, "
    "version INTEGER NOT NULL DEFAULT 1, "
    "state TEXT NOT NULL, "
    "soap_json TEXT NOT NULL, "
    "content_hash TEXT NOT NULL, "
    "quality_score INTEGER, "
    "quality_issues_json TEXT, "
    "comparison_json TEXT, "
    "reviewer_id TEXT, "
    "review_decision TEXT, "
    "review_reason TEXT, "
    "reviewed_at TEXT, "
    "pushed_at TEXT, "
    "agent_id TEXT, "
    "failure_reason TEXT, "
    "his_job_id TEXT, "
    "his_machine_id TEXT, "
    "created_at TEXT NOT NULL, "
    "updated_at TEXT NOT NULL"
    ")"
)
SCHEMA_INDEX_SOAP_DRAFTS_CASE = (
    "CREATE INDEX IF NOT EXISTS idx_soap_drafts_case ON soap_drafts (case_id)"
)
SCHEMA_INDEX_SOAP_DRAFTS_STATE = (
    "CREATE INDEX IF NOT EXISTS idx_soap_drafts_state ON soap_drafts (state)"
)
SCHEMA_INDEX_SOAP_DRAFTS_CASE_HASH = (
    "CREATE INDEX IF NOT EXISTS idx_soap_drafts_case_hash ON soap_drafts (case_id, content_hash)"
)

# soap_draft_history：醫師編修歷史與版本追蹤
SCHEMA_SOAP_DRAFT_HISTORY = (
    "CREATE TABLE IF NOT EXISTS soap_draft_history ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "draft_id TEXT NOT NULL, "
    "version INTEGER NOT NULL, "
    "state TEXT NOT NULL, "
    "soap_json TEXT NOT NULL, "
    "content_hash TEXT NOT NULL, "
    "reviewer_id TEXT, "
    "review_decision TEXT, "
    "review_reason TEXT, "
    "created_at TEXT NOT NULL"
    ")"
)
SCHEMA_INDEX_SOAP_DRAFT_HIST = (
    "CREATE INDEX IF NOT EXISTS idx_soap_draft_hist ON soap_draft_history (draft_id, version)"
)

# agent_heartbeats：Windows Agent 心跳登記表
SCHEMA_AGENT_HEARTBEATS = (
    "CREATE TABLE IF NOT EXISTS agent_heartbeats ("
    "agent_id TEXT PRIMARY KEY, "
    "version TEXT, "
    "his_status TEXT, "
    "client_timestamp TEXT, "
    "last_heartbeat_at TEXT NOT NULL"
    ")"
)

# soap_recording_sessions：SoapVoice 錄音接收冪等登記表（Phase 30）
SCHEMA_SOAP_RECORDING_SESSIONS = (
    "CREATE TABLE IF NOT EXISTS soap_recording_sessions ("
    "session_id TEXT PRIMARY KEY, "
    "draft_id TEXT NOT NULL, "
    "caller TEXT, "
    "created_at TEXT NOT NULL"
    ")"
)

# soap_settings：全域與診所層 SOAP 設定鍵值表（Phase 30：自動接入開關等）
SCHEMA_SOAP_SETTINGS = (
    "CREATE TABLE IF NOT EXISTS soap_settings ("
    "key TEXT PRIMARY KEY, "
    "value TEXT NOT NULL, "
    "updated_at TEXT NOT NULL, "
    "updated_by TEXT"
    ")"
)

# ── Phase 31: 循環狀態機與多連線監控資料表 ─────────────────────────────

SCHEMA_RECORDING_CYCLES = (
    "CREATE TABLE IF NOT EXISTS recording_cycles ("
    "cycle_id TEXT PRIMARY KEY, "
    "machine_id TEXT NOT NULL, "
    "room_id TEXT, "
    "state TEXT NOT NULL, "
    "command_id TEXT UNIQUE NOT NULL, "
    "stop_command_id TEXT, "
    "session_id TEXT UNIQUE, "
    "draft_id TEXT, "
    "total_chunks INTEGER, "
    "audio_sha256 TEXT, "
    "upload_complete INTEGER NOT NULL DEFAULT 0, "
    "audio_path TEXT, "
    "transcript_path TEXT, "
    "extras_json TEXT, "
    "last_error TEXT, "
    "created_by TEXT, "
    "created_at TEXT NOT NULL, "
    "updated_at TEXT NOT NULL, "
    "archived_at TEXT"
    ")"
)

SCHEMA_INDEX_RECORDING_CYCLES_ACTIVE = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_recording_cycles_machine_active "
    "ON recording_cycles (machine_id) "
    "WHERE state NOT IN ('ARCHIVED', 'ABANDONED')"
)

SCHEMA_CYCLE_EVENTS = (
    "CREATE TABLE IF NOT EXISTS cycle_events ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "cycle_id TEXT NOT NULL, "
    "from_state TEXT, "
    "to_state TEXT NOT NULL, "
    "actor TEXT, "
    "reason_code TEXT, "
    "created_at TEXT NOT NULL"
    ")"
)

SCHEMA_CYCLE_CHUNKS = (
    "CREATE TABLE IF NOT EXISTS cycle_chunks ("
    "cycle_id TEXT NOT NULL, "
    "seq INTEGER NOT NULL, "
    "sha256 TEXT NOT NULL, "
    "size_bytes INTEGER NOT NULL, "
    "path TEXT NOT NULL, "
    "received_at TEXT NOT NULL, "
    "PRIMARY KEY (cycle_id, seq)"
    ")"
)

SCHEMA_CYCLE_CONFIRMATIONS = (
    "CREATE TABLE IF NOT EXISTS cycle_confirmations ("
    "cycle_id TEXT PRIMARY KEY, "
    "draft_id TEXT NOT NULL, "
    "version INTEGER NOT NULL, "
    "content_hash TEXT NOT NULL, "
    "soap_json TEXT NOT NULL, "
    "extras_json TEXT, "
    "reviewer_id TEXT, "
    "confirmed_at TEXT NOT NULL"
    ")"
)

SCHEMA_CLIENT_PRESENCE = (
    "CREATE TABLE IF NOT EXISTS client_presence ("
    "machine_id TEXT PRIMARY KEY, "
    "machine_name TEXT, "
    "room_id TEXT, "
    "bar_state TEXT, "
    "soapvoice_state TEXT, "
    "chunks_pending INTEGER, "
    "app_version TEXT, "
    "client_subnet TEXT, "
    "caller_id TEXT, "
    "last_seen_at TEXT NOT NULL"
    ")"
)


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
    """在 `db_path` 指向的資料庫建立各業務表與索引（冪等）。"""
    conn = get_connection(db_path)
    try:
        conn.execute(SCHEMA_CASES)
        conn.execute(SCHEMA_TRANSITIONS)
        conn.execute(SCHEMA_ARTIFACTS)
        conn.execute(SCHEMA_INDEX_CASES_STATE_KIND)
        conn.execute(SCHEMA_INDEX_TRANSITIONS_CASE)
        conn.execute(SCHEMA_INDEX_CASES_BATCH)
        conn.execute(SCHEMA_INDEX_CASES_BRIDGE_STATUS)
        conn.execute(SCHEMA_SOAP_TEMPLATES)
        conn.execute(SCHEMA_SOAP_DRAFTS)
        conn.execute(SCHEMA_INDEX_SOAP_DRAFTS_CASE)
        conn.execute(SCHEMA_INDEX_SOAP_DRAFTS_STATE)
        conn.execute(SCHEMA_INDEX_SOAP_DRAFTS_CASE_HASH)
        conn.execute(SCHEMA_SOAP_DRAFT_HISTORY)
        conn.execute(SCHEMA_INDEX_SOAP_DRAFT_HIST)
        conn.execute(SCHEMA_AGENT_HEARTBEATS)
        conn.execute(SCHEMA_SOAP_RECORDING_SESSIONS)
        conn.execute(SCHEMA_SOAP_SETTINGS)
        conn.execute(SCHEMA_RECORDING_CYCLES)
        conn.execute(SCHEMA_INDEX_RECORDING_CYCLES_ACTIVE)
        conn.execute(SCHEMA_CYCLE_EVENTS)
        conn.execute(SCHEMA_CYCLE_CHUNKS)
        conn.execute(SCHEMA_CYCLE_CONFIRMATIONS)
        conn.execute(SCHEMA_CLIENT_PRESENCE)

        # 冪等加欄：Phase 31 his_job_id, his_machine_id
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(soap_drafts)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        if "his_job_id" not in existing_cols:
            conn.execute("ALTER TABLE soap_drafts ADD COLUMN his_job_id TEXT")
        if "his_machine_id" not in existing_cols:
            conn.execute("ALTER TABLE soap_drafts ADD COLUMN his_machine_id TEXT")

        conn.commit()
    finally:
        conn.close()
