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


# ── 11.1-02：Phase 4 病歷時間軸接入 Flask API（BLOCKER-1）──────────


def _write_records_fixture(root, patient_id: str):
    """在 tmp_path 寫下 LocalFileProvider 契約病歷檔（最小契約即可）。

    日期取 2026-07-01：落在 build_timeline 預設半年窗（以執行當日
    2026-08 前後為 end_date）內，Test 1 才能得到 timeline 非 None。
    """
    patient_dir = root / patient_id
    patient_dir.mkdir(parents=True, exist_ok=True)
    (patient_dir / "records.json").write_text(
        json.dumps(
            {"visits": [{"date": "2026-07-01", "clinic": "內科", "soap_text": "S: DM O: 無異常"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return root


def test_audit_sampling_case_with_records_timeline(client, setup_tmp_casestore, tmp_path, monkeypatch):
    """11.1-02 Task1 Test1：RECORDS_DIR 存在＋帶 record_no → LocalFileProvider
    實查、timeline 傳入 run_presubmission_check（records_degraded=false、ok）。"""
    from config import settings

    records_dir = _write_records_fixture(tmp_path, "P001")
    monkeypatch.setattr(settings, "RECORDS_DIR", str(records_dir))
    headers = {"X-API-Key": "valid-key-123"}
    body = {
        "order_code": "14050B",
        "soap_text": "S: DM O: BP 120/80 A: DM P: HbA1c",
        "record_no": "P001",
    }
    resp = client.post("/api/sampling/audit", json=body, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["records_degraded"] is False
    assert data["records_source"] == "ok"
    assert data["records_degraded_reason"] is None


def test_audit_sampling_case_patient_records_absent(client, setup_tmp_casestore, tmp_path, monkeypatch):
    """Task1 Test2：病患缺席（RECORDS_DIR 存在但無該病歷號目錄）→ 已查詢、
    C5 降級，records_source=absent（與 unconfigured 區分）。"""
    from config import settings

    records_dir = tmp_path / "records"
    records_dir.mkdir()
    monkeypatch.setattr(settings, "RECORDS_DIR", str(records_dir))
    headers = {"X-API-Key": "valid-key-123"}
    body = {
        "order_code": "14050B",
        "soap_text": "S: DM O: BP 120/80 A: DM P: HbA1c",
        "record_no": "NO_SUCH_PATIENT",
    }
    resp = client.post("/api/sampling/audit", json=body, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["records_degraded"] is True
    assert data["records_source"] == "absent"
    assert data["records_degraded_reason"] == "查無此病患病歷檔案"


def test_audit_sampling_case_records_dir_unconfigured(client, setup_tmp_casestore, tmp_path, monkeypatch):
    """Task1 Test3：RECORDS_DIR 不存在 → records_source=unconfigured
    （病歷來源未設定，未嘗試查詢，不得偽裝成 absent）。"""
    from config import settings

    monkeypatch.setattr(settings, "RECORDS_DIR", str(tmp_path / "no_such_records"))
    headers = {"X-API-Key": "valid-key-123"}
    body = {
        "order_code": "14050B",
        "soap_text": "S: DM O: BP 120/80 A: DM P: HbA1c",
        "record_no": "P001",
    }
    resp = client.post("/api/sampling/audit", json=body, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["records_degraded"] is True
    assert data["records_source"] == "unconfigured"
    assert data["records_degraded_reason"] == "病歷來源未設定（病歷目錄不存在）"


def test_audit_sampling_case_no_record_no(client, setup_tmp_casestore, tmp_path, monkeypatch):
    """Task1 Test4（回歸）：RECORDS_DIR 存在但不帶 record_no → records_source
    =no_record_no（有來源但請求未提供病歷號，未嘗試查詢）。"""
    from config import settings

    records_dir = _write_records_fixture(tmp_path, "P001")
    monkeypatch.setattr(settings, "RECORDS_DIR", str(records_dir))
    headers = {"X-API-Key": "valid-key-123"}
    body = {
        "order_code": "14050B",
        "soap_text": "S: DM O: BP 120/80 A: DM P: HbA1c",
    }
    resp = client.post("/api/sampling/audit", json=body, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["records_degraded"] is True
    assert data["records_source"] == "no_record_no"
    assert data["records_degraded_reason"] == "請求未提供病歷號"


def test_audit_sampling_case_corrupt_records_500(client, setup_tmp_casestore, tmp_path, monkeypatch):
    """Task1 Test5：records.json 損毀（infra 故障）→ RecordProviderError 穿透
    統一 500（status=error），不得降級成業務結論（P0-2/T-1112-03）。"""
    from config import settings

    records_dir = tmp_path / "records"
    patient_dir = records_dir / "P001"
    patient_dir.mkdir(parents=True)
    (patient_dir / "records.json").write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(settings, "RECORDS_DIR", str(records_dir))
    headers = {"X-API-Key": "valid-key-123"}
    body = {
        "order_code": "14050B",
        "soap_text": "S: DM O: BP 120/80 A: DM P: HbA1c",
        "record_no": "P001",
    }
    resp = client.post("/api/sampling/audit", json=body, headers=headers)
    assert resp.status_code == 500
    data = resp.get_json()
    assert data["status"] == "error"


def test_generate_appeal_draft_timeline_injection(client, setup_tmp_casestore, tmp_path, monkeypatch):
    """11.1-02 Task2 Test1-4：/api/appeal/generate 帶 record_no（前端 appeal
    面板病歷號輸入欄 aRecordNoInput 送出）→ timeline 真實傳入 build_appeal_draft
    （②醫療必要性含半年病史），四態 records_source 正確。

    請求體即前端 generateAppealDraft 自 aRecordNoInput 輸入欄送出的內容
    （配合 tests/test_ingest.py::test_index_html_appeal_record_no_input 靜態
    回歸鎖定前端取值，共同證明「前端→API 請求體」真實路徑——非另行手動
    構造的請求形狀）。
    """
    from config import settings

    headers = {"X-API-Key": "valid-key-123"}
    base_body = {
        "case_seq": "201",
        "order_code": "14050B",
        "deduction_reason": "超過次數",
    }

    # Test 1：RECORDS_DIR 存在＋record_no → ②醫療必要性為正常半年病史摘要
    records_dir = _write_records_fixture(tmp_path, "P001")
    monkeypatch.setattr(settings, "RECORDS_DIR", str(records_dir))
    resp_ok = client.post(
        "/api/appeal/generate", json={**base_body, "record_no": "P001"}, headers=headers
    )
    assert resp_ok.status_code == 200
    data_ok = resp_ok.get_json()
    assert data_ok["status"] == "success"
    assert data_ok["records_degraded"] is False
    assert data_ok["records_source"] == "ok"
    assert data_ok["records_degraded_reason"] is None
    assert "半年病史" in data_ok["sections"][1]["text"]

    # Test 2：病歷號輸入欄留空（不帶 record_no，RECORDS_DIR 存在）→
    # no_record_no（有來源但未嘗試查詢），②為「病歷缺席」降級文字
    resp_no = client.post("/api/appeal/generate", json=dict(base_body), headers=headers)
    assert resp_no.status_code == 200
    data_no = resp_no.get_json()
    assert data_no["records_degraded"] is True
    assert data_no["records_source"] == "no_record_no"
    assert data_no["records_degraded_reason"] == "請求未提供病歷號"
    assert "病歷缺席" in data_no["sections"][1]["text"]

    # Test 3：病患缺席（RECORDS_DIR 存在但無該病歷號目錄）→ absent（已查詢）
    resp_absent = client.post(
        "/api/appeal/generate",
        json={**base_body, "record_no": "NO_SUCH_PATIENT"},
        headers=headers,
    )
    assert resp_absent.status_code == 200
    data_absent = resp_absent.get_json()
    assert data_absent["records_degraded"] is True
    assert data_absent["records_source"] == "absent"
    assert data_absent["records_degraded_reason"] == "查無此病患病歷檔案"

    # Test 4（回歸）：帶 record_no 但 RECORDS_DIR 不存在 → unconfigured；
    # render_appeal_json 契約既有鍵（sections/word_stats/p1-p9）不受影響
    monkeypatch.setattr(settings, "RECORDS_DIR", str(tmp_path / "no_such_records"))
    resp_unc = client.post(
        "/api/appeal/generate", json={**base_body, "record_no": "P001"}, headers=headers
    )
    assert resp_unc.status_code == 200
    data_unc = resp_unc.get_json()
    assert data_unc["records_degraded"] is True
    assert data_unc["records_source"] == "unconfigured"
    assert data_unc["records_degraded_reason"] == "病歷來源未設定（病歷目錄不存在）"
    # render_appeal_json 標準契約鍵不變
    assert isinstance(data_unc["sections"], list) and len(data_unc["sections"]) >= 1
    for sec in data_unc["sections"]:
        assert {"key", "title", "text", "trimmed"}.issubset(sec)
    assert isinstance(data_unc["word_stats"]["total_chars"], int)
    assert isinstance(data_unc["p8_reason1"], str)
    assert isinstance(data_unc["p9_reason2"], str)
    assert data_unc["status"] == "success"
    assert isinstance(data_unc["rule_found"], bool)
