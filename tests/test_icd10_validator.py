"""本機 ICD-10 診斷碼合法性與語意矛盾核對器測試（Phase 33）。"""

from __future__ import annotations

import sqlite3

from elc_audit_engine.comparator.icd10_validator import (
    extract_icd10_codes,
    validate_icd10_in_assessment,
)


def test_extract_icd10_codes_preserves_order_and_deduplicates():
    codes = extract_icd10_codes("1. Calcific tendinitis (M75.3), Chronic LBP (M54.5), M75.3")
    assert codes == ["M75.3", "M54.5"]


def test_builtin_lookup_recognizes_orthopedic_and_metabolic_codes():
    results = validate_icd10_in_assessment(
        "Adhesive capsulitis of right shoulder (M75.01); Hyperuricemia (E79.0)."
    )
    assert len(results) == 2
    assert results[0].code == "M75.01"
    assert results[0].known is True
    assert results[0].warning is None
    assert results[1].code == "E79.0"
    assert results[1].known is True
    assert results[1].warning is None


def test_detects_e760_hyperuricemia_semantic_mismatch():
    results = validate_icd10_in_assessment(
        "Chronic Myofascial Pain Syndrome (M79.1), Hyperlipidemia (E78.5), Hyperuricemia (E76.0)."
    )
    by_code = {r.code: r for r in results}
    assert by_code["M79.1"].warning is None
    assert by_code["E78.5"].warning is None
    assert by_code["E76.0"].known is True
    assert by_code["E76.0"].warning is not None
    assert "黏多醣貯積症" in by_code["E76.0"].warning


def test_unknown_code_marked_without_crashing():
    results = validate_icd10_in_assessment("Rare unlisted condition (Q99.8).")
    assert len(results) == 1
    assert results[0].code == "Q99.8"
    assert results[0].known is False
    assert results[0].source == "unknown"


def test_optional_medical_db_lookup_takes_priority(tmp_path):
    db_path = tmp_path / "medical.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE icd10 (code TEXT, title_zh TEXT)")
    conn.execute("INSERT INTO icd10 VALUES ('Q99.8', '測試自訂代碼名稱')")
    conn.commit()
    conn.close()

    results = validate_icd10_in_assessment(
        "Custom condition (Q99.8).",
        medical_db_path=str(db_path),
    )
    assert len(results) == 1
    assert results[0].known is True
    assert results[0].source == "medical_db"
    assert results[0].title_zh == "測試自訂代碼名稱"
