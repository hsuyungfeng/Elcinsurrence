"""get_rule() 錯誤語意契約測試（P0-2）。

鎖定「系統性故障 ≠ 查無此醫令」：

- DB 檔案不存在／連線失敗 → 拋 `RuleRepositoryError`（infra 故障）
- 表不存在（schema 未建）→ 拋 `RuleRepositoryError`
- 查詢路徑上真正的 SQLite 錯誤（如 locked DB）→ 拋 `RuleRepositoryError`
- 代碼真的不在表內 → 回傳 `found=False`（正常結果，不拋例外）

測試建立真實的 SQLite 檔案（而非 mock），確保鎖定的是真實行為。
"""

import sqlite3

import pytest

from elc_audit_engine.rule_repository import db, get_rule
from elc_audit_engine.rule_repository.errors import RuleRepositoryError


def test_get_rule_missing_db_file_raises_rule_repository_error(tmp_path):
    """DB 檔案不存在：這是系統性故障，必須拋 RuleRepositoryError。"""
    missing_db = str(tmp_path / "no_such_rules.sqlite3")
    with pytest.raises(RuleRepositoryError):
        get_rule("64140C", db_path=missing_db)


def test_get_rule_missing_table_raises_rule_repository_error(tmp_path):
    """檔案存在但 schema 未建（無 payment_rules 表）：同樣是系統性故障。"""
    db_path = str(tmp_path / "empty_rules.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.close()

    with pytest.raises(RuleRepositoryError):
        get_rule("64140C", db_path=db_path)


def test_get_rule_locked_db_raises_rule_repository_error(tmp_path):
    """DB 被鎖定（SQLite 層級錯誤）：必須拋 RuleRepositoryError，不得偽裝成查無。"""
    db_path = str(tmp_path / "locked_rules.sqlite3")
    conn = db.get_connection(db_path)
    db.init_schema(conn)
    conn.execute(
        "INSERT INTO payment_rules (code, name, payment_text, effective_from, effective_to) "
        "VALUES (?, ?, ?, ?, ?)",
        ("64140C", "甲床與手指重建術", "審查原則", "2016-04-01", None),
    )
    conn.commit()
    # 開啟第二個連線並取得 EXCLUSIVE lock，讓後續查詢觸發 sqlite3.OperationalError
    locker = db.get_connection(db_path)
    locker.execute("BEGIN EXCLUSIVE")

    try:
        with pytest.raises(RuleRepositoryError):
            get_rule("64140C", db_path=db_path)
    finally:
        locker.close()


def test_get_rule_unknown_code_still_returns_not_found(tmp_path):
    """正常「查無」仍回傳 found=False，不受錯誤語意變更影響。"""
    db_path = str(tmp_path / "known_rules.sqlite3")
    conn = db.get_connection(db_path)
    db.init_schema(conn)
    conn.execute(
        "INSERT INTO payment_rules (code, name, payment_text, effective_from, effective_to) "
        "VALUES (?, ?, ?, ?, ?)",
        ("64140C", "甲床與手指重建術", "審查原則", "2016-04-01", None),
    )
    conn.commit()
    conn.close()

    result = get_rule("ZZZZZZ99", db_path=db_path)
    assert result.found is False
    assert result.source == "unknown"
