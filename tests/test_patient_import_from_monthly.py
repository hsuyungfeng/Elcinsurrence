"""測試當月申報跨模組載入、依病患資訊鍵入加入案件、以及院所設定必填驗證。"""

import json
import pytest

from config import settings
from elc_audit_engine.case_store.store import CaseStore
from elc_audit_engine.monthly_patient_service import (
    add_appeal_case_by_patient,
    add_sampling_case_by_patient,
    find_monthly_patient_cases,
    import_monthly_to_appeal,
    import_monthly_to_sampling,
    normalize_date_variants,
)


@pytest.fixture
def app(make_api_app):
    return make_api_app()


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


@pytest.fixture
def store(tmp_path):
    db_file = tmp_path / "test_cases.sqlite3"
    return CaseStore(str(db_file))


def test_date_variants_normalization():
    """驗證民國年與西元年生日正規化轉換。"""
    roc_variants = normalize_date_variants("0761224")
    assert "0761224" in roc_variants
    assert "19871224" in roc_variants

    ce_variants = normalize_date_variants("1987-12-24")
    assert "0761224" in ce_variants
    assert "19871224" in ce_variants


def test_facility_web_save_requires_code_name_email(client, tmp_path, monkeypatch):
    """驗證 Web 儲存院所設定時，機構代碼、院所名稱、Mail Address 皆為必填項。"""
    cfg_file = tmp_path / "facility.json"
    cfg_file.write_text(json.dumps({"code": "01015C", "name": "原診所"}), encoding="utf-8")
    monkeypatch.setattr(settings, "FACILITY_CONFIG_PATH", str(cfg_file))

    # 1. 缺少 email
    res = client.post("/api/facility", json={"source": "web", "code": "3503250461", "name": "新明診所", "email": ""})
    assert res.status_code == 400
    assert "Mail Address" in res.get_json()["message"]
    assert "必填欄位" in res.get_json()["message"]

    # 2. 缺少 code
    res = client.post("/api/facility", json={"source": "web", "code": "", "name": "新明診所", "email": "test@clinic.com"})
    assert res.status_code == 400
    assert "醫事機構代碼" in res.get_json()["message"]
    assert "必填欄位" in res.get_json()["message"]

    # 3. 缺少 name
    res = client.post("/api/facility", json={"source": "web", "code": "3503250461", "name": "", "email": "test@clinic.com"})
    assert res.status_code == 400
    assert "醫療院所名稱" in res.get_json()["message"]
    assert "必填欄位" in res.get_json()["message"]

    # 4. 三者皆齊全時儲存成功
    res = client.post(
        "/api/facility",
        json={"source": "web", "code": "3503250461", "name": "新明診所", "email": "test@clinic.com", "address": "台北市中正區1號"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["facility"]["code"] == "3503250461"
    assert data["facility"]["name"] == "新明診所"
    assert data["facility"]["email"] == "test@clinic.com"


def _seed_monthly_case(store: CaseStore, case_id: str, payload: dict):
    store.create(
        case_id=case_id,
        kind="monthly",
        case_seq=payload.get("case_seq", "1"),
        payload=payload,
    )


def test_find_monthly_patient_and_import(store):
    """驗證當月申報案件檢索與一鍵帶入抽審與申復。"""
    batch = "MONTHLY-202307"
    p1 = {
        "batch": batch,
        "case_seq": "1",
        "record_no": "M220518024",
        "id_card": "M220518024",
        "patient_name": "王大明",
        "birth_date": "0761224",
        "visit_date": "1120718",
        "clinic": "01",
        "primary_diagnosis": "E119",
        "total_points": "1500",
        "orders": [
            {"p4": "14050B", "p12": "1200", "p13": "1"},
            {"p4": "00110C", "p12": "300", "p13": "2"},
        ],
    }
    p2 = {
        "batch": batch,
        "case_seq": "2",
        "record_no": "A123456789",
        "id_card": "A123456789",
        "patient_name": "李小華",
        "birth_date": "0800510",
        "visit_date": "1120719",
        "clinic": "02",
        "primary_diagnosis": "I10",
        "total_points": "800",
        "orders": [
            {"p4": "00110C", "p12": "800", "p13": "1"},
        ],
    }

    _seed_monthly_case(store, "MON-001", p1)
    _seed_monthly_case(store, "MON-002", p2)

    # 1. 依身分證與西元生日檢索
    found = find_monthly_patient_cases(store, id_card="M220518024", birth_date="1987-12-24")
    assert len(found) == 1
    assert found[0]["patient_name"] == "王大明"

    # 2. 依姓名檢索
    found_by_name = find_monthly_patient_cases(store, patient_name="李小華")
    assert len(found_by_name) == 1
    assert found_by_name[0]["record_no"] == "A123456789"

    # 3. 測試一鍵匯入當月申報至抽審
    sampling_res = import_monthly_to_sampling(store, batch_id=batch)
    assert sampling_res["status"] == "success"
    assert sampling_res["imported"] == 2
    assert store.count(kind="sampling") == 2

    # 4. 測試一鍵匯入當月申報至申復
    appeal_res = import_monthly_to_appeal(store, batch_id=batch)
    assert appeal_res["status"] == "success"
    assert appeal_res["imported"] == 2
    assert store.count(kind="appeal") == 2


def test_add_case_by_patient_matched_and_manual(store):
    """驗證依病患鍵入：相符時自動帶入申報醫令，查無相符時建立手動案件。"""
    batch = "MONTHLY-202307"
    p1 = {
        "batch": batch,
        "case_seq": "10",
        "record_no": "F123456789",
        "id_card": "F123456789",
        "patient_name": "陳阿土",
        "birth_date": "0650101",
        "visit_date": "1120720",
        "clinic": "01",
        "primary_diagnosis": "M545",
        "total_points": "2000",
        "orders": [{"p4": "34001B", "p12": "2000", "p13": "1"}],
    }
    _seed_monthly_case(store, "MON-100", p1)

    # 1. 相符案件加入抽審
    res_s1 = add_sampling_case_by_patient(
        store, id_card="F123456789", birth_date="0650101", patient_name="陳阿土"
    )
    assert res_s1["status"] == "success"
    assert res_s1["matched_monthly"] is True
    assert res_s1["cases"][0]["target_order_code"] == "34001B"

    # 2. 相符案件加入申復
    res_a1 = add_appeal_case_by_patient(
        store, id_card="F123456789", birth_date="0650101", patient_name="陳阿土"
    )
    assert res_a1["status"] == "success"
    assert res_a1["matched_monthly"] is True
    assert res_a1["cases"][0]["order_code"] == "34001B"

    # 3. 查無案件時手動加入抽審
    res_s2 = add_sampling_case_by_patient(
        store, id_card="Z999999999", birth_date="0900101", patient_name="張無忌"
    )
    assert res_s2["status"] == "success"
    assert res_s2["matched_monthly"] is False
    assert res_s2["cases"][0]["record_no"] == "Z999999999"

    # 4. 查無案件時手動加入申復
    res_a2 = add_appeal_case_by_patient(
        store, id_card="Z999999999", birth_date="0900101", patient_name="張無忌"
    )
    assert res_a2["status"] == "success"
    assert res_a2["matched_monthly"] is False
    assert res_a2["cases"][0]["record_no"] == "Z999999999"


def test_api_endpoints_for_monthly_import_and_patient_add(make_api_app, tmp_path, monkeypatch):
    """測試 HTTP 端點：一鍵載入當月申報與依病患鍵入加入案件。"""
    db_file = tmp_path / "test_api_cases.sqlite3"
    api_store = CaseStore(str(db_file))

    # 模擬機構代碼
    cfg_file = tmp_path / "facility.json"
    cfg_file.write_text(json.dumps({"code": "01015C", "name": "測試診所"}), encoding="utf-8")
    monkeypatch.setattr(settings, "FACILITY_CONFIG_PATH", str(cfg_file))
    headers = {"X-API-Key": "01015C"}

    test_app = make_api_app(case_store=api_store)
    client = test_app.test_client()

    batch = "MONTHLY-202307"
    p1 = {
        "batch": batch,
        "case_seq": "5",
        "record_no": "B123456789",
        "id_card": "B123456789",
        "patient_name": "周伯通",
        "birth_date": "0700101",
        "visit_date": "1120721",
        "clinic": "01",
        "primary_diagnosis": "M545",
        "total_points": "1200",
        "orders": [{"p4": "14050B", "p12": "1200", "p13": "1"}],
    }
    _seed_monthly_case(api_store, "MON-200", p1)

    # 1. 抽審：一鍵自當月申報載入
    res = client.post("/api/sampling/import-from-monthly", json={"batch": batch}, headers=headers)
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["imported"] == 1

    # 2. 抽審：依病患鍵入加入
    res = client.post(
        "/api/sampling/cases/add-by-patient",
        json={"id_card": "B123456789", "patient_name": "周伯通"},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["matched_monthly"] is True

    # 3. 申復：一鍵自當月申報載入
    res = client.post("/api/appeal/import-from-monthly", json={"batch": batch}, headers=headers)
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["imported"] == 1

    # 4. 申復：依病患鍵入加入（查無資料時手動建立）
    res = client.post(
        "/api/appeal/cases/add-by-patient",
        json={"id_card": "X999999999", "patient_name": "楊過"},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["matched_monthly"] is False
    assert data["cases"][0]["record_no"] == "X999999999"
