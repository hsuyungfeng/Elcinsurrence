"""規則庫 CSV 只讀品質稽核與 _csv_table NULL 契約統一測試（Phase 35 Wave 1）。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from elc_audit_engine.rule_repository import get_rule
from elc_audit_engine.rule_repository.audit_csv import (
    analyze_stale_payment_codes,
    audit_rule_csv,
    classify_payment_code_category,
    format_audit_markdown,
    format_stale_markdown,
    main as audit_cli_main,
)
from elc_audit_engine.rule_repository.db import SCHEMA_PAYMENT
from elc_audit_engine.rule_repository.loaders.drug_loader import load_drug_csv
from elc_audit_engine.rule_repository.loaders.payment_loader import load_payment_csv


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_audit_rule_csv_detects_all_anomaly_categories_and_is_readonly(tmp_path):
    """確認唯讀稽核精準檢出占位字串、非標準尾碼、缺碼引用、AI 預填與結構異常，且不改動原檔。"""
    csv_file = tmp_path / "payment_sample.csv"
    csv_file.write_text(
        "\ufeff診療項目代碼,健保支付點數,生效起日,生效迄日,英文項目名稱,中文項目名稱,支付規定\n"
        "62010C,1623,20231001,29101231,Excision,腫瘤摘除,審查原則：(2025-01-01) 版 1.0 **申報條件** 參考 92043D 與 99999C\n"
        "00304C,200,20160401,29101231,Ref,轉診,null\n"
        "00305C,200,20250101,20240101,BadDate,日期倒置,正常官方給付條文\n"
        "00305C,200,20250101,29101231,Dup,重複碼異文,不同條文內容\n"
        ",100,20200101,29101231,Empty,缺碼列,\n",
        encoding="utf-8",
    )
    before_hash = _sha256(csv_file)

    report = audit_rule_csv(csv_file)
    assert _sha256(csv_file) == before_hash  # 嚴格唯讀

    assert report["kind"] == "payment"
    assert report["total_rows"] == 5
    c = report["counts"]
    assert c["literal_placeholder"] == 1
    assert c["ai_prefill_marker"] == 1
    assert c["missing_code_ref"] == 1
    assert c["non_standard_suffix_ref"] == 1
    assert c["invalid_date_range"] == 1
    assert c["duplicate_code_diff_text"] == 1
    assert c["empty_code"] == 1
    assert report["anomalies"]["non_standard_suffix_ref"][0]["non_standard_refs"] == ["92043D"]

    md = format_audit_markdown([report])
    assert "92043D" in md
    assert "payment_sample.csv" in md


def test_audit_cli_outputs_json_and_md(tmp_path):
    """CLI --csv 搭配 --json-out 與 --md-out 輸出合法報告並回傳 0。"""
    csv_file = tmp_path / "drug_sample.csv"
    csv_file.write_text(
        "\ufeff藥品代號,藥品中文名稱,給付規定,有效起日,有效迄日\n"
        "AC00001100,測試藥品A,未找到給付規定,1120101,1991231\n"
        "AC00002100,測試藥品B,限特定適應症使用,1120101,1991231\n",
        encoding="utf-8",
    )
    json_out = tmp_path / "audit.json"
    md_out = tmp_path / "audit.md"

    rc = audit_cli_main(["--csv", str(csv_file), "--json-out", str(json_out), "--md-out", str(md_out)])
    assert rc == 0
    parsed = json.loads(json_out.read_text(encoding="utf-8"))
    assert len(parsed) == 1
    assert parsed[0]["kind"] == "drug"
    assert parsed[0]["counts"]["literal_placeholder"] == 1
    assert parsed[0]["counts"]["has_text"] == 1
    assert "drug_sample.csv" in md_out.read_text(encoding="utf-8")


def test_loaders_normalize_placeholder_text_to_sql_null(tmp_path):
    """_csv_table 載入 payment 與 drug CSV 時將字面 null/None/未找到給付規定/空白統一存為 SQLite NULL。"""
    db_path = str(tmp_path / "rules.sqlite3")
    pay_csv = tmp_path / "pay.csv"
    pay_csv.write_text(
        "\ufeff診療項目代碼,中文項目名稱,支付規定,生效起日,生效迄日\n"
        "P0001C,字面空值,null,20230101,29101231\n"
        "P0002C,大寫空值, NONE ,20230101,29101231\n"
        "P0003C,占位中文,未找到給付規定,20230101,29101231\n"
        "P0004C,正常規定,限特定條件申報,20230101,29101231\n",
        encoding="utf-8",
    )
    drug_csv = tmp_path / "drug.csv"
    drug_csv.write_text(
        "\ufeff藥品代號,藥品中文名稱,給付規定,有效起日,有效迄日\n"
        "D0001,藥品空值,null,1120101,1991231\n"
        "D0002,藥品正常,限糖尿病患者使用,1120101,1991231\n",
        encoding="utf-8",
    )

    assert load_payment_csv(db_path, str(pay_csv)) == 4
    assert load_drug_csv(db_path, str(drug_csv)) == 2

    assert get_rule("P0001C", db_path=db_path).payment_text is None
    assert get_rule("P0002C", db_path=db_path).payment_text is None
    assert get_rule("P0003C", db_path=db_path).payment_text is None
    assert get_rule("P0004C", db_path=db_path).payment_text == "限特定條件申報"
    assert get_rule("D0001", db_path=db_path).payment_text is None
    assert get_rule("D0002", db_path=db_path).payment_text == "限糖尿病患者使用"


def test_runtime_paths_are_isolated_from_production_data():
    """確認測試期全域隔離生效：CASES_DB_PATH 與 AUDIT_LOG_PATH 絕不指向正式 data/ 目錄。"""
    from config import settings
    from elc_audit_engine import audit_log
    from elc_audit_engine.case_store import store as case_store_mod

    prod_data = Path(settings.PROJECT_ROOT).resolve() / "data"
    for p in (settings.CASES_DB_PATH, case_store_mod.CASES_DB_PATH, settings.AUDIT_LOG_PATH, audit_log.AUDIT_LOG_PATH):
        assert not Path(p).resolve().is_relative_to(prod_data)


def test_audit_csv_cjk_adjacent_code_ref_and_official_prefix_not_flagged(tmp_path):
    """Phase 36：中文緊鄰異常尾碼（如51002D／（92043D））須檢出，正常「審查原則：」開頭不誤判 AI 預填。"""
    csv_file = tmp_path / "pay_261119_like.csv"
    csv_file.write_text(
        "\ufeff診療項目代碼,健保支付點數,生效起日,生效迄日,英文項目名稱,中文項目名稱,支付規定\n"
        '51002C,500,20230101,29101231,Suture,縫合,"審查原則：\n1.申報條件：逾三根須報如51002D。"\n'
        '92043C,600,20230101,29101231,TMJ,脫臼,"審查原則：\n1.不得同時申報固定項目（92043D）。"\n'
        '62010C,1623,20230101,29101231,Tumor,腫瘤,"審查原則：\n1.一般正常官方給付條文無異常碼。"\n',
        encoding="utf-8",
    )
    rep = audit_rule_csv(csv_file)
    c = rep["counts"]
    assert c["ai_prefill_marker"] == 0
    assert c["non_standard_suffix_ref"] == 2
    assert c["missing_code_ref"] == 2
    found_refs = [item["non_standard_refs"] for item in rep["anomalies"]["non_standard_suffix_ref"]]
    assert ["51002D"] in found_refs
    assert ["92043D"] in found_refs


def test_classify_payment_code_category_all_8_categories():
    """Phase 37：驗證 8 類互斥分類與大小寫／空白正規化（含 ASCII 純數字與非純數字特項碼）。"""
    assert classify_payment_code_category(" 08037c ") == "C類一般診療項目"
    assert classify_payment_code_category("05204D") == "D類（門診藥事服務費／助產）"
    assert classify_payment_code_category("00101E") == "E類"
    assert classify_payment_code_category("pt101") == "復健／職能／語言治療計畫碼（PT/OT/ST）"
    assert classify_payment_code_category("OT202") == "復健／職能／語言治療計畫碼（PT/OT/ST）"
    assert classify_payment_code_category("ST303") == "復健／職能／語言治療計畫碼（PT/OT/ST）"
    assert classify_payment_code_category("P1407A") == "P專案計畫碼（慢性病／家醫／牙醫／安寧等）"
    assert classify_payment_code_category("PA001") == "P專案計畫碼（慢性病／家醫／牙醫／安寧等）"
    assert classify_payment_code_category("N001") == "N類專案／護理／長照碼"
    assert classify_payment_code_category("01") == "預防保健／篩檢純數字碼（兒童衛教／癌症篩檢等）"
    # 非純數字（含全形數字或尾碼 P）不得誤判為純數字預防保健碼
    assert classify_payment_code_category("48027P") == "其他特項碼（K/F/G/H/Q/CH等非純數字碼）"
    assert classify_payment_code_category("１２３") == "其他特項碼（K/F/G/H/Q/CH等非純數字碼）"


def test_analyze_stale_payment_codes_upsert_no_stale_and_readonly(tmp_path):
    """Phase 37：stale_count > 0 一律推薦 upsert（即使僅含其他特項碼），stale_count == 0 回 no_stale，且嚴格唯讀。"""
    db_path = tmp_path / "rules.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute(SCHEMA_PAYMENT)
    conn.executemany(
        "INSERT INTO payment_rules (code, name, payment_text, effective_from, effective_to) VALUES (?, ?, ?, ?, ?)",
        [
            ("00101C", "保留項目", "正常條文", "2020-01-01", "2910-12-31"),
            ("48027p", "專案特項", "審查原則：(2025-01-01) **AI預填**", "2020-01-01", "2910-12-31"),
            ("05204D", "藥事服務", None, "2020-01-01", "2910-12-31"),
            ("N100", "長照碼", "既有一般文字", "2020-01-01", "2910-12-31"),
        ],
    )
    conn.commit()
    conn.close()

    before_sha = _sha256(db_path)
    csv_partial = tmp_path / "pay_partial.csv"
    csv_partial.write_text(
        "\ufeff診療項目代碼,中文項目名稱,支付規定,生效起日,生效迄日\n"
        " 00101c ,保留項目,新條文,20200101,29101231\n",
        encoding="utf-8",
    )

    rep = analyze_stale_payment_codes(db_path, csv_partial)
    assert _sha256(db_path) == before_sha
    assert rep["stale_count"] == 3
    assert rep["recommended_mode"] == "upsert"
    assert rep["ai_prefill_count"] == 1
    assert rep["null_text_count"] == 1
    assert rep["other_text_count"] == 1
    assert sum(rep["by_category"].values()) == 3
    md = format_stale_markdown(rep)
    assert "48027P" in md and "upsert" in md

    # 僅餘 1 筆「其他特項碼」仍須維持 recommended_mode == "upsert"（絕不建議自動刪除）
    csv_only_other_stale = tmp_path / "pay_other_stale.csv"
    csv_only_other_stale.write_text(
        "\ufeff診療項目代碼,中文項目名稱,支付規定,生效起日,生效迄日\n"
        "00101C,保留,條文,20200101,29101231\n"
        "05204D,藥事,條文,20200101,29101231\n"
        "N100,長照,條文,20200101,29101231\n",
        encoding="utf-8",
    )
    rep_other = analyze_stale_payment_codes(db_path, csv_only_other_stale)
    assert rep_other["stale_count"] == 1
    assert rep_other["recommended_mode"] == "upsert"

    # CSV 涵蓋 DB 全數代碼 → stale_count == 0, recommended_mode == "no_stale"
    csv_all = tmp_path / "pay_all.csv"
    csv_all.write_text(
        "\ufeff診療項目代碼,中文項目名稱,支付規定,生效起日,生效迄日\n"
        "00101C,保留,條文,20200101,29101231\n"
        "48027P,專案,條文,20200101,29101231\n"
        "05204D,藥事,條文,20200101,29101231\n"
        "N100,長照,條文,20200101,29101231\n",
        encoding="utf-8",
    )
    rep_none = analyze_stale_payment_codes(db_path, csv_all)
    assert rep_none["stale_count"] == 0
    assert rep_none["recommended_mode"] == "no_stale"
    assert _sha256(db_path) == before_sha


def test_analyze_stale_payment_codes_error_boundaries_and_cli(tmp_path, capsys):
    """Phase 37：驗證缺檔、損毀 DB、缺 payment_rules 表、誤傳藥品 CSV 與 CLI 參數錯誤邊界。"""
    pay_csv = tmp_path / "pay.csv"
    pay_csv.write_text("\ufeff診療項目代碼,中文項目名稱,支付規定,生效起日,生效迄日\n00101C,項,文,20200101,29101231\n", encoding="utf-8")

    # 1. DB 或 CSV 不存在 -> FileNotFoundError
    with pytest.raises(FileNotFoundError):
        analyze_stale_payment_codes(tmp_path / "missing.sqlite3", pay_csv)

    # 2. 損毀非 SQLite 檔 -> ValueError（不可拋裸 sqlite3.DatabaseError）
    corrupt_db = tmp_path / "corrupt.sqlite3"
    corrupt_db.write_bytes(b"not a valid sqlite database bytes")
    with pytest.raises(ValueError, match="損毀或非有效 SQLite"):
        analyze_stale_payment_codes(corrupt_db, pay_csv)

    # 3. 合法 SQLite 但缺 payment_rules 表 -> ValueError
    empty_db = tmp_path / "empty.sqlite3"
    sqlite3.connect(empty_db).close()
    with pytest.raises(ValueError, match="payment_rules"):
        analyze_stale_payment_codes(empty_db, pay_csv)

    # 4. 傳入藥品 CSV（缺「診療項目代碼」）-> ValueError
    valid_db = tmp_path / "valid.sqlite3"
    conn = sqlite3.connect(valid_db)
    conn.execute(SCHEMA_PAYMENT)
    conn.execute("INSERT INTO payment_rules VALUES ('00101C','項','文','2020-01-01','2910-12-31')")
    conn.commit()
    conn.close()

    drug_csv = tmp_path / "drug.csv"
    drug_csv.write_text("\ufeff藥品代號,藥品中文名稱,給付規定,有效起日,有效迄日\nD1,藥,文,1120101,1991231\n", encoding="utf-8")
    with pytest.raises(ValueError, match="診療項目代碼"):
        analyze_stale_payment_codes(valid_db, drug_csv)

    # 5. CLI --stale-vs-db 缺 --csv 或給 2 份 --csv -> 退出碼 1
    assert audit_cli_main(["--stale-vs-db", str(valid_db)]) == 1
    assert audit_cli_main(["--stale-vs-db", str(valid_db), "--csv", str(pay_csv), "--csv", str(pay_csv)]) == 1
    assert audit_cli_main(["--stale-vs-db", str(corrupt_db), "--csv", str(pay_csv)]) == 1
    _ = capsys.readouterr()

    # 6. CLI 正常執行寫出 json 與 md -> 退出碼 0
    json_out = tmp_path / "stale.json"
    md_out = tmp_path / "stale.md"
    assert (
        audit_cli_main(
            [
                "--stale-vs-db",
                str(valid_db),
                "--csv",
                str(pay_csv),
                "--json-out",
                str(json_out),
                "--md-out",
                str(md_out),
            ]
        )
        == 0
    )
    assert json.loads(json_out.read_text(encoding="utf-8"))["recommended_mode"] == "no_stale"
    assert "no_stale" in md_out.read_text(encoding="utf-8")
