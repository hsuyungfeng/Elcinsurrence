"""測試 SoapVoice 診間上傳與 EvidenceVault 自動歸檔整合端點 (Phase 24-01)."""

import io
import json
import pytest
from elc_audit_engine.evidence_vault import list_vault_files

KEY = {"X-API-Key": "valid-key-123"}


@pytest.fixture
def app(make_api_app, tmp_path, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    return make_api_app()


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


def test_soapvoice_ingest_json_payload(client):
    payload = {
        "session_id": "test-session-001",
        "patient_name": "王大明",
        "id_card": "A123456789",
        "visit_date": "1120718",
        "icd10_code": "M17.0",
        "order_code": "39004C",
        "soap": {
            "subjective": "雙膝疼痛半年",
            "objective": "Bilateral knee effusion (+)",
            "assessment": "M17.0 退化性膝關節炎",
            "plan": "評估玻尿酸注射或自費治療"
        }
    }
    resp = client.post("/api/his/soapvoice-ingest", json=payload, headers=KEY)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["vault_key"] == "A123456789-2307"
    assert len(data["self_pay_suggestions"]) >= 1
    assert any("PRP" in s["item_code"] for s in data["self_pay_suggestions"])


def test_soapvoice_ingest_multipart_files(client):
    audio_content = b"RIFFFAKEOPUSDATA12345678"
    image_content = b"\x89PNG\r\n\x1a\nFAKESCREENSHOT"
    
    data = {
        "session_id": "test-session-002",
        "patient_name": "李小華",
        "id_card": "B234567890",
        "visit_date": "1120720",
        "icd10_code": "M17.1",
        "soap_json": json.dumps({
            "subjective": "右膝腫脹",
            "assessment": "單側膝關節退化"
        }),
        "audio_file": (io.BytesIO(audio_content), "consultation.opus"),
        "screenshot_file": (io.BytesIO(image_content), "chart_screenshot.png")
    }
    
    resp = client.post("/api/his/soapvoice-ingest", data=data, content_type="multipart/form-data", headers=KEY)
    assert resp.status_code == 201
    res_json = resp.get_json()
    assert res_json["vault_key"] == "B234567890-2307"
    assert len(res_json["vault_files"]) == 2
    
    # 驗證實體佐證金庫中是否已建檔
    vault_key = res_json["vault_key"]
    files = list_vault_files(vault_key)
    assert len(files["audio"]) == 1
    assert files["audio"][0].filename == "consultation.opus"
    assert len(files["images"]) == 1
    assert files["images"][0].filename == "chart_screenshot.png"
