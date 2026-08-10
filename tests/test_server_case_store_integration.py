"""Tests for server.py integration with CaseStore."""

import io
import json
import pytest

import server
from elc_audit_engine.case_store import CaseStore
from elc_audit_engine.parsers.models import DeductionRecord
from elc_audit_engine.safe_paths import UnsafeIdentifierError


@pytest.fixture(autouse=True)
def setup_tmp_casestore(tmp_path, monkeypatch):
    """Isolate CaseStore to a temporary SQLite database for each test."""
    db_path = str(tmp_path / "cases_test.sqlite3")
    test_store = CaseStore(db_path=db_path)
    monkeypatch.setattr(server, "_case_store", test_store)
    return test_store


@pytest.fixture(autouse=True)
def tmp_upload_dirs(tmp_path, monkeypatch):
    """把上傳目錄（data/uploads 系）指到 tmp_path，避免測試污染專案 data/。

    沙箱環境中專案 data/ 為唯讀（reasonix bwrap 只對 plan 允許修改的檔案
    開放寫入），CSV 上傳測試若寫 data/uploads 會以 OSError 500 失敗。此
    fixture 只改落盤位置、不變更測試斷言語義（既有 import 測試行為不變）。
    """
    monkeypatch.setattr(server, "_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(server, "_RAW_DIR", str(tmp_path / "uploads" / "raw"))


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
    assert isinstance(data["rule_found"], bool)

    # W4 契約橋（D-03）：回應主體為 render_appeal_json 標準契約鍵，無舊鍵。
    assert isinstance(data["sections"], list)
    assert len(data["sections"]) >= 1
    for sec in data["sections"]:
        assert {"key", "title", "text", "trimmed"}.issubset(sec)
    assert data["word_stats"]["total_chars"] >= 0
    assert isinstance(data["p8_reason1"], str)
    assert isinstance(data["p9_reason2"], str)
    # p6_points 為 render_appeal_json 標準契約內建鍵（appeal.py:499 申復 XML 醫令段）。
    assert isinstance(data["p6_points"], int) and data["p6_points"] >= 0
    # case_seq/order_code 同為標準契約內建鍵（appeal.py:485/487），值透傳請求輸入。
    assert data["case_seq"] == "201"
    assert data["order_code"] == "14050B"
    # case_class 非 generate handler 可填（record.case_class 缺省 None）——屬
    # plan 09.1-03 轉換層補欄範圍，此處誠實為 None。
    assert data["case_class"] is None
    for old_key in (
        "appeal_sections",
        "reason1",
        "reason2",
        "total_char_count",
        "xml_p8_p9_valid",
        "over_limit",
        "record_no",
    ):
        assert old_key not in data, f"舊鍵 {old_key} 不應再出現於回應"

    # W1 合法邊（D-01）：imported 案件不經 fast-forward 直接 generate 即達 appealed。
    rec = setup_tmp_casestore.get("APP-2001")
    assert rec.state == "appealed"


def test_to_appeal_case_passthroughs_id_number():
    """W5 數據流（D-05 前置）：_to_appeal_case 透傳 rec.id_number（健保署已遮罩
    後 4 碼，models.py:166/189）——僅透傳不重組；缺省時 None，不捏造。
    """
    out = server._to_appeal_case(
        1,
        DeductionRecord(id_number="A123****", case_seq="201", order_code="14050B"),
    )
    assert out["id_number"] == "A123****"

    out_missing = server._to_appeal_case(
        1,
        DeductionRecord(case_seq="201", order_code="14050B"),
    )
    assert out_missing["id_number"] is None


def test_generate_appeal_draft_passthroughs_order_seq(client, setup_tmp_casestore):
    """11.1-01 Test 1/2（API 路徑醫令序對應）：generate 請求帶 order_seq →
    回應（render_appeal_json 契約）的 order_seq/p1_order_seq 透傳為該值；
    不帶 order_seq → None（不捏造）。"""
    headers = {"X-API-Key": "valid-key-123"}

    body_with_seq = {
        "case_seq": "201",
        "order_code": "14050B",
        "deduction_reason": "超過次數",
        "order_seq": "3",
    }
    resp = client.post("/api/appeal/generate", json=body_with_seq, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["order_seq"] == "3"
    assert data["p1_order_seq"] == "3"

    body_no_seq = {
        "case_seq": "202",
        "order_code": "14050B",
        "deduction_reason": "超過次數",
    }
    resp2 = client.post("/api/appeal/generate", json=body_no_seq, headers=headers)
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2["order_seq"] is None
    assert data2["p1_order_seq"] is None
