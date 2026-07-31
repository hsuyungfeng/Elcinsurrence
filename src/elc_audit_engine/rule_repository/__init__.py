"""規則庫：SQLite payment_rules/drug_rules + 自建 docx 樹狀索引 + rule_mapping。

對外只曝露 `get_rule(code)` 這一個查詢函式（D-07/D-08）：內部把
payment_rules/drug_rules（Plan 02）與 rule_mapping（Plan 04）的查詢結果
組合成單一 `RuleResult`，下游（Phase 3-5）不需要知道規則庫內部分成幾層。

`get_rule` 在查詢路徑上完全不呼叫 LLM、不發任何網路請求（D-05）——
LLM 只在 rule_mapping 的一次性批次建置階段（Plan 04）使用過。
"""

import os
import sqlite3
import warnings

from elc_audit_engine.rule_repository import db, models

_DEFAULT_DB_PATH = None


def _resolve_db_path(db_path: str | None) -> str:
    if db_path is not None:
        return db_path
    from config import settings

    return os.path.join(settings.DB_DIR, "rules.sqlite3")


def get_rule(code: str, db_path: str | None = None) -> models.RuleResult:
    """依醫令代碼／藥品代號查詢規則庫，回傳單一結構化結果（D-07/D-08）。

    內部依序查詢 `payment_rules`／`drug_rules`（基礎資料）與
    `rule_mapping`（Plan 04 預編譯的條文位置/全文快取）；查詢路徑完全
    零 LLM 呼叫（D-05）。任何 SQLite 層級的錯誤都會被捕捉並降級為
    「查無」結果，絕不將原始例外向呼叫端拋出。

    Args:
        code: 醫令代碼（診療項目代碼）或藥品代號。
        db_path: `rules.sqlite3` 路徑；未提供時預設解析為
            `config.settings.DB_DIR/rules.sqlite3`（測試可透過此參數
            注入暫存資料庫路徑）。

    Returns:
        `RuleResult`。代碼不存在於 payment_rules/drug_rules 時
        `found=False`；代碼存在但尚無 rule_mapping 快取項目時，
        `article_location`/`article_full_text`/`article_source`
        皆為 `None`，但 `found` 仍為 `True`。
    """
    resolved_path = _resolve_db_path(db_path)

    try:
        conn = db.get_connection(resolved_path)
        try:
            row = db.query_by_code(conn, "payment_rules", code)
            source = "payment"
            if row is None:
                row = db.query_by_code(conn, "drug_rules", code)
                source = "drug"
            if row is None:
                return models.not_found(code)

            mapping_row = db.query_by_code(conn, "rule_mapping", code)
            article_location = mapping_row["article_location"] if mapping_row else None
            article_full_text = mapping_row["article_full_text"] if mapping_row else None
            article_source = mapping_row["article_source"] if mapping_row else None

            return models.RuleResult(
                code=code,
                source=source,
                name=row["name"],
                payment_text=row["payment_text"],
                effective_from=row["effective_from"],
                effective_to=row["effective_to"],
                article_location=article_location,
                article_full_text=article_full_text,
                article_source=article_source,
                found=True,
            )
        finally:
            conn.close()
    except sqlite3.Error as exc:
        warnings.warn(f"get_rule({code!r}) SQLite error, degrading to not_found: {exc}")
        return models.not_found(code)
