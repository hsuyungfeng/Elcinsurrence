"""Info 第二組：資料正確性（A-IN-03、B-IN-03/04/07/08/10/11/12）。"""
import json

import pytest

from elc_audit_engine.eval.gold_standard import GoldStandardError, load_gold_standard
from elc_audit_engine.generators.evidence_packet import render_evidence_packet
from elc_audit_engine.parsers.deduction import parse_deduction_file
from elc_audit_engine.rule_repository.docx_tree.doc_converter import list_by_ext
from elc_audit_engine.rule_repository.loaders._csv_table import RuleCsvFormatError
from elc_audit_engine.rule_repository.loaders.dates import parse_flexible_date
from elc_audit_engine.rule_repository.loaders.payment_loader import load_payment_csv
from elc_audit_engine.rule_repository.mapping.versions import extract_csv_version


@pytest.mark.parametrize("raw, iso", [
    ("9991231", None), ("115/07/10", "2026-07-10"), ("2026/7/1", "2026-07-01"), ("2026-07-10", "2026-07-10"),
])
def test_dates(raw, iso):
    assert parse_flexible_date(raw) == iso


def test_rejected_row_has_file_line_number(tmp_path):
    good = ("0000000300,1234567890,202106,20210803,D2,18,20210623,19440901,"
            "F10291****,1,E5002C,20210623,1,300,20210820,原因,A-說明,備註")
    f = tmp_path / "d.csv"
    f.write_text(good + "\n\n\n1,2,3\n", encoding="utf-8")
    res = parse_deduction_file(str(f), encoding="utf-8")
    assert res.rejected[0].row_number == 2
    assert res.rejected[0].line_number == 4


def test_version_tag_uses_contiguous_digits(tmp_path):
    f = tmp_path / "2-2-7手術251027.csv"
    f.write_text("x", encoding="utf-8")
    assert extract_csv_version(str(f)).startswith("251027:")


def test_list_by_ext_case_insensitive(tmp_path):
    for n in ("a.doc", "B.DOC", "c.docx", "D.DOCX"):
        (tmp_path / n).write_bytes(b"x")
    assert [p.rsplit("/", 1)[1] for p in list_by_ext(str(tmp_path), ".doc")] == ["B.DOC", "a.doc"]
    assert len(list_by_ext(str(tmp_path), ".docx")) == 2


def test_loader_missing_column_is_explicit(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("診療項目代碼,中文項目名稱\nA0001C,甲\n", encoding="utf-8-sig")
    with pytest.raises(RuleCsvFormatError, match="支付規定"):
        load_payment_csv(str(tmp_path / "r.sqlite3"), str(f))


def test_gold_standard_non_dict_item(tmp_path):
    f = tmp_path / "g.json"
    f.write_text(json.dumps(["x"]), encoding="utf-8")
    with pytest.raises(GoldStandardError):
        load_gold_standard(str(f))


def test_cover_does_not_fabricate_case_class_and_shows_facility():
    from docx import Document
    import io

    docx_bytes, _ = render_evidence_packet(
        {"case_seq": "9", "order_code": "64140C", "deduction_upper_bound": 300, "p6_points": 300},
        {"name": "示例醫療院所", "code": "01015C"},
    )
    text = "\n".join(p.text for p in Document(io.BytesIO(docx_bytes)).paragraphs)
    assert "案件分類: —" in text
    assert "示例醫療院所" in text and "不予核銷點數合計: 300" in text


def test_soap_keywords_longest_match_and_ascii_boundaries():
    """B-IN-05"""
    from elc_audit_engine.parsers.soap import _classify_sentence

    assert _classify_sentence("開立止痛藥")[0] == "P"          # 「痛」不替 S 加分
    assert _classify_sentence("ACTIVE lifestyle")[0] == "UNKNOWN"  # CT 不命中 ACTIVE
    assert _classify_sentence("安排CT檢查")[0] == "O"


def test_table_ocr_engine_failure_cached(monkeypatch):
    """B-IN-06"""
    import builtins

    from elc_audit_engine.ingest import table_ocr

    monkeypatch.setattr(table_ocr, "_engine", None)
    monkeypatch.setattr(table_ocr, "_engine_failed", False)
    calls = []
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "paddleocr":
            calls.append(1)
            raise ImportError("no paddle")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert table_ocr._get_engine() is None
    assert table_ocr._get_engine() is None
    assert calls == [1]
