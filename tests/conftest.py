import sys
import os

import pytest

# Insert project root to sys.path so `config` package resolves during collection
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture
def tmp_rule_db_path(tmp_path) -> str:
    """回傳一個尚未建立的暫存 SQLite DB 路徑（str），供規則庫測試使用。

    只回傳路徑，不建立檔案 — 實際建表由 rule_repository.db 負責
    （Plan 02）。使用 pytest 的 tmp_path，確保測試執行不會寫入
    專案正式的 data/db/rules.sqlite3。
    """
    return str(tmp_path / "test_rules.sqlite3")
