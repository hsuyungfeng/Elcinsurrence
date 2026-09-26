"""B-WR-07／B-WR-08：代碼正規化、生效期間、唯讀查詢、載入器不殘留舊碼。"""
import os
from datetime import date

import pytest

from elc_audit_engine.comparator import compare_case
from elc_audit_engine.comparator.models import Judgment, VERDICT_MANUAL
from elc_audit_engine.parsers.models import OrderRecord, SubmissionCase
from elc_audit_engine.rule_repository import db, get_rule, is_effective_on
from elc_audit_engine.rule_repository.errors import RuleRepositoryError
from elc_audit_engine.rule_repository.loaders.payment_loader import load_payment_csv
from elc_audit_engine.rule_repository.models import RuleResult


def _db(path, rows):
    conn = db.get_connection(path)
    db.init_schema(conn)
    conn.executemany(
        "INSERT INTO payment_rules (code, name, payment_text, effective_from, effective_to) VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def test_code_is_normalized(tmp_path):
    path = str(tmp_path / "r.sqlite3")
    _db(path, [("64140C", "n", "t", "2016-04-01", None)])
    assert get_rule(" 64140c ", db_path=path).found is True


def test_missing_db_raises_and_does_not_create_file(tmp_path):
    path = str(tmp_path / "nope" / "rules.sqlite3")
    with pytest.raises(RuleRepositoryError):
        get_rule("64140C", db_path=path)
    assert not os.path.exists(path)


def _rule(frm, to):
    return RuleResult(code="X", source="payment", name="n", payment_text="須記載",
                      effective_from=frm, effective_to=to, article_location=None,
                      article_full_text=None, article_source=None, found=True)


def test_is_effective_on():
    assert is_effective_on(_rule("2020-01-01", None), date(2026, 1, 1)) is True
    assert is_effective_on(_rule("2020-01-01", "2024-12-31"), date(2026, 1, 1)) is False
    assert is_effective_on(_rule("2027-01-01", None), date(2026, 1, 1)) is False
    assert is_effective_on(_rule(None, None), date(2026, 1, 1)) is None


def test_expired_rule_not_judged_on_visit_date():
    called = []
    case = SubmissionCase(visit_date="1150710", orders=(OrderRecord(code="X"),))
    result = compare_case(
        case, None, None,
        rule_lookup=lambda c: _rule("2020-01-01", "2024-12-31"),
        judge_fn=lambda *a: called.append(1) or Judgment("支持", "q"),
        narrative_fn=lambda *a: [],
    )
    assert called == []
    j = result.order_judgments[0].judgment
    assert j.verdict == VERDICT_MANUAL and "生效期間" in j.reason


def test_reload_drops_codes_removed_from_csv(tmp_path):
    path = str(tmp_path / "r.sqlite3")
    header = "診療項目代碼,中文項目名稱,支付規定,生效起日,生效迄日\n"
    v1 = tmp_path / "v1.csv"
    v1.write_text(header + "A0001C,甲,t,20200101,\nB0002C,乙,t,20200101,\n", encoding="utf-8-sig")
    v2 = tmp_path / "v2.csv"
    v2.write_text(header + "A0001C,甲,t,20200101,\n", encoding="utf-8-sig")
    load_payment_csv(path, str(v1))
    load_payment_csv(path, str(v2))
    assert get_rule("B0002C", db_path=path).found is False
