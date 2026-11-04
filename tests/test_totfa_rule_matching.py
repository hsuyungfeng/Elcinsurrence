"""Phase 15-02：當月申報高風險醫令的規則比對與批次彙總。

所有規則文字皆為測試內的合成字串（代碼以 TST/SYN 開頭），不是真實給付規定。
唯一讀取真實規則庫的測試為唯讀，且檔案不存在時跳過。
"""

from __future__ import annotations

import io
import os
import sqlite3
import zipfile
from datetime import date

import pytest

from elc_audit_engine.case_store.monthly import ingest_monthly_declaration
from elc_audit_engine.case_store.store import CaseStore
from elc_audit_engine.monthly_audit import (
    ARTIFACT_NAME,
    STATUS_NO_MARKERS,
    STATUS_NO_TEXT,
    STATUS_NOT_FOUND,
    STATUS_RESTRICTION,
    STATUS_UNDETERMINED,
    audit_batch,
    audit_case,
    diagnosis_matches,
    evaluate_order,
    extract_icd_codes,
    order_flags,
    roc7_to_date,
    split_sentences,
)
from elc_audit_engine.parsers.models import OrderRecord
from elc_audit_engine.rule_repository import get_rule
from elc_audit_engine.rule_repository.db import (
    SCHEMA_DRUG,
    SCHEMA_PAYMENT,
    SCHEMA_RULE_MAPPING,
)
from elc_audit_engine.rule_repository.errors import RuleRepositoryError
from elc_audit_engine.rule_repository.models import RuleResult, not_found

REAL_RULES = os.path.join(os.path.dirname(__file__), "..", "data", "db", "rules.sqlite3")

PAYMENT_RESTRICT_TEXT = "本項目限下列情形使用。ICD‑10 S00.1、S00.2 等診斷需附病歷。每次申報需檢附證明"
PAYMENT_PLAIN_TEXT = "一般說明文字。"


def _rule(
    code: str,
    *,
    payment_text: str | None = None,
    article: str | None = None,
    name: str = "測試項目",
    eff_from: str | None = "2023-01-01",
    eff_to: str | None = "2910-12-31",
) -> RuleResult:
    return RuleResult(
        code=code,
        source="payment",
        name=name,
        payment_text=payment_text,
        effective_from=eff_from,
        effective_to=eff_to,
        article_location=None,
        article_full_text=article,
        article_source="csv" if article else None,
        found=True,
    )


def _dict_lookup(table: dict[str, RuleResult]):
    def lookup(code: str) -> RuleResult:
        return table.get(code, not_found(code))

    return lookup


def _raising_lookup(code: str) -> RuleResult:
    raise RuleRepositoryError(f"rule repository query failed for code {code!r}: disk I/O error")


def _order(code: str, *, cat: str = "2", unit: str | None = "1", points: str | None = "1", seq: str = "1") -> OrderRecord:
    return OrderRecord(code=code, category=cat, unit_price=unit, points=points, seq=seq, raw={})


def _payload(orders: list[dict], *, primary: str = "S00123A", secondary: tuple[str, ...] = (), visit: str = "1120718") -> dict:
    return {
        "batch": "MONTHLY-202307",
        "case_seq": "7",
        "clinic": "03",
        "doctor_code": "D0001",
        "visit_date": visit,
        "primary_diagnosis": primary,
        "secondary_diagnoses": list(secondary),
        "orders": orders,
    }


def _po(code: str, *, cat: str = "2", unit: str = "1", points: str = "1", seq: str = "1") -> dict:
    return {"p1": "0", "p3": cat, "p4": code, "p10": "1.0", "p11": unit, "p12": points, "p13": seq}


# ── 純函式 ──────────────────────────────────────────────────────


def test_icd_codes_extracted_only_in_icd_context():
    text = "申報時需附 ICD‑10 B27、Z94、Z94.2 等診斷碼。另有維生素B12與A1C檢測。"
    assert extract_icd_codes(text) == ("B27", "Z94", "Z94.2")


def test_icd_extraction_ignores_non_icd_tokens_without_context():
    assert extract_icd_codes("HbA1c 與 B12 缺乏，需空腹檢測") == ()  # 句中無 ICD 語境字樣


def test_icd_extraction_keeps_dotless_extended_codes():
    assert extract_icd_codes("診斷碼 S90221A 適用") == ("S90221A",)


def test_split_sentences_yields_verbatim_substrings():
    text = PAYMENT_RESTRICT_TEXT + "。\n第二句；第三句"
    sentences = split_sentences(text)
    assert sentences
    for sentence in sentences:
        assert sentence in text


@pytest.mark.parametrize(
    ("case_codes", "rule_codes", "expected"),
    [
        (("Z942",), ("Z94",), True),  # 案件碼落在條文類別之下
        (("Z94",), ("Z94.2",), False),  # 案件碼較粗，不落在條文細碼之下
        (("S00.1",), ("S00.1",), True),
        (("I10",), ("S00.1", "S00.2"), False),
        (("K5700",), ("K57.0",), True),
    ],
)
def test_diagnosis_prefix_matching(case_codes, rule_codes, expected):
    assert diagnosis_matches(case_codes, rule_codes) is expected


def test_roc7_date_conversion():
    assert roc7_to_date("1120718") == date(2023, 7, 18)
    assert roc7_to_date("1121340") is None  # 月份/日期不合法
    assert roc7_to_date("20230718") is None  # 非民國七碼
    assert roc7_to_date(None) is None


def test_order_flags_thresholds_are_strict():
    assert order_flags(_order("X1", points="350")) == ()
    assert order_flags(_order("X1", points="350.01")) == ("points_over_350",)
    assert order_flags(_order("D1", cat="4", unit="0.00", points="0")) == ("drug_unpriced",)
    assert order_flags(_order("D1", cat="4", unit="5.00", points="0")) == ()  # 恰等於門檻不超過
    assert order_flags(_order("D1", cat="4", unit="5.01", points="0")) == ("drug_over_5",)
    assert order_flags(_order("D1", cat="4", unit="5", points="0")) == ()  # 恰等於門檻不超過
    assert order_flags(_order("P1", cat="2", unit="6.00", points="10")) == ()  # 非藥品不套單價門檻


# ── 單一醫令判定 ──────────────────────────────────────────────────


def test_restriction_evidence_is_verbatim_and_tagged():
    rule = _rule("TST1", payment_text=PAYMENT_RESTRICT_TEXT)
    finding = evaluate_order(
        _order("TST1", points="400"),
        case_diagnoses=("S00123A",),
        visit_date=date(2023, 7, 18),
        lookup=_dict_lookup({"TST1": rule}),
    )
    assert finding is not None
    assert finding.rule_status == STATUS_RESTRICTION
    assert finding.icd_in_rule == ("S00.1", "S00.2")
    assert finding.evidence
    for ev in finding.evidence:
        assert ev.sentence in PAYMENT_RESTRICT_TEXT  # 逐字
        assert ev.source == "payment_text"
    assert any("diagnosis" in ev.kinds for ev in finding.evidence)


def test_diagnosis_not_listed_is_a_fact_not_a_conclusion():
    rule = _rule("TST1", payment_text=PAYMENT_RESTRICT_TEXT)
    finding = evaluate_order(
        _order("TST1", points="400"),
        case_diagnoses=("I10",),
        visit_date=date(2023, 7, 18),
        lookup=_dict_lookup({"TST1": rule}),
    )
    assert finding.rule_status == STATUS_RESTRICTION
    assert finding.diagnosis_check == "not_listed"


def test_diagnosis_matched_when_case_code_under_listed_code():
    rule = _rule("TST1", payment_text=PAYMENT_RESTRICT_TEXT)
    finding = evaluate_order(
        _order("TST1", points="400"),
        case_diagnoses=("S001XA",),
        visit_date=date(2023, 7, 18),
        lookup=_dict_lookup({"TST1": rule}),
    )
    assert finding.diagnosis_check == "matched"


def test_rule_without_icd_text_reports_no_icd_not_matched():
    rule = _rule("TST2", payment_text="限治療糖尿病使用。需檢附病歷。")
    finding = evaluate_order(
        _order("TST2", points="400"),
        case_diagnoses=("E119",),
        visit_date=date(2023, 7, 18),
        lookup=_dict_lookup({"TST2": rule}),
    )
    assert finding.rule_status == STATUS_RESTRICTION
    assert finding.diagnosis_check == "no_icd_in_rule_text"


def test_text_without_restriction_markers_is_not_called_unrestricted():
    rule = _rule("TST3", payment_text=PAYMENT_PLAIN_TEXT)
    finding = evaluate_order(
        _order("TST3", points="400"),
        case_diagnoses=("S00123A",),
        visit_date=date(2023, 7, 18),
        lookup=_dict_lookup({"TST3": rule}),
    )
    assert finding.rule_status == STATUS_NO_MARKERS
    assert finding.evidence == ()


@pytest.mark.parametrize("payment_text", [None, "", "  ", "null"])
def test_missing_text_is_no_text_not_clean(payment_text):
    rule = _rule("TST4", payment_text=payment_text)
    finding = evaluate_order(
        _order("TST4", points="400"),
        case_diagnoses=("S00123A",),
        visit_date=date(2023, 7, 18),
        lookup=_dict_lookup({"TST4": rule}),
    )
    assert finding.rule_status == STATUS_NO_TEXT
    assert finding.diagnosis_check == "not_applicable"


def test_article_full_text_is_used_as_second_source():
    rule = _rule("TST5", payment_text=None, article="條文：限具適應症者使用。")
    finding = evaluate_order(
        _order("TST5", points="400"),
        case_diagnoses=("S00123A",),
        visit_date=date(2023, 7, 18),
        lookup=_dict_lookup({"TST5": rule}),
    )
    assert finding.rule_status == STATUS_RESTRICTION
    assert {ev.source for ev in finding.evidence} == {"article_full_text"}


def test_code_not_in_repository_is_not_found():
    finding = evaluate_order(
        _order("NOPE1", points="400"),
        case_diagnoses=("S00123A",),
        visit_date=date(2023, 7, 18),
        lookup=_dict_lookup({}),
    )
    assert finding.rule_status == STATUS_NOT_FOUND


def test_repository_failure_is_undetermined_never_not_found_or_clean():
    finding = evaluate_order(
        _order("TST6", points="400"),
        case_diagnoses=("S00123A",),
        visit_date=date(2023, 7, 18),
        lookup=_raising_lookup,
    )
    assert finding.rule_status == STATUS_UNDETERMINED
    assert finding.rule_status not in {STATUS_NOT_FOUND, STATUS_NO_MARKERS, STATUS_RESTRICTION}
    assert "disk I/O error" in finding.error


def test_out_of_period_is_flagged_against_effective_dates():
    rule = _rule("TST7", payment_text=PAYMENT_RESTRICT_TEXT, eff_from="2024-01-01")
    finding = evaluate_order(
        _order("TST7", points="400"),
        case_diagnoses=("S00123A",),
        visit_date=date(2023, 7, 18),
        lookup=_dict_lookup({"TST7": rule}),
    )
    assert finding.period_check == "out_of_period"
    assert finding.effective_from == "2024-01-01"


def test_unknown_visit_date_is_reported_not_guessed():
    rule = _rule("TST7", payment_text=PAYMENT_RESTRICT_TEXT)
    finding = evaluate_order(
        _order("TST7", points="400"),
        case_diagnoses=("S00123A",),
        visit_date=None,
        lookup=_dict_lookup({"TST7": rule}),
    )
    assert finding.period_check == "no_visit_date"


def test_non_flagged_orders_produce_no_finding():
    finding = evaluate_order(
        _order("TST8", points="350", unit="5.00"),
        case_diagnoses=(),
        visit_date=None,
        lookup=_dict_lookup({}),
    )
    assert finding is None


# ── 案件層 ──────────────────────────────────────────────────────


def test_audit_case_lists_only_flagged_orders_in_order():
    table = {"TST1": _rule("TST1", payment_text=PAYMENT_RESTRICT_TEXT)}
    payload = _payload(
        [
            _po("CHEAP", points="10", seq="1"),
            _po("TST1", points="400", seq="2"),
            _po("DRUG", cat="4", unit="6.00", points="0", seq="3"),
        ],
        secondary=("S00.2",),
    )
    audit = audit_case("MON-x", payload, lookup=_dict_lookup(table))
    assert [f.code for f in audit.findings] == ["TST1", "DRUG"]
    assert audit.doctor_code == "D0001"
    assert audit.department == "03"
    assert audit.case_seq == "7"


def test_audit_case_with_no_payload_is_empty_not_error():
    audit = audit_case("MON-y", None, lookup=_dict_lookup({}))
    assert audit.findings == ()


# ── 規則庫（合成 SQLite，經 get_rule 真實路徑） ──────────────────────


@pytest.fixture
def rules_db(tmp_path) -> str:
    path = str(tmp_path / "rules.sqlite3")
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA_PAYMENT)
    conn.execute(SCHEMA_DRUG)
    conn.execute(SCHEMA_RULE_MAPPING)
    conn.execute(
        "INSERT INTO payment_rules VALUES (?,?,?,?,?)",
        ("TST1", "測試項目", PAYMENT_RESTRICT_TEXT, "2023-01-01", "2910-12-31"),
    )
    conn.execute(
        "INSERT INTO payment_rules VALUES (?,?,?,?,?)",
        ("TSTNULL", "空規則", "null", "2023-01-01", "2910-12-31"),
    )
    conn.execute(
        "INSERT INTO drug_rules VALUES (?,?,?,?,?)",
        ("TSTDRUG", "測試藥", "限治療糖尿病使用。", "2023-01-01", "2910-12-31"),
    )
    conn.commit()
    conn.close()
    return path


def test_get_rule_wiring_with_synthetic_db(rules_db):
    payload = _payload(
        [_po("TST1", points="400", seq="1"), _po("TSTDRUG", cat="4", unit="0", points="0", seq="2"), _po("MISSING", points="400", seq="3")],
    )
    audit = audit_case(
        "MON-z",
        payload,
        lookup=lambda code: get_rule(code, db_path=rules_db),
    )
    status = {f.code: f.rule_status for f in audit.findings}
    assert status == {
        "TST1": STATUS_RESTRICTION,
        "TSTDRUG": STATUS_RESTRICTION,  # 藥品單價缺漏 → 旗標；規則文字含「限」
        "MISSING": STATUS_NOT_FOUND,
    }


def test_missing_rules_database_is_undetermined_not_not_found(tmp_path):
    missing = str(tmp_path / "does_not_exist" / "rules.sqlite3")
    payload = _payload([_po("TST1", points="400", seq="1")])
    audit = audit_case("MON-m", payload, lookup=lambda code: get_rule(code, db_path=missing))
    assert [f.rule_status for f in audit.findings] == [STATUS_UNDETERMINED]
    assert not os.path.exists(missing)  # 唯讀查詢不建立空檔


# ── 批次：彙總、快取、持久化 ───────────────────────────────────────


def _zip_with(cases_xml: list[str]) -> bytes:
    text = (
        '<?xml version="1.0" encoding="Big5"?>\r\n<outpatient>\r\n'
        "<tdata><t1>10</t1><t3>11207</t3></tdata>\r\n"
        + "\r\n".join(cases_xml)
        + "\r\n</outpatient>\r\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("TOTFA.xml", text.encode("big5"))
    return buf.getvalue()


def _ddata(seq: int, *, dept: str, doctor: str, orders: list[tuple[str, str, str, str]]) -> str:
    pdatas = "".join(
        f"<pdata><p1>0</p1><p3>{cat}</p3><p4>{code}</p4><p10>1.0</p10>"
        f"<p11>{unit}</p11><p12>{points}</p12><p13>{i + 1}</p13></pdata>"
        for i, (code, cat, unit, points) in enumerate(orders)
    )
    return (
        f"<ddata><dhead><d1>02</d1><d2>{seq}</d2></dhead><dbody>"
        f"<d3>M{seq:04d}</d3><d8>{dept}</d8><d9>1120718</d9><d19>S00123A</d19>"
        f"<d30>{doctor}</d30><d49>測試病患</d49>{pdatas}</dbody></ddata>"
    )


@pytest.fixture
def batch_store(tmp_path):
    store = CaseStore(db_path=str(tmp_path / "cases.sqlite3"))
    cases = [
        _ddata(1, dept="03", doctor="DOC_A", orders=[("TST1", "2", "1", "400"), ("PLAIN", "2", "1", "10")]),
        _ddata(2, dept="03", doctor="DOC_B", orders=[("TST1", "2", "1", "500")]),
        _ddata(3, dept="01", doctor="DOC_A", orders=[("TSTDRUG", "4", "0.00", "0"), ("TSTNULL", "2", "1", "999")]),
        _ddata(4, dept="01", doctor="DOC_A", orders=[("PLAIN", "2", "1", "1")]),  # 無旗標
    ]
    result_zip = _zip_with(cases)
    from elc_audit_engine.parsers.totfa import parse_totfa_zip

    ingest_monthly_declaration(store, parse_totfa_zip(result_zip))
    return store


def test_batch_audit_aggregates_by_department_doctor_and_case_seq(batch_store, rules_db):
    result = audit_batch(batch_store, "MONTHLY-202307", rules_db_path=rules_db)

    assert result.cases_total == 4
    assert result.report["totals"]["cases_total"] == 4
    assert result.report["totals"]["cases_flagged"] == 3  # 第 4 筆無旗標
    assert result.report["by_department"]["03"]["cases_flagged"] == 2
    assert result.report["by_department"]["01"]["cases_flagged"] == 1
    assert result.report["by_doctor"]["DOC_A"]["cases_flagged"] == 2
    assert result.report["by_doctor"]["DOC_B"]["cases_flagged"] == 1
    # case_seq 可重複：以 case_id 為鍵列出全部案件，不以 case_seq 取代主鍵
    assert all(len(ids) == 1 for ids in result.report["by_case_seq"].values())
    assert len(result.report["by_case_seq"]) == 3


def test_batch_audit_status_totals_are_consistent(batch_store, rules_db):
    result = audit_batch(batch_store, "MONTHLY-202307", rules_db_path=rules_db)
    status_totals = result.report["totals"]["rule_status"]
    assert sum(status_totals.values()) == result.report["totals"]["findings"]
    assert status_totals[STATUS_RESTRICTION] == 3  # TST1 × 2 + TSTDRUG（單價 0 → unpriced）
    assert status_totals[STATUS_NO_TEXT] == 1  # TSTNULL（點數 999 > 350，規則無文字）
    assert STATUS_NO_MARKERS not in status_totals


def test_batch_audit_caches_rule_lookups_per_code(batch_store):
    calls: list[str] = []

    def counting(code: str) -> RuleResult:
        calls.append(code)
        return _rule(code, payment_text=PAYMENT_RESTRICT_TEXT) if code == "TST1" else not_found(code)

    audit_batch(batch_store, "MONTHLY-202307", lookup=counting)
    assert calls.count("TST1") == 1  # 同一代碼只查一次規則庫


def test_batch_audit_persists_per_case_artifacts_and_omits_names(batch_store, rules_db):
    result = audit_batch(batch_store, "MONTHLY-202307", rules_db_path=rules_db, persist=True)

    for audit in result.cases:
        stored = batch_store.get_artifact(audit.case_id, ARTIFACT_NAME)
        assert stored == audit.to_dict()

    # 案件產物預設不含規則全文（避免膨脹）；報告端點才以 include_rule_text=True 輸出
    for case in result.to_dict()["cases"]:
        for finding in case["findings"]:
            assert "rule_full_text" not in finding
    full = result.to_dict(include_rule_text=True)
    assert any(f.get("rule_full_text") for c in full["cases"] for f in c["findings"])


def test_batch_audit_on_missing_rules_db_marks_everything_undetermined(batch_store, tmp_path):
    missing = str(tmp_path / "nope" / "rules.sqlite3")
    result = audit_batch(batch_store, "MONTHLY-202307", rules_db_path=missing)
    statuses = set(result.report["totals"]["rule_status"])
    assert statuses == {STATUS_UNDETERMINED}
    assert result.report["totals"]["findings"] > 0


def test_batch_audit_empty_batch_is_empty_not_error(batch_store, rules_db):
    result = audit_batch(batch_store, "MONTHLY-209901", rules_db_path=rules_db)
    assert result.cases_total == 0
    assert result.cases == ()
    assert result.report["totals"]["findings"] == 0


# ── 真實規則庫冒煙（唯讀；檔案不存在則跳過） ─────────────────────────


@pytest.mark.skipif(not os.path.exists(REAL_RULES), reason="data/db/rules.sqlite3 不存在")
def test_real_rule_48003c_restriction_and_icd_match_read_only():
    payload = _payload(
        [_po("48003C", points="400", seq="1")],
        primary="S00123A",
        visit="1120703",
    )
    audit = audit_case("MON-real", payload, lookup=lambda c: get_rule(c, db_path=REAL_RULES))
    finding = audit.findings[0]
    assert finding.rule_status == STATUS_RESTRICTION
    assert "S00.1" in finding.icd_in_rule
    assert finding.evidence
    # 證據可能來自 payment_text 或 article_full_text（兩來源可能不一致），逐一核對原文
    real_rule = get_rule("48003C", db_path=REAL_RULES)
    sources = {"payment_text": real_rule.payment_text or "", "article_full_text": real_rule.article_full_text or ""}
    for ev in finding.evidence:
        assert ev.sentence in sources[ev.source]  # 逐字取自真實規則原文


def test_frequency_limit_without_restriction_marker_is_still_evidence():
    # 「每日最多2次」不含限制用語，但屬頻次限制，必須被視為給付限制證據（不可漏掉）
    rule = _rule("TSTF", payment_text="每日最多2次。")
    finding = evaluate_order(
        _order("TSTF", points="400"),
        case_diagnoses=(),
        visit_date=date(2023, 7, 18),
        lookup=_dict_lookup({"TSTF": rule}),
    )
    assert finding.rule_status == STATUS_RESTRICTION
    assert finding.evidence[0].sentence == "每日最多2次"
    assert "frequency" in finding.evidence[0].kinds
