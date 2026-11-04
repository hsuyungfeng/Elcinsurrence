"""Phase 15-01：TOTFA.zip 解析、批次推得、門檻篩選、CaseStore 冪等匯入。

測試資料一律為合成 XML（Big5 編碼、zip 內包 TOTFA.xml），不含真實病患資料；
唯一的真實檔冒煙測試在 data/TOTFA.zip 存在時才執行，且不輸出任何 PHI。
"""

from __future__ import annotations

import io
import os
import zipfile

import pytest

from elc_audit_engine.case_store.monthly import ingest_monthly_declaration
from elc_audit_engine.case_store.store import CaseStore
from elc_audit_engine.parsers.submission_xml import SubmissionXmlError
from elc_audit_engine.parsers.totfa import (
    batch_name_from_header,
    drugs_over_unit_price,
    monthly_case_ids,
    orders_over_points,
    parse_totfa_zip,
    unpriced_drug_orders,
)

REAL_ZIP = os.path.join(os.path.dirname(__file__), "..", "data", "TOTFA.zip")
SYNTHETIC_NAME = "測試病患"


def _pdata(seq: int, *, cat: str, code: str, unit: str | None, points: str | None) -> str:
    unit_xml = f"<p11>{unit}</p11>" if unit is not None else ""
    points_xml = f"<p12>{points}</p12>" if points is not None else ""
    return (
        f"<pdata><p1>0</p1><p3>{cat}</p3><p4>{code}</p4>"
        f"<p10>1.0</p10>{unit_xml}{points_xml}<p13>{seq}</p13></pdata>"
    )


def _ddata(seq: int, record: str, pdatas: list[str]) -> str:
    return (
        f"<ddata><dhead><d1>02</d1><d2>{seq}</d2></dhead><dbody>"
        f"<d3>{record}</d3><d9>1120718</d9><d19>S90221A</d19>"
        f"<d49>{SYNTHETIC_NAME}</d49>{''.join(pdatas)}</dbody></ddata>"
    )


def _xml_bytes(ddatas: list[str], *, t3: str = "11207") -> bytes:
    text = (
        '<?xml version="1.0" encoding="Big5"?>\r\n<outpatient>\r\n'
        f"<tdata><t1>10</t1><t2>3503250461</t2><t3>{t3}</t3></tdata>\r\n"
        + "\r\n".join(ddatas)
        + "\r\n</outpatient>\r\n"
    )
    return text.encode("big5")


def _zip_bytes(xml: bytes, name: str = "TOTFA.xml") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, xml)
    return buf.getvalue()


def _sample_zip() -> bytes:
    cases = [
        _ddata(
            1,
            "M0001",
            [
                _pdata(1, cat="2", code="47039C", unit="28.00", points="28"),
                _pdata(2, cat="2", code="64140C", unit="4640.00", points="351"),
                _pdata(3, cat="4", code="AC37603100", unit="0.00", points="0"),
                _pdata(4, cat="4", code="B000001", unit="6.50", points="0"),
            ],
        ),
        _ddata(
            2,
            "M0002",
            [
                _pdata(1, cat="0", code="01015C", unit="350.00", points="350"),
                _pdata(2, cat="4", code="C000002", unit="5.00", points="0"),
            ],
        ),
    ]
    return _zip_bytes(_xml_bytes(cases))


@pytest.fixture
def store(tmp_path) -> CaseStore:
    return CaseStore(db_path=str(tmp_path / "cases.sqlite3"))


# ── 讀取與批次 ─────────────────────────────────────────────────────


def test_parse_zip_reads_big5_xml_from_memory():
    result = parse_totfa_zip(_sample_zip())

    assert result.header["t3"] == "11207"
    assert len(result.cases) == 2
    assert result.rejected == ()
    first = result.cases[0]
    assert first.case_seq == "1"
    assert first.record_no == "M0001"
    assert first.primary_diagnosis == "S90221A"
    assert len(first.orders) == 4


def test_batch_name_is_roc_year_month_converted_to_gregorian():
    assert batch_name_from_header({"t3": "11207"}) == "MONTHLY-202307"
    assert batch_name_from_header({"t3": "11212"}) == "MONTHLY-202312"


@pytest.mark.parametrize("t3", [None, "", "11213", "abc", "1120"])
def test_batch_name_rejects_bad_year_month(t3):
    header = {} if t3 is None else {"t3": t3}
    with pytest.raises(SubmissionXmlError):
        batch_name_from_header(header)


def test_zip_member_in_subfolder_is_found():
    result = parse_totfa_zip(_zip_bytes(_xml_bytes([_ddata(1, "M1", [_pdata(1, cat="2", code="X", unit="1", points="1")])]), name="export/TOTFA.xml"))
    assert len(result.cases) == 1


def test_zip_without_totfa_xml_is_rejected():
    with pytest.raises(SubmissionXmlError, match="找不到"):
        parse_totfa_zip(_zip_bytes(_xml_bytes([]), name="other.xml"))


def test_zip_with_two_totfa_xml_is_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a/TOTFA.xml", _xml_bytes([]))
        zf.writestr("b/TOTFA.xml", _xml_bytes([]))
    with pytest.raises(SubmissionXmlError, match="多份"):
        parse_totfa_zip(buf.getvalue())


def test_corrupt_zip_is_rejected():
    with pytest.raises(SubmissionXmlError):
        parse_totfa_zip(b"not a zip at all")


# ── 門檻篩選 ─────────────────────────────────────────────────────


def test_orders_over_points_is_strictly_greater_than_350():
    result = parse_totfa_zip(_sample_zip())
    case_1, case_2 = result.cases

    assert [o.code for o in orders_over_points(case_1)] == ["64140C"]  # 351 > 350
    assert orders_over_points(case_2) == ()  # 350 不超過門檻


def test_orders_with_missing_points_are_not_flagged():
    xml = _xml_bytes([_ddata(1, "M1", [_pdata(1, cat="2", code="NOPT", unit="1", points=None)])])
    case = parse_totfa_zip(_zip_bytes(xml)).cases[0]
    assert orders_over_points(case) == ()


def test_drugs_over_unit_price_only_checks_drug_lines():
    result = parse_totfa_zip(_sample_zip())
    case_1, case_2 = result.cases

    # case_1：B000001 藥品單價 6.50 > 5 命中；procedure 行 unit 28/4640 雖大於 5 但不是藥品
    assert [o.code for o in drugs_over_unit_price(case_1)] == ["B000001"]
    # case_2：C000002 單價 5.00 不超過門檻；非藥品 01015C 單價 350 不列入
    assert drugs_over_unit_price(case_2) == ()


def test_unpriced_drug_lines_are_surfaced_not_silently_passed():
    result = parse_totfa_zip(_sample_zip())
    case_1, case_2 = result.cases

    assert [o.code for o in unpriced_drug_orders(case_1)] == ["AC37603100"]
    assert [o.code for o in unpriced_drug_orders(case_2)] == []  # C000002 有單價 5.00


def test_filters_do_not_mutate_source_orders():
    result = parse_totfa_zip(_sample_zip())
    before = len(result.cases[0].orders)
    orders_over_points(result.cases[0])
    drugs_over_unit_price(result.cases[0])
    assert len(result.cases[0].orders) == before


# ── 內容雜湊 ID ──────────────────────────────────────────────────


def test_case_ids_are_stable_across_reparse():
    first = monthly_case_ids("MONTHLY-202307", parse_totfa_zip(_sample_zip()).cases)
    second = monthly_case_ids("MONTHLY-202307", parse_totfa_zip(_sample_zip()).cases)
    assert first == second
    assert all(cid.startswith("MON-") for cid in first)
    assert len(set(first)) == len(first)


def test_same_content_in_different_batches_gets_different_ids():
    cases = parse_totfa_zip(_sample_zip()).cases
    assert set(monthly_case_ids("MONTHLY-202307", cases)).isdisjoint(
        monthly_case_ids("MONTHLY-202308", cases)
    )


def test_identical_records_in_one_file_keep_distinct_ids():
    dup = _ddata(7, "M9", [_pdata(1, cat="2", code="SAME", unit="1", points="1")])
    cases = parse_totfa_zip(_zip_bytes(_xml_bytes([dup, dup]))).cases
    ids = monthly_case_ids("MONTHLY-202307", cases)
    assert len(ids) == 2 and ids[0] != ids[1]


# ── CaseStore 冪等匯入 ───────────────────────────────────────────


def test_ingest_creates_monthly_cases_and_is_idempotent(store):
    result = parse_totfa_zip(_sample_zip())

    first = ingest_monthly_declaration(store, result, actor="tester")
    assert first.batch == "MONTHLY-202307"
    assert (first.created, first.skipped_existing, first.rejected) == (2, 0, 0)
    assert store.count_by_batch("MONTHLY-202307") == 2

    second = ingest_monthly_declaration(store, parse_totfa_zip(_sample_zip()), actor="tester")
    assert (second.created, second.skipped_existing) == (0, 2)
    assert store.count_by_batch("MONTHLY-202307") == 2
    assert store.count(kind="monthly") == 2


def test_ingested_case_uses_content_hash_id_and_keeps_case_seq(store):
    result = parse_totfa_zip(_sample_zip())
    summary = ingest_monthly_declaration(store, result)

    record = store.get(summary.case_ids[0])
    assert record.kind == "monthly"
    assert record.state == "imported"
    assert record.case_seq == "1"  # case_seq 可重複，僅作欄位，不作主鍵
    assert record.payload["batch"] == "MONTHLY-202307"
    assert record.payload["record_no"] == "M0001"


def test_patient_identifiers_are_persisted_for_report(store):
    ingest_monthly_declaration(store, parse_totfa_zip(_sample_zip()))
    payloads = [record.payload for record in store.list_by_batch("MONTHLY-202307")]
    assert payloads
    for payload in payloads:
        assert payload["patient_name"] == SYNTHETIC_NAME  # d49（需求：報告顯示姓名）
        assert payload["record_no"]  # d3 病歷號
        assert "birth_date" in payload  # d11（此合成檔未提供，值為 None）
    assert {p["record_no"] for p in payloads} == {"M0001", "M0002"}


def test_list_by_batch_only_returns_that_batch(store):
    ingest_monthly_declaration(store, parse_totfa_zip(_sample_zip()))
    other = _zip_bytes(_xml_bytes([_ddata(9, "MX", [_pdata(1, cat="2", code="Z", unit="1", points="1")])], t3="11208"))
    ingest_monthly_declaration(store, parse_totfa_zip(other))

    assert store.count_by_batch("MONTHLY-202307") == 2
    assert store.count_by_batch("MONTHLY-202308") == 1
    assert len(store.list_by_batch("MONTHLY-202307")) == 2
    assert store.list_by_batch("MONTHLY-202399") == ()


def test_rejected_cases_are_counted_not_stored(store):
    bad = "<ddata><dhead><d1>02</d1><d2>5</d2></dhead><dbody><d3>M5</d3><d19>X</d19></dbody></ddata>"
    good = _ddata(6, "M6", [_pdata(1, cat="2", code="OK", unit="1", points="1")])
    summary = ingest_monthly_declaration(store, parse_totfa_zip(_zip_bytes(_xml_bytes([bad, good]))))

    assert (summary.created, summary.rejected) == (1, 1)
    assert store.count_by_batch("MONTHLY-202307") == 1


def test_monthly_kind_is_accepted_and_unknown_kind_still_rejected(store):
    store.create(case_id="MON-manualtest", kind="monthly")
    assert store.get("MON-manualtest").kind == "monthly"
    from elc_audit_engine.case_store.store import CaseStoreError

    with pytest.raises(CaseStoreError):
        store.create(case_id="BAD-kind", kind="unknown")


# ── 真實檔冒煙（有檔才跑；不輸出 PHI） ─────────────────────────────


@pytest.mark.skipif(not os.path.exists(REAL_ZIP), reason="data/TOTFA.zip 不存在")
def test_real_totfa_zip_parses_to_expected_shape():
    result = parse_totfa_zip(REAL_ZIP)

    assert batch_name_from_header(result.header) == "MONTHLY-202307"
    assert len(result.cases) == 633
    assert result.rejected == ()
    # 規格實測：點數 > 350 的醫令有數百筆；藥品行單價皆為 0（無法以單價門檻判定）
    assert sum(len(orders_over_points(c)) for c in result.cases) > 0
    assert sum(len(drugs_over_unit_price(c)) for c in result.cases) == 0
    assert sum(len(unpriced_drug_orders(c)) for c in result.cases) > 0
