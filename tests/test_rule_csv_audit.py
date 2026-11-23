"""規則庫 CSV 只讀品質稽核與 _csv_table NULL 契約統一測試（Phase 35 Wave 1）。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from elc_audit_engine.rule_repository import get_rule
from elc_audit_engine.rule_repository.audit_csv import audit_rule_csv, format_audit_markdown, main as audit_cli_main
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
