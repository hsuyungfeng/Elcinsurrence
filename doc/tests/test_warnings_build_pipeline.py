"""Warning 第三批：建置管線（B-WR-13/15/16）。"""
import json
from unittest.mock import patch

import pytest

from elc_audit_engine.rule_repository import db
from elc_audit_engine.rule_repository.mapping import build_mapping, versions
from elc_audit_engine.rule_repository.scripts import build_sqlite


def _setup(tmp_path):
    path = str(tmp_path / "r.sqlite3")
    conn = db.get_connection(path)
    db.init_schema(conn)
    conn.execute("INSERT INTO payment_rules VALUES ('06012C','尿一般檢查',NULL,'2016-04-01',NULL)")
    conn.commit()
    conn.close()
    trees = tmp_path / "t.json"
    trees.write_text(json.dumps({}), encoding="utf-8")
    return path, str(trees)


def test_incremental_without_version_is_refused(tmp_path):
    path, trees = _setup(tmp_path)
    with pytest.raises(ValueError):
        build_mapping.build_rule_mapping(path, trees, source_version=None, incremental=True)


def test_null_version_rows_are_retried(tmp_path):
    path, trees = _setup(tmp_path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO rule_mapping (code, source_version) VALUES ('06012C', NULL)")
    conn.commit()
    conn.close()
    with patch.object(build_mapping.llm_client, "smoke_test", return_value="2"):
        result = build_mapping.build_rule_mapping(path, trees, source_version="v1", incremental=True)
    assert result["processed_count"] == 1


@pytest.mark.parametrize("reply", ['{"content": string}', "1", ""])
def test_bad_smoke_reply_degrades(tmp_path, reply):
    path, trees = _setup(tmp_path)
    with patch.object(build_mapping.llm_client, "smoke_test", return_value=reply), \
         patch.object(build_mapping.llm_client, "chat_completion") as chat:
        result = build_mapping.build_rule_mapping(path, trees, source_version="v1")
    assert chat.call_count == 0
    assert result["degraded_count"] == 1


def test_extract_csv_version_raises_on_missing_file(tmp_path):
    with pytest.raises(OSError):
        versions.extract_csv_version(str(tmp_path / "醫療服務給付項目251027.csv"))


def test_pick_latest_csv_version():
    picked = build_sqlite._pick_latest([
        "/x/醫療服務給付項目251027準確板.csv",
        "/x/醫療服務給付項目260301準確板.csv",
        "/x/醫療服務給付項目240101.csv",
    ])
    assert picked.endswith("260301準確板.csv")
