"""rule_mapping 批次建置行為測試（mock llm_client，不需要 live server）。"""

import json
from unittest.mock import patch

from elc_audit_engine.rule_repository import db
from elc_audit_engine.rule_repository.mapping import build_mapping


def _make_test_db(db_path: str) -> None:
    conn = db.get_connection(db_path)
    db.init_schema(conn)
    conn.execute(
        "INSERT INTO payment_rules (code, name, payment_text, effective_from, effective_to) "
        "VALUES (?, ?, ?, ?, ?)",
        ("64140C", "甲床與手指重建術", "審查原則：" + ("條" * 100), "2016-04-01", None),
    )
    conn.execute(
        "INSERT INTO payment_rules (code, name, payment_text, effective_from, effective_to) "
        "VALUES (?, ?, ?, ?, ?)",
        ("06012C", "尿一般檢查", None, "2016-04-01", None),
    )
    conn.commit()
    conn.close()


def _make_test_docx_trees(path: str) -> None:
    tree = {
        "sample.docx": {
            "title": "sample",
            "level": 0,
            "path": "sample",
            "full_text": "",
            "children": [
                {
                    "title": "第一節 檢驗",
                    "level": 1,
                    "path": "第一節 檢驗",
                    "full_text": "尿一般檢查相關規定內容...",
                    "children": [],
                    "table_refs": [],
                }
            ],
            "table_refs": [],
        }
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tree, f, ensure_ascii=False)


def test_csv_reuse_fast_path_avoids_llm_call(tmp_path):
    """Test 1: payment_text > 60 字的代碼走 CSV 重用快速路徑，不呼叫 LLM。"""
    db_path = str(tmp_path / "test_rules.sqlite3")
    trees_path = str(tmp_path / "docx_trees.json")
    _make_test_db(db_path)
    _make_test_docx_trees(trees_path)

    with patch.object(build_mapping.llm_client, "smoke_test", return_value="1"), \
         patch.object(build_mapping.llm_client, "chat_completion") as mock_chat:
        # 06012C 的 payment_text 為 None，會走 LLM path；為了單獨驗證 64140C
        # 不觸發 LLM 呼叫，這裡讓 mock_chat 回傳一個可解析的回應供 06012C 使用。
        mock_chat.return_value = "條文位置：測試路徑\n條文摘要：本條文規範尿液一般檢查之審查原則與給付規定，適用於門診及住院申報案件。"
        result = build_mapping.build_rule_mapping(db_path, trees_path)

    conn = db.get_connection(db_path)
    row = conn.execute(
        "SELECT article_location, article_full_text, article_source FROM rule_mapping WHERE code=?",
        ("64140C",),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["article_source"] == "csv"
    assert row["article_full_text"] == "審查原則：" + ("條" * 100)
    assert result["csv_reuse_count"] == 1

    # 64140C 不應觸發任何 LLM 呼叫；mock_chat 只應為 06012C 被呼叫一次。
    assert mock_chat.call_count == 1
    called_code_in_prompt = mock_chat.call_args[0][1]
    assert "06012C" in called_code_in_prompt
    assert "64140C" not in called_code_in_prompt


def test_llm_path_triggered_for_short_payment_text(tmp_path):
    """Test 2: 短/空 payment_text 的代碼觸發 LLM 路徑，並正確解析回應。"""
    db_path = str(tmp_path / "test_rules.sqlite3")
    trees_path = str(tmp_path / "docx_trees.json")
    _make_test_db(db_path)
    _make_test_docx_trees(trees_path)

    with patch.object(build_mapping.llm_client, "smoke_test", return_value="1"), \
         patch.object(
             build_mapping.llm_client,
             "chat_completion",
             return_value="條文位置：測試路徑\n條文摘要：本條文規範尿液一般檢查之審查原則與給付規定，適用於門診及住院申報案件。",
         ):
        build_mapping.build_rule_mapping(db_path, trees_path)

    conn = db.get_connection(db_path)
    row = conn.execute(
        "SELECT article_location, article_full_text, article_source FROM rule_mapping WHERE code=?",
        ("06012C",),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["article_location"] == "測試路徑"
    assert row["article_full_text"] == "本條文規範尿液一般檢查之審查原則與給付規定，適用於門診及住院申報案件。"
    assert row["article_source"] == "docx"


def test_graceful_degradation_when_smoke_test_fails(tmp_path):
    """Test 3: smoke_test 失敗時，LLM path 的所有代碼優雅降級為 article_source=None，不拋例外。"""
    db_path = str(tmp_path / "test_rules.sqlite3")
    trees_path = str(tmp_path / "docx_trees.json")
    _make_test_db(db_path)
    _make_test_docx_trees(trees_path)

    with patch.object(build_mapping.llm_client, "smoke_test", side_effect=RuntimeError("server down")), \
         patch.object(build_mapping.llm_client, "chat_completion") as mock_chat:
        result = build_mapping.build_rule_mapping(db_path, trees_path)

    # 不應拋出例外（with 區塊順利結束），且 chat_completion 完全不應被呼叫。
    assert mock_chat.call_count == 0

    conn = db.get_connection(db_path)
    row = conn.execute(
        "SELECT article_location, article_full_text, article_source FROM rule_mapping WHERE code=?",
        ("06012C",),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["article_location"] is None
    assert row["article_full_text"] is None
    assert row["article_source"] is None
    assert result["no_match_count"] == 1
    # 64140C 仍走 CSV 重用路徑，不受 smoke test 失敗影響。
    assert result["csv_reuse_count"] == 1
