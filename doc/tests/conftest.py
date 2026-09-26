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
def client(monkeypatch, tmp_path):
    import server
    from elc_audit_engine.case_store import CaseStore

    monkeypatch.setattr(server, "_case_store", CaseStore(db_path=str(tmp_path / "cases.sqlite3")))
    monkeypatch.setattr(server, "_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(server, "_RAW_DIR", str(tmp_path / "uploads" / "raw"))
    server.app.config["TESTING"] = True
    monkeypatch.setitem(server.app.config, "ELC_API_KEYS", {"valid-key-123": "clinic_a"})
    with server.app.test_client() as c:
        c.environ_base["HTTP_X_API_KEY"] = "valid-key-123"
        yield c
