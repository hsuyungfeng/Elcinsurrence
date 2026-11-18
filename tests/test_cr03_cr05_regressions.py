"""CR-03（批次讀取靜默截斷）與 CR-05（同名跨病人 SOAP 綁定）回歸測試。"""

from __future__ import annotations

import pytest

from elc_audit_engine.case_store import CaseStore
from elc_audit_engine.reconciliation import soap_reconciler


@pytest.fixture
def store(tmp_path):
    return CaseStore(db_path=str(tmp_path / "cases.sqlite3"))


def test_iter_by_batch_returns_every_record_across_pages(store):
    """CR-03：逐頁讀取不得因單次上限而丟案件。"""
    for i in range(5):
        store.create(
            case_id=f"MON-{i:03d}",
            kind="monthly",
            payload={"batch": "MONTHLY-TEST", "case_seq": str(i)},
        )
    got = [r.case_id for r in store.iter_by_batch("MONTHLY-TEST", page_size=2)]
    assert len(got) == 5
    assert len(set(got)) == 5


def test_iter_all_returns_every_record_across_pages(store):
    for i in range(3):
        store.create(case_id=f"SAMP-{i:03d}", kind="sampling", payload={"n": i})
    got = list(store.iter_all(kind="sampling", page_size=2))
    assert len(got) == 3


def test_same_name_different_id_is_not_matched(store, monkeypatch):
    """CR-05：只有姓名相同、身分證不同時，不得回傳他人的 SOAP。"""
    from elc_audit_engine.api.routes import his_integration

    patient_db = {
        "A111111111": {
            "patient_name": "王小明",
            "encounters": [{"visit_date": "1150301", "soap": {"S": "他人的主訴"}}],
        }
    }
    monkeypatch.setattr(his_integration, "PATIENT_DB", patient_db, raising=False)

    result = soap_reconciler.reconcile_case_soap(
        store,
        {"id_card": "B222222222", "visit_date": "1150301", "patient_name": "王小明"},
    )
    assert result["found"] is False
    assert result["soap"] == ""


def test_same_id_still_matches(store, monkeypatch):
    """CR-05 修復不得影響正常的身分證精確比對。"""
    from elc_audit_engine.api.routes import his_integration

    patient_db = {
        "A111111111": {
            "patient_name": "王小明",
            "encounters": [{"visit_date": "1150301", "soap": {"S": "本人主訴"}}],
        }
    }
    monkeypatch.setattr(his_integration, "PATIENT_DB", patient_db, raising=False)

    result = soap_reconciler.reconcile_case_soap(
        store,
        {"id_card": "A111111111", "visit_date": "1150301", "patient_name": "王小明"},
    )
    assert result["found"] is True
    assert result["source"] == "patient_db_local"
