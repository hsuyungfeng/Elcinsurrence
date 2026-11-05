"""Tests for WebBrain NHI Cloud 2.0 integration and Stage 2/3 automation."""

import pytest
from elc_audit_engine.webbrain_bridge import (
    NHICloudRecord,
    NHILabItem,
    NHIMedItem,
    WebBrainClient,
    build_automation_action,
    extract_nhi_cloud_history,
    inject_nhi_history_into_case,
    parse_nhi_cloud_json,
)


@pytest.fixture
def sample_nhi_payload():
    return {
        "nhi_med_history": [
            {
                "visit_date_roc": "1120710",
                "facility_name": "仁愛診所",
                "nhi_drug_code": "AC45123100",
                "drug_name": "Atorvastatin 20mg",
                "days": 28,
            },
            {
                "visit_date_roc": "1120715",
                "facility_name": "博愛醫院",
                "nhi_drug_code": "BC12345678",
                "drug_name": "Metformin 500mg",
                "days": 14,
            },
        ],
        "recent_labs": [
            {"item_name": "HbA1c", "value": "8.4", "unit": "%", "report_date_roc": "1120701"},
            {"item_name": "LDL-C", "value": "172", "unit": "mg/dL", "report_date_roc": "1120701"},
            {"item_name": "eGFR", "value": "62", "unit": "mL/min", "report_date_roc": "1120701"},
        ],
        "duplicate_alerts": ["健保署警示: 降血脂藥品跨院重複領取"],
    }


@pytest.fixture
def app(make_api_app, tmp_path, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    return make_api_app()


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


def test_parse_nhi_cloud_json(sample_nhi_payload):
    record = parse_nhi_cloud_json("A123456789", sample_nhi_payload)
    assert record.patient_id == "A123456789"
    assert len(record.nhi_med_history) == 2
    assert record.nhi_med_history[0].facility_name == "仁愛診所"
    assert record.nhi_med_history[0].nhi_drug_code == "AC45123100"
    assert len(record.recent_labs) == 3
    assert record.recent_labs[0].item_name == "HbA1c"
    assert record.recent_labs[0].value == "8.4"
    assert len(record.duplicate_alerts) == 1


def test_inject_nhi_history_into_case(sample_nhi_payload):
    record = parse_nhi_cloud_json("A123456789", sample_nhi_payload)
    case_data = {
        "patient_name": "測試病患",
        "soap_s": "頭暈，抽血追蹤",
        "soap_o": "BP 130/80 mmHg",
        "orders": [
            {"order_code": "AC45123100", "order_name": "Atorvastatin 20mg"},
        ],
    }

    enhanced = inject_nhi_history_into_case(case_data, record)

    # 1. Labs should be injected into soap_o
    assert "[健保雲端檢驗]" in enhanced["soap_o"]
    assert "HbA1c: 8.4 % (1120701)" in enhanced["soap_o"]
    assert "LDL-C: 172 mg/dL (1120701)" in enhanced["soap_o"]
    assert "BP 130/80 mmHg" in enhanced["soap_o"]

    # 2. Duplicate medication alert should be raised for AC45123100
    warnings = enhanced.get("duplicate_medication_warnings", [])
    assert any("AC45123100" in w for w in warnings)
    assert any("仁愛診所" in w for w in warnings)

    # 3. Double injection idempotency check
    enhanced2 = inject_nhi_history_into_case(enhanced, record)
    assert enhanced2["soap_o"].count("[健保雲端檢驗]") == 1


def test_build_automation_action():
    act2 = build_automation_action(2, "calc_points")
    assert act2["selector"] == "#btn-s-calc-points"
    assert act2["stage"] == 2

    act3 = build_automation_action(3, "gen_appeal")
    assert act3["selector"] == "#btn-a-gen-appeal"
    assert act3["stage"] == 3

    with pytest.raises(ValueError):
        build_automation_action(2, "non_existent_action")


def test_webbrain_mock_extraction(sample_nhi_payload):
    client = WebBrainClient()

    def mock_runner(task, mode, tab_id=None):
        assert mode == "ask"
        return {"status": "completed", "result": sample_nhi_payload}

    client.set_mock_handler(mock_runner)
    record = extract_nhi_cloud_history(client, "B223456789")
    assert record.patient_id == "B223456789"
    assert len(record.recent_labs) == 3


def test_webbrain_nhi_extract_api(app, client, sample_nhi_payload):
    store = app.extensions["elc"].case_store
    created = store.create(
        case_id="case_webbrain_test_01",
        kind="his",
        payload={
            "patient_name": "王大明",
            "id_card": "A123456789",
            "soap_o": "理學檢查正常",
            "orders": [{"order_code": "AC45123100"}],
        },
        actor="doctor_1",
    )

    resp = client.post(
        "/api/his/webbrain/nhi-extract",
        headers={"X-API-Key": "valid-key-123"},
        json={
            "patient_id": "A123456789",
            "case_id": "case_webbrain_test_01",
            "raw_payload": sample_nhi_payload,
        },
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["case_updated"] is True
    enhanced = data["enhanced_case"]
    assert "[健保雲端檢驗]" in enhanced["soap_o"]
    assert len(enhanced["duplicate_medication_warnings"]) > 0


def test_webbrain_action_api(client):
    resp = client.post(
        "/api/his/webbrain/action",
        headers={"X-API-Key": "valid-key-123"},
        json={"stage": 2, "action": "filter_unsupported"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["action_plan"]["selector"] == "#btn-s-filter-unsupported"
