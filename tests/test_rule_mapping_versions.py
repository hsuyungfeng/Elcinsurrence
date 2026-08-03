"""rule_mapping 版本追蹤與增量建置測試（P1-4）。"""

import json
from unittest.mock import patch

from elc_audit_engine.rule_repository import db
from elc_audit_engine.rule_repository.mapping import build_mapping, versions


def test_extract_csv_version_payment():
    v = versions.extract_csv_version(
        "醫療服務給付項目251027準確板_已優化填入支付規定.csv"
    )
    assert v == "251027"


def test_extract_csv_version_drug():
    v = versions.extract_csv_version(
        "藥品項查詢項目檔260605 AI 摘要支付價大於0.csv"
    )
    assert v == "260605"


def test_extract_csv_version_no_digits_is_unknown():
    assert versions.extract_csv_version("rules.csv") == "unknown"


def test_hash_docx_trees_changes_with_content(tmp_path):
    p1 = tmp_path / "t1.json"
    p2 = tmp_path / "t2.json"
    p1.write_text('{"a": {"full_text": "x"}}', encoding="utf-8")
    p2.write_text('{"a": {"full_text": "x", "extra": 1}}', encoding="utf-8")
    h1 = versions.hash_docx_trees(str(p1))
    h2 = versions.hash_docx_trees(str(p2))
    assert h1 != h2
    assert len(h1) == 12


def test_build_source_version_format(tmp_path):
    pay = tmp_path / "醫療服務給付項目251027.csv"
    drug = tmp_path / "藥品項查詢項目檔260605.csv"
    trees = tmp_path / "docx_trees.json"
    pay.write_text("x", encoding="utf-8")
    drug.write_text("x", encoding="utf-8")
    trees.write_text("{}", encoding="utf-8")
    v = versions.build_source_version(str(pay), str(drug), str(trees))
    assert v.startswith("251027|260605|")
    assert len(v.split("|")[2]) == 12


def _make_db(db_path, codes, source_version=None):
    conn = db.get_connection(db_path)
    db.init_schema(conn)
    for code, name, text in codes:
        conn.execute(
            "INSERT INTO payment_rules (code, name, payment_text, effective_from, effective_to) "
            "VALUES (?, ?, ?, ?, ?)",
            (code, name, text, "2016-04-01", None),
        )
        if source_version is not None:
            conn.execute(
                "INSERT OR REPLACE INTO rule_mapping "
                "(code, article_location, article_full_text, article_source, source_version) "
                "VALUES (?, ?, ?, ?, ?)",
                (code, None, None, None, source_version),
            )
    conn.commit()
    conn.close()


def test_incremental_skips_codes_with_same_version(tmp_path):
    """版本相同時，既有 mapping 應被跳過（不重算、零 LLM 呼叫）。"""
    db_path = str(tmp_path / "rules.sqlite3")
    trees_path = str(tmp_path / "docx_trees.json")
    _make_db(
        db_path,
        [("06012C", "尿一般檢查", None)],
        source_version="v1",
    )
    with open(trees_path, "w", encoding="utf-8") as f:
        json.dump({}, f)

    with patch.object(build_mapping.llm_client, "smoke_test", return_value="1"), \
         patch.object(build_mapping.llm_client, "chat_completion") as mock_chat:
        result = build_mapping.build_rule_mapping(
            db_path, trees_path, source_version="v1", incremental=True
        )

    assert result["processed_count"] == 0
    assert result["skipped_count"] == 1
    assert mock_chat.call_count == 0

    conn = db.get_connection(db_path)
    row = conn.execute(
        "SELECT article_location, article_source, source_version FROM rule_mapping WHERE code=?",
        ("06012C",),
    ).fetchone()
    conn.close()
    assert row["article_location"] is None
    assert row["source_version"] == "v1"


def test_incremental_rebuilds_when_version_changed(tmp_path):
    """版本變更時，舊 mapping 應被重算（即使既有列存在）。"""
    db_path = str(tmp_path / "rules.sqlite3")
    trees_path = str(tmp_path / "docx_trees.json")
    _make_db(
        db_path,
        [("06012C", "尿一般檢查", None)],
        source_version="old-version",
    )
    with open(trees_path, "w", encoding="utf-8") as f:
        json.dump({}, f)

    with patch.object(build_mapping.llm_client, "smoke_test", return_value="1"), \
         patch.object(
             build_mapping.llm_client,
             "chat_completion",
             return_value="條文位置：測試路徑\n條文摘要：本條文規範尿液一般檢查之審查原則與給付規定，適用於門診及住院申報案件。",
         ):
        result = build_mapping.build_rule_mapping(
            db_path, trees_path, source_version="new-version", incremental=True
        )

    assert result["processed_count"] == 1
    assert result["skipped_count"] == 0

    conn = db.get_connection(db_path)
    row = conn.execute(
        "SELECT article_location, article_source, source_version FROM rule_mapping WHERE code=?",
        ("06012C",),
    ).fetchone()
    conn.close()
    assert row["article_location"] == "測試路徑"
    assert row["article_source"] == "docx"
    assert row["source_version"] == "new-version"


def test_non_incremental_writes_source_version(tmp_path):
    """全量模式（incremental=False）仍應寫入 source_version。"""
    db_path = str(tmp_path / "rules.sqlite3")
    trees_path = str(tmp_path / "docx_trees.json")
    _make_db(db_path, [("06012C", "尿一般檢查", None)])
    with open(trees_path, "w", encoding="utf-8") as f:
        json.dump({}, f)

    with patch.object(build_mapping.llm_client, "smoke_test", return_value="1"), \
         patch.object(
             build_mapping.llm_client,
             "chat_completion",
             return_value="條文位置：測試路徑\n條文摘要：本條文規範尿液一般檢查之審查原則與給付規定，適用於門診及住院申報案件。",
         ):
        result = build_mapping.build_rule_mapping(
            db_path, trees_path, source_version="v9", incremental=False
        )

    assert result["processed_count"] == 1
    conn = db.get_connection(db_path)
    row = conn.execute(
        "SELECT source_version FROM rule_mapping WHERE code=?", ("06012C",)
    ).fetchone()
    conn.close()
    assert row["source_version"] == "v9"


def test_incremental_degraded_run_does_not_lock_no_match(tmp_path):
    """server 故障時的降級結果不應鎖死：source_version=None，下次同版本會重試。

    這是 P1-4 的關鍵語意 —— 若降級也寫版本，server 起來後增量模式會
    因為版本相同而跳過，把「故障」永久誤判成「查無」。
    """
    db_path = str(tmp_path / "rules.sqlite3")
    trees_path = str(tmp_path / "docx_trees.json")
    _make_db(db_path, [("06012C", "尿一般檢查", None)])
    with open(trees_path, "w", encoding="utf-8") as f:
        json.dump({}, f)

    # 第一次：server 掛掉（smoke 失敗）→ 降級寫入，source_version 必須為 None
    with patch.object(build_mapping.llm_client, "smoke_test", side_effect=RuntimeError("down")), \
         patch.object(build_mapping.llm_client, "chat_completion") as mock_chat:
        result = build_mapping.build_rule_mapping(
            db_path, trees_path, source_version="v1", incremental=True
        )
    assert result["processed_count"] == 1
    assert result["degraded_count"] == 1
    assert mock_chat.call_count == 0

    conn = db.get_connection(db_path)
    row = conn.execute(
        "SELECT source_version FROM rule_mapping WHERE code=?", ("06012C",)
    ).fetchone()
    conn.close()
    assert row["source_version"] is None

    # 第二次：server 恢復、同版本 v1 → 不應被 skip，應重新處理並配對成功
    with patch.object(build_mapping.llm_client, "smoke_test", return_value="1"), \
         patch.object(
             build_mapping.llm_client,
             "chat_completion",
             return_value="條文位置：測試路徑\n條文摘要：本條文規範尿液一般檢查之審查原則與給付規定，適用於門診及住院申報案件。",
         ):
        result = build_mapping.build_rule_mapping(
            db_path, trees_path, source_version="v1", incremental=True
        )
    assert result["processed_count"] == 1
    assert result["skipped_count"] == 0
    assert result["llm_matched_count"] == 1

    conn = db.get_connection(db_path)
    row = conn.execute(
        "SELECT article_location, article_source, source_version FROM rule_mapping WHERE code=?",
        ("06012C",),
    ).fetchone()
    conn.close()
    assert row["article_location"] == "測試路徑"
    assert row["source_version"] == "v1"


def test_per_code_llm_failure_not_locked_but_genuine_no_match_is(tmp_path):
    """單一碼 LLM 呼叫失敗 → source_version=None（待重試）；
    真正回「查無相關條文」→ source_version 鎖定（不重試）。"""
    db_path = str(tmp_path / "rules.sqlite3")
    trees_path = str(tmp_path / "docx_trees.json")
    _make_db(
        db_path,
        [
            ("06012C", "尿一般檢查", None),
            ("06013C", "尿液特殊檢查", None),
        ],
    )
    with open(trees_path, "w", encoding="utf-8") as f:
        json.dump({}, f)

    def _fake_chat(system_prompt, user_prompt):
        if "06013C" in user_prompt:
            return "查無相關條文"
        raise RuntimeError("timeout")

    with patch.object(build_mapping.llm_client, "smoke_test", return_value="1"), \
         patch.object(build_mapping.llm_client, "chat_completion", side_effect=_fake_chat):
        result = build_mapping.build_rule_mapping(
            db_path, trees_path, source_version="v2", incremental=False
        )

    assert result["no_match_count"] == 2
    assert result["degraded_count"] == 1

    conn = db.get_connection(db_path)
    row = conn.execute(
        "SELECT source_version FROM rule_mapping WHERE code=?", ("06012C",)
    ).fetchone()
    assert row["source_version"] is None  # 故障 → 待重試
    row = conn.execute(
        "SELECT source_version FROM rule_mapping WHERE code=?", ("06013C",)
    ).fetchone()
    assert row["source_version"] == "v2"  # 真正查無 → 鎖定
    conn.close()


def test_select_top_candidates_filters_title_only_nodes():
    """候選節點必須有實質全文：標題-only 節點（full_text 等於標題）應被過濾。"""
    nodes = [
        {"title": "婦產科", "full_text": "婦產科", "children": []},  # 標題-only，應排除
        {"title": "短", "full_text": "x", "children": []},            # 太短，應排除
        {
            "title": "第一節 尿液檢查",
            "full_text": "尿液檢查項目編號06001至06017，包含一般尿液檢查、尿液沉渣檢查…",
            "children": [],
        },  # 實質內容，應保留
    ]
    picked = build_mapping._select_top_candidates(nodes, "尿蛋白")
    assert len(picked) == 1
    assert picked[0]["title"] == "第一節 尿液檢查"


def test_low_value_article_heading_only_is_degraded(tmp_path):
    """LLM 回報「全文等於標題」的低價值條文：不寫成 docx 匹配，應降級為無匹配。"""
    db_path = str(tmp_path / "rules.sqlite3")
    trees_path = str(tmp_path / "docx_trees.json")
    _make_db(db_path, [("06012C", "尿一般檢查", None)])
    with open(trees_path, "w", encoding="utf-8") as f:
        json.dump({}, f)

    # LLM 回傳「條文位置只有一層、全文就是標題」
    with patch.object(build_mapping.llm_client, "smoke_test", return_value="1"), \
         patch.object(
             build_mapping.llm_client,
             "chat_completion",
             return_value="條文位置：婦產科\n條文摘要：婦產科",
         ):
        result = build_mapping.build_rule_mapping(
            db_path, trees_path, source_version="v3", incremental=False
        )

    conn = db.get_connection(db_path)
    row = conn.execute(
        "SELECT article_source, article_location, article_full_text, source_version "
        "FROM rule_mapping WHERE code=?", ("06012C",)
    ).fetchone()
    conn.close()

    assert row["article_source"] is None
    assert row["article_location"] is None
    assert row["article_full_text"] is None
    # 鎖定版本：下次同版本不重試（這是「查無」而非故障）
    assert row["source_version"] == "v3"
    assert result["llm_matched_count"] == 0
    assert result["no_match_count"] == 1
