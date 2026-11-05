"""Unit tests for Phase 28-01: Monthly Declaration and Daily Voice SOAP Reconciliation.

Tests:
1. reconcile_case_soap against PATIENT_DB and CaseStore (kind='his').
2. ingest_monthly_declaration automatically enriches cases with real SOAP and vault metadata.
3. sampling and appeal promotion inherits the reconciled SOAP.
"""

import pytest
from elc_audit_engine.case_store.store import CaseStore
from elc_audit_engine.case_store.monthly import ingest_monthly_declaration
from elc_audit_engine.parsers.models import SubmissionCase, OrderRecord, SubmissionParseResult
from elc_audit_engine.reconciliation.soap_reconciler import (
    reconcile_case_soap,
    reconcile_monthly_batch,
    format_soap_to_text,
)
from elc_audit_engine.monthly_patient_service import (
    monthly_payload_to_sampling_case,
    monthly_payload_to_appeal_case,
    add_sampling_case_by_patient,
    add_appeal_case_by_patient,
)


@pytest.fixture
def store(tmp_path):
    return CaseStore(str(tmp_path / "test_reconcile.sqlite3"))


def test_format_soap_to_text():
    # Dict SOAP
    soap_dict = {
        "s": "Sore throat",
        "o": "Fever 38C",
        "a": "Pharyngitis",
        "p": "Antibiotics",
    }
    txt = format_soap_to_text(soap_dict)
    assert "[S] Sore throat" in txt
    assert "[O] Fever 38C" in txt
    assert "[A] Pharyngitis" in txt
    assert "[P] Antibiotics" in txt

    # String SOAP
    raw_str = "S: Headache\nO: Normal\nA: Tension\nP: Rest"
    assert format_soap_to_text(raw_str) == raw_str


def test_reconcile_case_soap_patient_db(store):
    # 王大明 1120920 (DM follow-up in PATIENT_DB)
    payload_wang = {
        "id_card": "A123456789",
        "patient_name": "王大明",
        "visit_date": "1120920",
    }
    res_wang = reconcile_case_soap(store, payload_wang)
    assert res_wang["found"] is True
    assert "Diabetes" in res_wang["soap_text"] or "refill" in res_wang["soap_text"]
    assert res_wang["vault_key"] == "A123456789-2609"
    assert len(res_wang["vault_files"]) >= 1

    # 陳美玲 1120718 (Knee arthritis in PATIENT_DB)
    payload_chen = {
        "id_card": "F229871234",
        "patient_name": "陳美玲",
        "visit_date": "1120718",
    }
    res_chen = reconcile_case_soap(store, payload_chen)
    assert res_chen["found"] is True
    assert "knee" in res_chen["soap_text"].lower() or "osteoarthritis" in res_chen["soap_text"].lower()
    assert res_chen["vault_key"] == "F229871234-2607"

    # Non-existent patient
    payload_none = {
        "id_card": "Z999999999",
        "patient_name": "無名氏",
        "visit_date": "1120718",
    }
    res_none = reconcile_case_soap(store, payload_none)
    assert res_none["found"] is False
    assert res_none["soap_text"] == ""


def test_reconcile_case_soap_casestore_his(store):
    # Pre-populate a kind='his' case in CaseStore
    store.create(
        case_id="ENC-HIS-T123456789-1120710",
        kind="his",
        payload={
            "id_card": "T123456789",
            "patient_name": "張小明",
            "visit_date": "1120710",
            "soap": {
                "s": "Cough for 3 days",
                "o": "Chest clear",
                "a": "Upper respiratory tract infection",
                "p": "Medication for 3 days",
            },
            "vault_key": "T123456789-2607",
            "vault_files": [{"category": "audio", "filename": "rec.opus", "size": 1000}],
        },
    )

    payload_zhang = {
        "id_card": "T123456789",
        "patient_name": "張小明",
        "visit_date": "1120710",
    }
    res = reconcile_case_soap(store, payload_zhang)
    assert res["found"] is True
    assert res["source"] == "casestore_his"
    assert "Cough" in res["soap_text"]
    assert res["vault_key"] == "T123456789-2607"
    assert len(res["vault_files"]) == 1


def test_ingest_monthly_declaration_reconciles_soap(store):
    header = {
        "t1": "MONTHLY-11209",
        "t2": "3503250461",
        "t3": "11209",
    }
    cases = [
        SubmissionCase(
            case_seq="0001",
            case_class="09",
            record_no="A123456789",
            patient_name="王大明",
            birth_date="0540812",
            visit_date="1120920",
            clinic="西醫",
            primary_diagnosis="E11.9",
            secondary_diagnoses=[],
            orders=[OrderRecord(code="14050B", points="100", seq="1", raw={"p4": "14050B", "p12": "100", "p13": "1"})],
            warnings=[],
            raw={"d3": "A123456789", "d9": "1120920", "d39": "100"},
        ),
        SubmissionCase(
            case_seq="0002",
            case_class="09",
            record_no="Z999999999",
            patient_name="未知病患",
            birth_date="0800101",
            visit_date="1120920",
            clinic="西醫",
            primary_diagnosis="J00",
            secondary_diagnoses=[],
            orders=[OrderRecord(code="00110C", points="200", seq="1", raw={"p4": "00110C", "p12": "200", "p13": "1"})],
            warnings=[],
            raw={"d3": "Z999999999", "d9": "1120920", "d39": "200"},
        ),
    ]
    result = SubmissionParseResult(header=header, cases=cases, rejected=[])

    ingest_summary = ingest_monthly_declaration(store, result)
    assert ingest_summary.created == 2

    # Check that case 1 (王大明) has reconciled SOAP in CaseStore
    rec1 = store.get(ingest_summary.case_ids[0])
    assert rec1.payload.get("soap") != ""
    assert "Diabetes" in rec1.payload.get("soap_text") or "refill" in rec1.payload.get("soap_text")
    assert rec1.payload.get("vault_key") == "A123456789-2609"

    # Check that case 2 has empty SOAP (no error)
    rec2 = store.get(ingest_summary.case_ids[1])
    assert rec2.payload.get("soap") == ""
    assert rec2.payload.get("soap_text") == ""


def test_sampling_and_appeal_inheritance(store):
    payload = {
        "batch": "MONTHLY-11209",
        "case_seq": "0001",
        "id_card": "A123456789",
        "patient_name": "王大明",
        "birth_date": "0540812",
        "visit_date": "1120920",
        "soap": "Chief Complaint: Regular refill visit for DM",
        "soap_text": "Chief Complaint: Regular refill visit for DM",
        "vault_key": "A123456789-2609",
        "vault_files": [{"category": "images", "filename": "xray.jpg"}],
        "orders": [{"p4": "14050B", "p12": "100", "p13": "1"}],
    }

    # 1. Convert to sampling case
    s_case = monthly_payload_to_sampling_case(payload)
    assert "DM" in s_case["soap"]
    assert s_case["vault_key"] == "A123456789-2609"
    assert len(s_case["vault_files"]) == 1

    # 2. Convert to appeal case
    a_case = monthly_payload_to_appeal_case(payload)
    assert "DM" in a_case["soap"]
    assert a_case["vault_key"] == "A123456789-2609"
    assert len(a_case["multisource_evidence"]["images"]) == 1
    assert a_case["multisource_evidence"]["images"][0]["name"] == "xray.jpg"
