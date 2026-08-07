"""Tests for server.py integration with CaseStore."""

import io
import json
import pytest

import server
from elc_audit_engine.case_store import CaseStore
from elc_audit_engine.safe_paths import UnsafeIdentifierError


@pytest.fixture(autouse=True)
def setup_tmp_casestore(tmp_path, monkeypatch):
    """Isolate CaseStore to a temporary SQLite database for each test."""
    db_path = str(tmp_path / "cases_test.sqlite3")
    test_store = CaseStore(db_path=db_path)
    monkeypatch.setattr(server, "_case_store", test_store)
    return test_store


@pytest.fixture
def client(monkeypatch):
    server.app.config["TESTING"] = True
    monkeypatch.setitem(server.app.config, "ELC_API_KEYS", {"valid-key-123": "clinic_a"})
    with server.app.test_client() as c:
        yield c


def test_import_sampling_cases_persists_to_casestore(client, setup_tmp_casestore):
    csv_content = (
        "流水號,病歷號,病患姓名,醫令代碼,醫令名稱,就醫日期,科別,SOAP\n"
        "101,M1001,王小明,14050B,HbA1c,20260701,家醫科,S: DM O: BP 120/80 A: DM P: HbA1c\n"
    )
    headers = {"X-API-Key": "valid-key-123"}
    data = {"file": (io.BytesIO(csv_content.encode("utf-8-sig")), "test.csv")}
    resp = client.post("/api/sampling/import", data=data, headers=headers, content_type="multipart/form-data")
    assert resp.status_code == 200
    res_json = resp.get_json()
    assert res_json["status"] == "success"
    assert res_json["case_store_persisted"] == 1
    assert res_json["case_store_conflicts"] == []

    records = setup_tmp_casestore.list_all(kind="sampling")
    assert len(records) == 1
    assert records[0].case_id == "SAMP-0001"
    assert records[0].state == "imported"


def test_duplicate_import_reports_conflicts(client, setup_tmp_casestore):
    csv_content = (
        "流水號,病歷號,病患姓名,醫令代碼,醫令名稱,就醫日期,科別,SOAP\n"
        "101,M1001,王小明,14050B,HbA1c,20260701,家醫科,S: DM O: BP 120/80 A: DM P: HbA1c\n"
    )
    headers = {"X-API-Key": "valid-key-123"}
    data1 = {"file": (io.BytesIO(csv_content.encode("utf-8-sig")), "test1.csv")}
    resp1 = client.post("/api/sampling/import", data=data1, headers=headers, content_type="multipart/form-data")
    assert resp1.status_code == 200

    data2 = {"file": (io.BytesIO(csv_content.encode("utf-8-sig")), "test2.csv")}
    resp2 = client.post("/api/sampling/import", data=data2, headers=headers, content_type="multipart/form-data")
    assert resp2.status_code == 200
    res_json2 = resp2.get_json()
    assert res_json2["case_store_persisted"] == 0
    assert "SAMP-0001" in res_json2["case_store_conflicts"]


def test_migrate_legacy_uploads_idempotent(setup_tmp_casestore, tmp_path, monkeypatch):
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    sample_json = [
        {
            "id": "SAMP-9999",
            "case_seq": "9999",
            "order_code": "14050B",
            "patient_name": "測試員",
        }
    ]
    with open(uploads_dir / "sampling_20260101_000000.json", "w", encoding="utf-8") as f:
        json.dump(sample_json, f)

    monkeypatch.setattr(server, "_UPLOAD_DIR", str(uploads_dir))

    res1 = server._migrate_legacy_uploads(setup_tmp_casestore)
    assert res1["sampling"] == 1
    assert setup_tmp_casestore.get("SAMP-9999").kind == "sampling"

    res2 = server._migrate_legacy_uploads(setup_tmp_casestore)
    assert res2["sampling"] == 0


def test_persist_cases_unsafe_identifier_raises(setup_tmp_casestore):
    cases = [{"id": "../unsafe_id", "case_seq": "1", "order_code": "14050B"}]
    with pytest.raises(UnsafeIdentifierError):
        server._persist_cases("sampling", cases, actor="test")


def test_get_sampling_cases_reads_from_casestore(client, setup_tmp_casestore):
    setup_tmp_casestore.create(
        case_id="SAMP-8888",
        kind="sampling",
        case_seq="8888",
        order_code="14050B",
        payload={"id": "SAMP-8888", "patient_name": "真實資料"},
    )
    headers = {"X-API-Key": "valid-key-123"}
    resp = client.get("/api/sampling/cases", headers=headers)
    assert resp.status_code == 200
    cases = resp.get_json()
    assert len(cases) == 1
    assert cases[0]["id"] == "SAMP-8888"
    assert cases[0]["patient_name"] == "真實資料"


def test_get_sampling_cases_fallback_demo_when_empty(client, setup_tmp_casestore):
    headers = {"X-API-Key": "valid-key-123"}
    resp = client.get("/api/sampling/cases", headers=headers)
    assert resp.status_code == 200
    cases = resp.get_json()
    assert len(cases) >= 1
    assert cases[0]["demo"] is True


def test_audit_sampling_case_with_optional_case_id(client, setup_tmp_casestore):
    setup_tmp_casestore.create(
        case_id="SAMP-1001",
        kind="sampling",
        case_seq="1001",
        order_code="14050B",
        payload={"id": "SAMP-1001"},
    )
    headers = {"X-API-Key": "valid-key-123"}
    body = {
        "case_id": "SAMP-1001",
        "order_code": "14050B",
        "soap_text": "S: DM O: BP 120/80 A: DM P: HbA1c",
    }
    resp = client.post("/api/sampling/audit", json=body, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["case_id"] == "SAMP-1001"

    rec = setup_tmp_casestore.get("SAMP-1001")
    assert rec.state == "reviewed"


def test_audit_sampling_case_nonexistent_case_id_warning_logged(client, setup_tmp_casestore, caplog):
    headers = {"X-API-Key": "valid-key-123"}
    body = {
        "case_id": "SAMP-NONEXISTENT",
        "order_code": "14050B",
        "soap_text": "S: DM O: BP 120/80 A: DM P: HbA1c",
    }
    resp = client.post("/api/sampling/audit", json=body, headers=headers)
    assert resp.status_code == 200
    assert "狀態轉換失敗" in caplog.text


def test_generate_appeal_draft_with_optional_case_id(client, setup_tmp_casestore):
    setup_tmp_casestore.create(
        case_id="APP-2001",
        kind="appeal",
        case_seq="201",
        order_code="14050B",
        payload={"id": "APP-2001"},
    )
    # Fast forward case to reviewed state so transition to appealed is legal
    setup_tmp_casestore.transition("APP-2001", "parsed")
    setup_tmp_casestore.transition("APP-2001", "reviewing")
    setup_tmp_casestore.transition("APP-2001", "reviewed")

    headers = {"X-API-Key": "valid-key-123"}
    body = {
        "case_id": "APP-2001",
        "case_seq": "201",
        "order_code": "14050B",
        "deduction_reason": "超過次數",
    }
    resp = client.post("/api/appeal/generate", json=body, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["case_id"] == "APP-2001"

    rec = setup_tmp_casestore.get("APP-2001")
    assert rec.state == "appealed"
