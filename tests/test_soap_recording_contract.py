from __future__ import annotations

import io
import json
import logging
from pathlib import Path
import pytest

from elc_audit_engine.api.app import create_app
from elc_audit_engine.api.routes.soap_recording import (
    MAX_AUDIO_BYTES,
    parse_soap_txt,
    validate_recording_payload,
)
from elc_audit_engine.case_store import CaseStore
from elc_audit_engine.case_store.soap_draft_states import (
    STATE_QUALITY_FAILED,
    STATE_VALIDATED,
)


@pytest.fixture
def recording_fixture():
    fixture_path = Path(__file__).parent / "fixtures" / "soapvoice_recording_v1.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def app_with_db(tmp_path, monkeypatch):
    db_file = tmp_path / "cases.sqlite3"
    rec_dir = tmp_path / "recordings"
    audit_log_path = tmp_path / "audit" / "access.log"
    monkeypatch.setenv("CASES_DB_PATH", str(db_file))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_log_path))
    monkeypatch.setenv("ELC_API_KEYS", "caller_client:valid_client_key_12345")
    monkeypatch.setenv("ELC_AGENT_KEYS", "agent_win:valid_agent_key_67890")
    monkeypatch.setenv("DISABLE_AUTH", "0")

    from config import settings
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "CASES_DB_PATH", str(db_file))
    monkeypatch.setattr(settings, "AUDIT_LOG_PATH", str(audit_log_path))

    from elc_audit_engine import audit_log
    monkeypatch.setattr(audit_log, "AUDIT_LOG_PATH", str(audit_log_path))

    store = CaseStore(str(db_file))
    app = create_app(
        config={
            "TESTING": True,
            "DISABLE_AUTH": False,
            "ELC_API_KEYS": {"valid_client_key_12345": "caller_client"},
            "ELC_AGENT_KEYS": {"valid_agent_key_67890": "agent_win"},
            "ELC_ALLOWED_HOSTS": ["localhost", "127.0.0.1", "testserver"],
            "DATA_DIR": str(tmp_path),
        },
        case_store=store,
        migrate_legacy=False,
    )
    return app


# --- Task 1: Contract Fixture & Pure Validator Tests ---

def test_parse_soap_txt_success():
    raw = (
        "[S]\nPatient feels pain in right ankle.\n"
        "[O]\nSwelling and mild bruising.\n"
        "[A]\nAnkle sprain.\n"
        "[P]\nRICE protocol and painkiller prescribed.\n"
    )
    soap, errs = parse_soap_txt(raw)
    assert not errs
    assert soap["s"] == "Patient feels pain in right ankle."
    assert soap["o"] == "Swelling and mild bruising."
    assert soap["a"] == "Ankle sprain."
    assert soap["p"] == "RICE protocol and painkiller prescribed."


def test_parse_soap_txt_missing_section_rejected():
    # Missing [P]
    raw = "[S] Headache [O] Normal BP [A] Tension headache"
    soap, errs = parse_soap_txt(raw)
    assert len(errs) > 0
    assert "[P]" in errs[0]


def test_parse_soap_txt_empty_section_rejected():
    raw = "[S] Headache [O]  [A] Tension headache [P] Rest"
    soap, errs = parse_soap_txt(raw)
    assert len(errs) > 0
    assert "不得為空" in errs[0]


def test_validator_fixture_valid(recording_fixture):
    """Test 1: fixture 內的合法樣本通過 validate_recording_payload，回傳 normalized 且無 errors"""
    file_meta = {
        "filename": "sample_audio.wav",
        "content_type": "audio/wav",
        "size_bytes": 1024 * 1024,
    }
    normalized, errors = validate_recording_payload(recording_fixture, file_meta)
    assert not errors
    assert normalized["session_id"] == recording_fixture["session_id"]
    assert normalized["soap"] == recording_fixture["soap"]


def test_validator_missing_session_id(recording_fixture):
    """Test 2: 缺少 session_id 回傳 error"""
    payload = dict(recording_fixture)
    payload.pop("session_id")
    file_meta = {"filename": "a.wav", "content_type": "audio/wav", "size_bytes": 100}
    _, errors = validate_recording_payload(payload, file_meta)
    assert any("session_id" in e for e in errors)


def test_validator_invalid_session_id_path_traversal(recording_fixture):
    """Test 3: session_id 含 '/' 或 '..' 回傳 error"""
    payload = dict(recording_fixture)
    payload["session_id"] = "../evil_id"
    file_meta = {"filename": "a.wav", "content_type": "audio/wav", "size_bytes": 100}
    _, errors = validate_recording_payload(payload, file_meta)
    assert any("session_id" in e for e in errors)


def test_validator_missing_soap_key(recording_fixture):
    """Test 4: soap 缺少 p 鍵回傳 error"""
    payload = dict(recording_fixture)
    payload.pop("soap_txt", None)
    payload["soap"] = {"s": "S text", "o": "O text", "a": "A text"}  # Missing 'p'
    file_meta = {"filename": "a.wav", "content_type": "audio/wav", "size_bytes": 100}
    _, errors = validate_recording_payload(payload, file_meta)
    assert any("缺少必要鍵" in e for e in errors)


def test_validator_caller_field_forbidden(recording_fixture):
    """Test 5: 客戶端提供 caller 欄位回傳 error（不默默忽略）"""
    payload = dict(recording_fixture)
    payload["caller"] = "spoofed_caller"
    file_meta = {"filename": "a.wav", "content_type": "audio/wav", "size_bytes": 100}
    _, errors = validate_recording_payload(payload, file_meta)
    assert any("caller" in e for e in errors)


def test_validator_audio_oversize(recording_fixture):
    """Test 6: 音檔超過 25 MB 回傳 error"""
    file_meta = {
        "filename": "huge.wav",
        "content_type": "audio/wav",
        "size_bytes": MAX_AUDIO_BYTES + 1,
    }
    _, errors = validate_recording_payload(recording_fixture, file_meta)
    assert any("超過 25 MB" in e for e in errors)


def test_validator_invalid_content_type(recording_fixture):
    """Test 7: 非 audio/wav content-type 回傳 error"""
    file_meta = {
        "filename": "audio.mp3",
        "content_type": "audio/mpeg",
        "size_bytes": 1000,
    }
    _, errors = validate_recording_payload(recording_fixture, file_meta)
    assert any("音檔格式錯誤" in e for e in errors)


def test_validator_invalid_visit_date(recording_fixture):
    """Test 8: visit_date 格式錯誤回傳 error"""
    payload = dict(recording_fixture)
    payload["visit_date"] = "2026/11/09"  # invalid format
    file_meta = {"filename": "a.wav", "content_type": "audio/wav", "size_bytes": 100}
    _, errors = validate_recording_payload(payload, file_meta)
    assert any("visit_date" in e for e in errors)


# --- Task 2: Endpoint Ingestion, Idempotency, Auth & Logging Tests ---

def test_endpoint_successful_ingestion_and_idempotency(app_with_db, recording_fixture):
    """Test 1 & 2: 合法 POST 回傳 201；相同 session_id 重送回傳 200且 draft_id 相同"""
    client = app_with_db.test_client()

    data = {
        "session_id": "sess_test_1001",
        "visit_date": "2026-11-09",
        "patient_ref": "PAT_001",
        "soap_txt": recording_fixture["soap_txt"],
        "audio": (io.BytesIO(b"RIFF....WAVEfmt "), "recording.wav", "audio/wav"),
    }

    # First request with caller API key
    headers = {"X-API-Key": "valid_client_key_12345"}
    resp1 = client.post("/api/soap/recordings", data=data, headers=headers)
    assert resp1.status_code == 201
    res1_json = resp1.get_json()
    assert res1_json["status"] == "success"
    assert res1_json["idempotent"] is False
    draft_id1 = res1_json["draft_id"]
    assert draft_id1 is not None

    # Second request with same session_id (idempotent)
    data2 = {
        "session_id": "sess_test_1001",
        "visit_date": "2026-11-09",
        "patient_ref": "PAT_001",
        "soap_txt": recording_fixture["soap_txt"],
        "audio": (io.BytesIO(b"RIFF....WAVEfmt "), "recording.wav", "audio/wav"),
    }
    resp2 = client.post("/api/soap/recordings", data=data2, headers=headers)
    assert resp2.status_code == 200
    res2_json = resp2.get_json()
    assert res2_json["status"] == "success"
    assert res2_json["idempotent"] is True
    assert res2_json["draft_id"] == draft_id1


def test_endpoint_agent_key_rejected_with_403(app_with_db, recording_fixture):
    """Test 3: Agent 金鑰 POST 回傳 403"""
    client = app_with_db.test_client()
    data = {
        "session_id": "sess_agent_try",
        "visit_date": "2026-11-09",
        "patient_ref": "PAT_002",
        "soap_txt": recording_fixture["soap_txt"],
        "audio": (io.BytesIO(b"RIFF....WAVEfmt "), "recording.wav", "audio/wav"),
    }
    headers = {"X-API-Key": "valid_agent_key_67890"}
    resp = client.post("/api/soap/recordings", data=data, headers=headers)
    assert resp.status_code == 403
    assert "Agent 金鑰權限不足" in resp.get_json()["message"]


def test_endpoint_o3_private_ip_exempt_public_ip_requires_key(app_with_db, recording_fixture):
    """Test 4: 私有 IP 免 key，公網 IP 需 key（O3 決策）"""
    client = app_with_db.test_client()

    # Case A: Private IP (127.0.0.1) without key -> Allowed (201)
    data_lan = {
        "session_id": "sess_lan_ok",
        "visit_date": "2026-11-09",
        "patient_ref": "PAT_LAN",
        "soap_txt": recording_fixture["soap_txt"],
        "audio": (io.BytesIO(b"RIFF....WAVEfmt "), "recording.wav", "audio/wav"),
    }
    resp_lan = client.post(
        "/api/soap/recordings",
        data=data_lan,
        environ_base={"REMOTE_ADDR": "192.168.1.100"},
    )
    assert resp_lan.status_code == 201

    # Case B: Public IP (8.8.8.8) without key -> Rejected (401)
    data_wan = {
        "session_id": "sess_wan_fail",
        "visit_date": "2026-11-09",
        "patient_ref": "PAT_WAN",
        "soap_txt": recording_fixture["soap_txt"],
        "audio": (io.BytesIO(b"RIFF....WAVEfmt "), "recording.wav", "audio/wav"),
    }
    resp_wan = client.post(
        "/api/soap/recordings",
        data=data_wan,
        environ_base={"REMOTE_ADDR": "8.8.8.8"},
    )
    assert resp_wan.status_code == 401


def test_endpoint_persists_audio_file(app_with_db, recording_fixture, tmp_path):
    """Test 5: 音檔寫入 <data_dir>/recordings/<session_id>.wav"""
    client = app_with_db.test_client()
    session_id = "sess_audio_check"
    audio_content = b"RIFF1234WAVEfmt 16bit-mono-pcm"

    data = {
        "session_id": session_id,
        "visit_date": "2026-11-09",
        "patient_ref": "PAT_AUDIO",
        "soap_txt": recording_fixture["soap_txt"],
        "audio": (io.BytesIO(audio_content), "user_provided_name.wav", "audio/wav"),
    }
    resp = client.post("/api/soap/recordings", data=data)
    assert resp.status_code == 201

    expected_path = tmp_path / "recordings" / f"{session_id}.wav"
    assert expected_path.exists()
    assert expected_path.read_bytes() == audio_content


def test_endpoint_draft_state_validated_not_approved(app_with_db, recording_fixture):
    """Test 6: 草稿 state 為 validated 或 quality_failed，絕不為 approved"""
    client = app_with_db.test_client()
    data = {
        "session_id": "sess_state_check",
        "visit_date": "2026-11-09",
        "patient_ref": "PAT_STATE",
        "soap_txt": recording_fixture["soap_txt"],
        "audio": (io.BytesIO(b"RIFF....WAVEfmt "), "recording.wav", "audio/wav"),
    }
    resp = client.post("/api/soap/recordings", data=data)
    assert resp.status_code == 201
    state = resp.get_json()["state"]
    assert state in (STATE_VALIDATED, STATE_QUALITY_FAILED)
    assert state != "approved"


def test_endpoint_phi_safe_logging(app_with_db, recording_fixture, caplog):
    """Test 7: caplog 掃描，日誌中不含 soap 任一欄位的文字"""
    caplog.set_level(logging.DEBUG)
    client = app_with_db.test_client()

    secret_symptom = "SECRET_SYMPTOM_FOR_LOG_CHECK_42"
    soap_txt = (
        f"[S]\n{secret_symptom}\n"
        "[O]\nPhysical exam unremarkable.\n"
        "[A]\nCommon cold.\n"
        "[P]\nRest and fluids.\n"
    )
    data = {
        "session_id": "sess_log_check",
        "visit_date": "2026-11-09",
        "patient_ref": "PAT_SECRET",
        "soap_txt": soap_txt,
        "audio": (io.BytesIO(b"RIFF....WAVEfmt "), "recording.wav", "audio/wav"),
    }
    resp = client.post("/api/soap/recordings", data=data)
    assert resp.status_code == 201

    for record in caplog.records:
        assert secret_symptom not in record.getMessage()


# --- Task 3: Blueprint Registration & Boundary Tests ---

def test_endpoint_url_map_registered(app_with_db):
    """Test 1: 應用程式啟動後 url_map 含 /api/soap/recordings POST"""
    rules = [
        r.rule for r in app_with_db.url_map.iter_rules()
        if "POST" in r.methods
    ]
    assert "/api/soap/recordings" in rules


def test_endpoint_audio_write_failure_returns_500_and_no_orphan(app_with_db, recording_fixture, monkeypatch, tmp_path):
    """Test 2 & 3: 音檔寫入失敗時回傳 500 且不留孤兒檔案、不建立草稿"""
    client = app_with_db.test_client()

    def fake_save(self, dst, *args, **kwargs):
        raise OSError("Disk full")

    monkeypatch.setattr("werkzeug.datastructures.FileStorage.save", fake_save)

    data = {
        "session_id": "sess_disk_fail",
        "visit_date": "2026-11-09",
        "patient_ref": "PAT_DISK_FAIL",
        "soap_txt": recording_fixture["soap_txt"],
        "audio": (io.BytesIO(b"RIFF....WAVEfmt "), "recording.wav", "audio/wav"),
    }
    resp = client.post("/api/soap/recordings", data=data)
    assert resp.status_code == 500

    rec_file = tmp_path / "recordings" / "sess_disk_fail.wav"
    assert not rec_file.exists()
