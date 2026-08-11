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
# Phase 11-03（D-04）：院所層固定欄位設定檔路徑，可用環境變數覆寫（比照 LLAMA_CONFIG_PATH）。
FACILITY_CONFIG_PATH = os.getenv(
    "FACILITY_CONFIG_PATH", os.path.join(PROJECT_ROOT, "config/facility.json")
)

# 11.1-02（BLOCKER-1）：病歷資料來源根目錄（Phase 4 LocalFileProvider 契約，
# `<RECORDS_DIR>/<patient_id>/records.json`），可用環境變數覆寫（比照
# FACILITY_CONFIG_PATH 模式）；預設 data/samples/records。
RECORDS_DIR = os.getenv("RECORDS_DIR", os.path.join(DATA_DIR, "samples", "records"))

# Phase 9-01：存取審計日誌路徑（JSON Lines，無 PHI）。
AUDIT_LOG_PATH = os.getenv("AUDIT_LOG_PATH", os.path.join(PROJECT_ROOT, "data/audit/access.log"))

# Phase 9-02：案件狀態機＋轉換歷史 SQLite 路徑（含 PHI payload，須入 .gitignore）。
CASES_DB_PATH = os.getenv("CASES_DB_PATH", os.path.join(DB_DIR, "cases.sqlite3"))

# Phase 12：影像佐證附件儲存區根目錄（可由環境變數覆寫）。
ATTACHMENTS_DIR = os.getenv("ATTACHMENTS_DIR", os.path.join(DATA_DIR, "attachments"))


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


# 院所層設定必填欄位（D-04）：代號字碼／醫療院所名稱。
REQUIRED_FACILITY_FIELDS = ("code", "name")


def load_facility_config() -> dict:
    """讀取院所層固定欄位設定（config/facility.json，D-04）。

    缺檔時明確拋出 FileNotFoundError（fail-fast）；JSON 解析失敗、
    內容非物件或缺必填欄位（code/name）時拋出 ValueError——避免下游
    在院所設定未就緒的情況下，以空值靜默產出看似正常的申復清單 PDF
    （比照 load_llama_config「缺檔立刻失敗、不靜默空值」哲學）。
    """
    if not os.path.isfile(FACILITY_CONFIG_PATH):
        raise FileNotFoundError(
            f"facility config file not found at expected path: {FACILITY_CONFIG_PATH}"
        )
    with open(FACILITY_CONFIG_PATH, "r", encoding="utf-8") as f:
        try:
            cfg = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"facility config JSON 解析失敗：{FACILITY_CONFIG_PATH} ({exc})"
            ) from exc

    if not isinstance(cfg, dict):
        raise ValueError(
            f"facility config 內容需為 JSON 物件（單一院所）：{FACILITY_CONFIG_PATH}"
        )

    missing = [k for k in REQUIRED_FACILITY_FIELDS if not cfg.get(k)]
    if missing:
        raise ValueError(
            f"facility config 缺必填欄位：{', '.join(missing)}（{FACILITY_CONFIG_PATH}）"
        )
    return cfg
