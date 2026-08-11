"""dates.py 與 db.py 的獨立單元測試（不依賴 Plan 01 Wave 0 骨架，即時可綠）。"""

import pytest

from elc_audit_engine.rule_repository import db
from elc_audit_engine.rule_repository.loaders.dates import parse_flexible_date


def test_parse_flexible_date_gregorian():
    assert parse_flexible_date("20160401") == "2016-04-01"


def test_parse_flexible_date_roc():
    assert parse_flexible_date("1121001") == "2023-10-01"


def test_parse_flexible_date_empty_sentinels():
    assert parse_flexible_date("") is None
    assert parse_flexible_date("null") is None


def test_parse_flexible_date_rejects_invalid_month():
    with pytest.warns(UserWarning, match="invalid calendar date"):
        assert parse_flexible_date("20161301") is None


def test_parse_flexible_date_rejects_invalid_day():
    with pytest.warns(UserWarning, match="invalid calendar date"):
        assert parse_flexible_date("20160230") is None


def test_parse_flexible_date_accepts_leap_day():
    assert parse_flexible_date("20200229") == "2020-02-29"


def test_parse_flexible_date_rejects_non_leap_day():
    with pytest.warns(UserWarning, match="invalid calendar date"):
        assert parse_flexible_date("20210229") is None


def test_db_connection_schema_and_query_roundtrip(tmp_rule_db_path):
    conn = db.get_connection(tmp_rule_db_path)
    db.init_schema(conn)

    conn.execute(
        "INSERT INTO payment_rules (code, name, payment_text, effective_from, effective_to) "
        "VALUES (?, ?, ?, ?, ?)",
        ("64140C", "測試項目", "測試支付規定", "2016-04-01", None),
    )
    conn.commit()

    row = db.query_by_code(conn, "payment_rules", "64140C")
    assert row is not None
    assert row["name"] == "測試項目"

    missing = db.query_by_code(conn, "payment_rules", "NOPE")
    assert missing is None

    with pytest.raises(ValueError):
        db.query_by_code(conn, "not_a_real_table", "64140C")
