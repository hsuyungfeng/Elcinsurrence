"""code review 修正回歸測試的共用設定（比照 tests/conftest.py）。

執行：uv run pytest doc/tests
"""
import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("ELC_API_KEYS", "test-suite:0000000000TESTKEY0000")


@pytest.fixture
def app(tmp_path):
    """create_app 隔離實例：暫存 CaseStore／上傳目錄、固定測試 key。"""
    from elc_audit_engine.api import create_app
    from elc_audit_engine.case_store import CaseStore

    return create_app(
        {
            "TESTING": True,
            "ELC_API_KEYS": {"valid-key-123": "clinic_a"},
            "ELC_UPLOAD_DIR": str(tmp_path / "uploads"),
            "ELC_RAW_DIR": str(tmp_path / "uploads" / "raw"),
        },
        case_store=CaseStore(db_path=str(tmp_path / "cases.sqlite3")),
        migrate_legacy=False,
    )


@pytest.fixture
def store(app):
    return app.extensions["elc"].case_store


@pytest.fixture
def client(app):
    with app.test_client() as c:
        c.environ_base["HTTP_X_API_KEY"] = "valid-key-123"
        yield c
