import os
import json
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

DATA_DIR = os.getenv("DATA_DIR", os.path.join(PROJECT_ROOT, "data"))
DB_DIR = os.getenv("DB_DIR", os.path.join(PROJECT_ROOT, "data/db"))
RAG_DIR = os.getenv("RAG_DIR", os.path.join(PROJECT_ROOT, "data/rag"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR", os.path.join(PROJECT_ROOT, "data/output"))
RULE_SOURCE_DIR = os.getenv(
    "RULE_SOURCE_DIR", os.path.join(PROJECT_ROOT, "officialdocument/審查注意事項")
)
LLAMA_CPP_BASE_URL = os.getenv("LLAMA_CPP_BASE_URL", "http://localhost:8080")
LLAMA_CONFIG_PATH = os.getenv(
    "LLAMA_CONFIG_PATH", os.path.join(PROJECT_ROOT, "config/llama_config.json")
)

# Phase 9-01：存取審計日誌路徑（JSON Lines，無 PHI）。
AUDIT_LOG_PATH = os.getenv("AUDIT_LOG_PATH", os.path.join(PROJECT_ROOT, "data/audit/access.log"))

# Phase 9-02：案件狀態機＋轉換歷史 SQLite 路徑（含 PHI payload，須入 .gitignore）。
CASES_DB_PATH = os.getenv("CASES_DB_PATH", os.path.join(DB_DIR, "cases.sqlite3"))


def load_llama_config() -> dict:
    """讀取 llama.cpp server 連線設定（config/llama_config.json）。

    缺檔時明確拋出 FileNotFoundError（fail-fast），避免下游 phase
    在設定未就緒的情況下產生難以追查的執行期錯誤。
    """
    if not os.path.isfile(LLAMA_CONFIG_PATH):
        raise FileNotFoundError(
            f"llama.cpp config file not found at expected path: {LLAMA_CONFIG_PATH}"
        )
    with open(LLAMA_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)
