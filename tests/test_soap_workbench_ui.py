"""Unit tests for Phase 27: SOAP Workbench and Forensic Vault UI APIs.

Tests:
1. GET /api/soap/live-session: Nurse live recording capsule, waveform, transcript.
2. POST /api/soap/search-patient: Query encounters by ID card or birth date.
3. GET /api/soap/cases/<case_id>/bundle: Get encounter SOAP and vault files.
4. GET /api/soap/cases/<case_id>/export-forensic-zip: Export court-ready evidence zip with SHA256 checksums.
"""

import io
import json
import zipfile
import pytest
from elc_audit_engine.evidence_vault import list_vault_files, store_single_file

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


def test_soap_live_session_api(client):
    resp = client.get("/api/soap/live-session", headers=KEY)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["is_recording"] is True
    assert "transcript_ticker" in data
    assert len(data["waveform_bars"]) == 12
    assert data["patient_name"] == "陳美玲"
    assert data["id_card"] == "F229871234"


def test_soap_search_patient_api(client):
    # 1. Search by ID card
    resp = client.post("/api/soap/search-patient", json={"id_card": "A123456789"}, headers=KEY)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert len(data["encounters"]) >= 1
    enc = data["encounters"][0]
    assert "soap" in enc
    assert enc["soap"]["s"] != ""
    assert "vault_files" in enc

    # 2. Search by birth date
    resp2 = client.post("/api/soap/search-patient", json={"birth_date": "1958-03-12"}, headers=KEY)
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2["status"] == "success"
    assert len(data2["encounters"]) >= 1

    # 3. Missing query params
    resp3 = client.post("/api/soap/search-patient", json={}, headers=KEY)
    assert resp3.status_code == 400


def test_soap_case_bundle_api(client):
    resp = client.get("/api/soap/cases/A123456789-202611-001/bundle", headers=KEY)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["case_id"] == "A123456789-202611-001"
    assert "soap" in data
    assert "vault_files" in data


def test_soap_export_forensic_zip_api(client, tmp_path):
    # Ingest a sample audio into evidence vault
    store_single_file(
        vault_key="A123456789-2611",
        filename="consult_rec_1120718.wav",
        data=b"RIFFdummy_audio_bytes_for_forensic_evidence_test",
    )

    resp = client.get("/api/soap/cases/A123456789-202611-001/export-forensic-zip", headers=KEY)
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "application/zip"
    assert "A123456789" in resp.headers["Content-Disposition"]

    # Verify zip content
    zip_buf = io.BytesIO(resp.data)
    with zipfile.ZipFile(zip_buf, "r") as zf:
        namelist = zf.namelist()
        assert "SOAP_RECORD.txt" in namelist
        assert "SOAP_RECORD.json" in namelist
        assert "SHA256_CHECKSUM.txt" in namelist
        assert "AUDIT_TRAIL.json" in namelist

        # Check SOAP_RECORD.txt contents
        soap_txt = zf.read("SOAP_RECORD.txt").decode("utf-8")
        assert "A123456789" in soap_txt
        assert "【S - 主觀主訴】" in soap_txt

        # Check SHA256_CHECKSUM.txt
        checksums = zf.read("SHA256_CHECKSUM.txt").decode("utf-8")
        assert "SOAP_RECORD.txt" in checksums
        assert "SOAP_RECORD.json" in checksums

        # Check AUDIT_TRAIL.json
        audit_trail = json.loads(zf.read("AUDIT_TRAIL.json").decode("utf-8"))
        assert audit_trail["case_id"] == "A123456789-202611-001"
        assert audit_trail["legal_purpose"] == "Court & NHI Evidence Archive"
