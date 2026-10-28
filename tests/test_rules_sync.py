"""每月規則同步：來源檔選取、藥品欄位解析（支付價／AI 摘要／占位字串）、upsert 與整表取代、
get_rule 回傳欄位，以及官方支付價在醫令判定中的使用。

所有 CSV 皆為測試內合成資料（代碼以 TST 開頭），不讀取、不寫入正式規則庫。
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from elc_audit_engine.monthly_audit import evaluate_order
from elc_audit_engine.parsers.models import OrderRecord
from elc_audit_engine.rule_repository import get_rule
from elc_audit_engine.rule_repository.db import (
    SCHEMA_DRUG,
    SCHEMA_PAYMENT,
    SCHEMA_RULE_MAPPING,
)
from elc_audit_engine.rule_repository.loaders._csv_table import RuleCsvFormatError
from elc_audit_engine.rule_repository.loaders.drug_loader import load_drug_csv_full
from elc_audit_engine.rule_repository.loaders.payment_loader import load_payment_csv
from elc_audit_engine.rule_repository.models import RuleResult, not_found
from elc_audit_engine.rule_repository.scripts.sync_latest_rules import (
    pick_latest,
    rule_csv_kind,
    sync_latest_rules,
    validate_rule_csv_header,
)

DRUG_HEADER = "藥品代號,藥品中文名稱,給付規定,有效起日,有效迄日,支付價,AI-note"
PAYMENT_HEADER = "診療項目代碼,中文項目名稱,支付規定,生效起日,生效迄日"


def _write_csv(path, lines: list[str]) -> str:
    # 與官方檔相同：UTF-8 含 BOM
    path.write_bytes(("﻿" + "\n".join(lines) + "\n").encode("utf-8"))
    return str(path)


@pytest.fixture
def drug_csv(tmp_path) -> str:
    return _write_csv(tmp_path / "藥品項查詢項目檔251016 AI  摘要.csv", [
        DRUG_HEADER,
        # 正常：有支付價、有給付規定、民國七碼日期、代碼含小寫（應正規化）
        'tst001,"測試藥A 25毫克",限治療精神分裂症使用。,1091201,9991231,3.57,"**AI 摘要A**"',
        # 占位：給付規定為「未找到給付規定」→ NULL，且不得以 AI 摘要取代
        'TST002,測試藥B,未找到給付規定,1091201,9991231,5.00,"**AI 摘要B（非官方）**"',
        # 支付價非數字（欄位錯位）→ NULL
        "TST003,測試藥C,,1091201,9991231,單方,",
        # 無 AI 摘要
        "TST004,測試藥D,每日最多2次,1091201,9991231,0.32,",
    ])


# ── 來源檔選取與格式判定 ─────────────────────────────────────────────


def test_pick_latest_chooses_newest_version_tag(tmp_path):
    _write_csv(tmp_path / "藥品項查詢項目檔251016 AI  摘要.csv", [DRUG_HEADER])
    _write_csv(tmp_path / "藥品項查詢項目檔260301 AI  摘要.csv", [DRUG_HEADER])
    chosen = pick_latest(str(tmp_path), "藥品項查詢項目檔*.csv")
    assert chosen.endswith("260301 AI  摘要.csv")


def test_pick_latest_raises_when_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        pick_latest(str(tmp_path), "藥品項查詢項目檔*.csv")


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("藥品項查詢項目檔251016 AI  摘要.csv", "drug"),
        ("醫療服務給付項目_醫療服務給付項目及支付標準260801_C類已填支付規定.csv", "payment"),
        ("../藥品項查詢項目檔.csv", None),  # 路徑成分
        ("notes.csv", None),
        (".藥品項查詢項目檔.csv", None),  # 隱藏檔
        ("藥品項查詢項目檔.ods", None),
    ],
)
def test_rule_csv_kind_accepts_only_known_sources(filename, expected):
    assert rule_csv_kind(filename) == expected


def test_header_validation_rejects_missing_columns(tmp_path):
    path = _write_csv(tmp_path / "藥品項查詢項目檔1.csv", ["藥品代號,藥品中文名稱"])
    with pytest.raises(RuleCsvFormatError, match="缺少必要欄位"):
        validate_rule_csv_header(path, "drug")


# ── 藥品欄位解析 ──────────────────────────────────────────────────


def test_drug_loader_maps_price_official_text_and_ai_note(tmp_path, drug_csv):
    db = str(tmp_path / "rules.sqlite3")
    count = load_drug_csv_full(db, drug_csv)
    assert count == 4

    conn = sqlite3.connect(db)
    rows = {r[0]: r for r in conn.execute("SELECT code, name, payment_text, effective_from, unit_price, ai_note FROM drug_rules")}
    conn.close()

    # 代碼正規化為大寫；官方文字原樣；民國日期轉西元
    # 民國 109 年 12 月 1 日 = 2020-12-01（七碼 RRRMMDD）
    assert rows["TST001"][1:] == ("測試藥A 25毫克", "限治療精神分裂症使用。", "2020-12-01", "3.57", "**AI 摘要A**")
    # 占位字串 → payment_text NULL；AI 摘要獨立保存，不進 payment_text
    assert rows["TST002"][2] is None
    assert rows["TST002"][5] == "**AI 摘要B（非官方）**"
    # 非數字支付價 → NULL
    assert rows["TST003"][4] is None
    # 無 AI 摘要 → NULL
    assert rows["TST004"][5] is None


def test_get_rule_returns_name_price_and_labelled_ai_note(tmp_path, drug_csv):
    db = str(tmp_path / "rules.sqlite3")
    load_drug_csv_full(db, drug_csv)

    rule = get_rule("tst002", db_path=db)
    assert rule.found and rule.source == "drug"
    assert rule.name == "測試藥B"
    assert rule.payment_text is None  # 不以 AI 摘要替代官方規定
    assert rule.unit_price == "5.00"
    assert rule.ai_note == "**AI 摘要B（非官方）**"


def test_get_rule_on_old_database_without_new_columns_still_works(tmp_path):
    """舊版 drug_rules（無 unit_price／ai_note）：查詢不得失敗，新欄位為 None。"""
    db = str(tmp_path / "old.sqlite3")
    conn = sqlite3.connect(db)
    conn.execute(SCHEMA_PAYMENT)  # get_rule 會先查 payment_rules，再查 rule_mapping
    conn.execute(SCHEMA_RULE_MAPPING)
    conn.execute(SCHEMA_DRUG)
    conn.execute("INSERT INTO drug_rules VALUES ('OLD1','舊藥','限使用。','2023-01-01','2910-12-31')")
    conn.commit()
    conn.close()
    rule = get_rule("OLD1", db_path=db)
    assert rule.found and rule.unit_price is None and rule.ai_note is None


# ── upsert 與整表取代 ─────────────────────────────────────────────


def _seed_db(path: str) -> None:
    conn = sqlite3.connect(path)
    for ddl in (SCHEMA_PAYMENT, SCHEMA_DRUG, SCHEMA_RULE_MAPPING):
        conn.execute(ddl)
    conn.execute("INSERT INTO payment_rules VALUES ('KEEP1','保留項目','舊規定','2020-01-01','2910-12-31')")
    conn.execute("INSERT INTO payment_rules VALUES ('STALE1','不在新檔的項目','舊規定','2020-01-01','2910-12-31')")
    conn.execute("INSERT INTO drug_rules VALUES ('DSTALE','不在新檔的藥','舊','2020-01-01','2910-12-31')")
    conn.commit()
    conn.close()


def _payment_csv(tmp_path) -> str:
    return _write_csv(tmp_path / "醫療服務給付項目_測試260801.csv", [
        PAYMENT_HEADER,
        "KEEP1,保留項目,新規定,20200101,29101231",
        "NEW1,新增項目,新規定,20240101,29101231",
    ])


def test_upsert_keeps_codes_missing_from_source_and_reports_them(tmp_path, drug_csv):
    db = str(tmp_path / "rules.sqlite3")
    _seed_db(db)
    payment_csv = _payment_csv(tmp_path)

    # 直接驗證 loader 的 upsert 行為（sync 的目錄選檔另由 sync 測試覆蓋）
    load_payment_csv(db, payment_csv, replace=False)
    load_drug_csv_full(db, drug_csv, replace=False)

    conn = sqlite3.connect(db)
    payment = {r[0]: r[2] for r in conn.execute("SELECT code, name, payment_text FROM payment_rules")}
    drug_codes = {r[0] for r in conn.execute("SELECT code FROM drug_rules")}
    conn.close()
    assert payment["STALE1"] == "舊規定"  # 不在來源的代碼保留，不被刪除
    assert payment["KEEP1"] == "新規定"  # 來源有的代碼被覆寫
    assert "NEW1" in payment
    assert "DSTALE" in drug_codes and "TST001" in drug_codes


def test_replace_mode_deletes_codes_missing_from_source(tmp_path):
    db = str(tmp_path / "rules.sqlite3")
    _seed_db(db)
    load_payment_csv(db, _payment_csv(tmp_path), replace=True)
    conn = sqlite3.connect(db)
    codes = {r[0] for r in conn.execute("SELECT code FROM payment_rules")}
    conn.close()
    assert codes == {"KEEP1", "NEW1"}


def test_sync_reports_stale_counts_in_upsert_mode(tmp_path, drug_csv):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "藥品項查詢項目檔251016 AI  摘要.csv").write_bytes(Path(drug_csv).read_bytes())
    _write_csv(rules_dir / "醫療服務給付項目_測試260801.csv", [
        PAYMENT_HEADER, "KEEP1,保留項目,新規定,20200101,29101231",
    ])
    db = str(tmp_path / "rules.sqlite3")
    _seed_db(db)

    result = sync_latest_rules(db_path=db, rules_dir=str(rules_dir))
    assert result.drug_rows == 4
    assert result.payment_rows == 1
    assert result.payment_stale == 1  # STALE1 仍在 DB 但不在來源
    assert result.drug_stale == 1  # DSTALE
    assert result.to_dict()["mode"] == "upsert"


def test_sync_replace_mode_is_explicit(tmp_path, drug_csv):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "藥品項查詢項目檔251016 AI  摘要.csv").write_bytes(Path(drug_csv).read_bytes())
    _write_csv(rules_dir / "醫療服務給付項目_測試260801.csv", [PAYMENT_HEADER, "KEEP1,保留,新,20200101,29101231"])
    db = str(tmp_path / "rules.sqlite3")
    _seed_db(db)
    result = sync_latest_rules(db_path=db, rules_dir=str(rules_dir), replace=True)
    assert result.to_dict()["mode"] == "replace"
    conn = sqlite3.connect(db)
    assert {r[0] for r in conn.execute("SELECT code FROM payment_rules")} == {"KEEP1"}
    conn.close()


def test_sync_without_sources_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        sync_latest_rules(db_path=str(tmp_path / "r.sqlite3"), rules_dir=str(tmp_path))


def test_sync_rejects_bad_drug_header_without_touching_db(tmp_path):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    _write_csv(rules_dir / "藥品項查詢項目檔251016 AI  摘要.csv", ["藥品代號"])
    _write_csv(rules_dir / "醫療服務給付項目_測試260801.csv", [PAYMENT_HEADER])
    db = str(tmp_path / "rules.sqlite3")
    _seed_db(db)
    with pytest.raises(RuleCsvFormatError):
        sync_latest_rules(db_path=db, rules_dir=str(rules_dir))
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM drug_rules").fetchone()[0] == 1  # 未被改動
    conn.close()


# ── 官方支付價在醫令判定中的使用 ──────────────────────────────────


def _rule(code: str, *, price: str | None, text: str | None) -> RuleResult:
    return RuleResult(
        code=code, source="drug", name=f"藥{code}", payment_text=text,
        effective_from="2023-01-01", effective_to="2910-12-31", article_location=None,
        article_full_text=None, article_source=None, found=True, unit_price=price,
    )


def _drug_line(code: str, *, unit: str = "0.00", points: str = "0") -> OrderRecord:
    return OrderRecord(code=code, category="4", unit_price=unit, points=points, seq="1", raw={})


def _judge(order: OrderRecord, rule: RuleResult):
    return evaluate_order(
        order, case_diagnoses=("S1",), visit_date=date(2023, 7, 18), lookup=lambda c: rule,
    )


def test_official_price_above_five_flags_unpriced_drug_with_text():
    finding = _judge(_drug_line("TSTA"), _rule("TSTA", price="6.50", text="限使用。"))
    assert finding is not None
    assert finding.flags == ("drug_over_5",)
    assert finding.price_source == "official"
    assert finding.official_unit_price == "6.50"


def test_official_price_above_five_flags_even_without_payment_text():
    """回歸：無給付文字的藥品也必須帶出官方價與來源（先前在 NO_TEXT 分支遺漏）。"""
    finding = _judge(_drug_line("TSTB"), _rule("TSTB", price="16.4", text=None))
    assert finding is not None
    assert finding.rule_status == "no_text"
    assert finding.flags == ("drug_over_5",)
    assert finding.price_source == "official"
    assert finding.official_unit_price == "16.4"


def test_official_price_at_or_below_five_is_not_high_risk():
    assert _judge(_drug_line("TSTC"), _rule("TSTC", price="5.00", text="限使用。")) is None
    assert _judge(_drug_line("TSTD"), _rule("TSTD", price="0.32", text="限使用。")) is None


def test_unpriced_drug_without_official_price_stays_unpriced():
    finding = _judge(_drug_line("TSTE"), _rule("TSTE", price=None, text="限使用。"))
    assert finding.flags == ("drug_unpriced",)
    assert finding.price_source == "totfa"


def test_invalid_official_price_is_ignored():
    finding = _judge(_drug_line("TSTF"), _rule("TSTF", price="單方", text="限使用。"))
    assert finding.flags == ("drug_unpriced",)
    assert finding.price_source == "totfa"


def test_points_flag_survives_official_price_resolution():
    """回歸：藥品同時點數 >350 與單價缺漏，官方價 ≤5 時只移除單價旗標，點數旗標保留。"""
    order = _drug_line("TSTG", points="400")
    finding = _judge(order, _rule("TSTG", price="1.00", text="限使用。"))
    assert finding is not None
    assert finding.flags == ("points_over_350",)


def test_not_found_drug_keeps_unpriced_flag():
    order = _drug_line("TSTH")
    finding = evaluate_order(order, case_diagnoses=(), visit_date=None, lookup=lambda c: not_found(c))
    assert finding.rule_status == "not_found"
    assert finding.flags == ("drug_unpriced",)
