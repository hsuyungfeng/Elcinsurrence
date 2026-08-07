import sys
import os

import pytest

# Insert project root to sys.path so `config` package resolves during collection
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Phase 9-01：server.py 在 import 期即以 _init_api_keys() 讀取 ELC_API_KEYS
# （fail-fast 設計，見 elc_audit_engine.auth）。測試環境若完全不設定此變數，
# 任何匯入 server 模組的測試檔會在收集階段就以 AuthConfigError 中止。
# 這裡以 setdefault 提供一組測試用固定 key（非真實憑證，公開於版控中亦
# 無風險）；各測試檔仍可用 monkeypatch 覆寫 app.config["ELC_API_KEYS"]
# 測試特定的認證情境（如 test_auth.py 的 401/200 案例）。
os.environ.setdefault("ELC_API_KEYS", "test-suite:0000000000TESTKEY0000")


@pytest.fixture
def tmp_rule_db_path(tmp_path) -> str:
    """回傳一個尚未建立的暫存 SQLite DB 路徑（str），供規則庫測試使用。

    只回傳路徑，不建立檔案 — 實際建表由 rule_repository.db 負責
    （Plan 02）。使用 pytest 的 tmp_path，確保測試執行不會寫入
    專案正式的 data/db/rules.sqlite3。
    """
    return str(tmp_path / "test_rules.sqlite3")
