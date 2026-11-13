"""Phase 31 Plan 05 Task 2: 循環管理 API 整合測試 (POST, GET, stop, abandon, auth, audit)."""

from __future__ import annotations


from elc_audit_engine.cycles.states import (
    STATE_ABANDONED,
    STATE_AWAITING_DRAFT,
    STATE_CONFIRMED,
    STATE_RECORDING,
)
from elc_audit_engine.cycles.store import cycle_dir, transition_cycle
from tests.phase31_support import phase31_app, phase31_client  # noqa: F401

KEY = {"X-API-Key": "valid-key-123"}
AGENT_KEY = {"X-API-Key": "agent-key-1"}

CMD_1 = "11111111111111111111111111111111"
CMD_2 = "22222222222222222222222222222222"
CMD_STOP_1 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
CMD_STOP_2 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
MACHINE_1 = "00000000-0000-4000-8000-000000000001"
MACHINE_2 = "00000000-0000-4000-8000-000000000002"


def test_create_cycle_success(phase31_client):
    """Test 1: POST /api/cycles 建立新循環，欄位符合契約且無 PHI。"""
    res = phase31_client.post(
        "/api/cycles",
        json={"command_id": CMD_1, "machine_id": MACHINE_1, "room_id": "診間1"},
        headers=KEY,
    )
    assert res.status_code == 201
    body = res.get_json()
    assert body["status"] == "success"
    c = body["cycle"]
    assert c["state"] == STATE_RECORDING
    assert c["machine_id"] == MACHINE_1
    assert c["room_id"] == "診間1"
    assert c["chunks_received"] == 0
    assert c["upload_complete"] is False

    # 確保絕無病歷與 SOAP 鍵
    for forbidden in ("soap", "transcript", "patient", "patient_name", "patient_ref"):
        assert forbidden not in c


def test_create_cycle_idempotent(phase31_client):
    """Test 2: 同 command_id 重送 → 200，同一 cycle_id。"""
    res1 = phase31_client.post(
        "/api/cycles",
        json={"command_id": CMD_1, "machine_id": MACHINE_1},
        headers=KEY,
    )
    assert res1.status_code == 201
    c1 = res1.get_json()["cycle"]

    res2 = phase31_client.post(
        "/api/cycles",
        json={"command_id": CMD_1, "machine_id": MACHINE_1},
        headers=KEY,
    )
    assert res2.status_code == 200
    c2 = res2.get_json()["cycle"]
    assert c1["cycle_id"] == c2["cycle_id"]


def test_create_cycle_active_exists_conflict(phase31_client):
    """Test 3: 同 machine_id 不同 command_id → 409，回應含 active_cycle_id。"""
    res1 = phase31_client.post(
        "/api/cycles",
        json={"command_id": CMD_1, "machine_id": MACHINE_1},
        headers=KEY,
    )
    assert res1.status_code == 201
    c1 = res1.get_json()["cycle"]

    res2 = phase31_client.post(
        "/api/cycles",
        json={"command_id": CMD_2, "machine_id": MACHINE_1},
        headers=KEY,
    )
    assert res2.status_code == 409
    body = res2.get_json()
    assert body["error"] == "active_cycle_exists"
    assert body["active_cycle_id"] == c1["cycle_id"]


def test_get_cycles_endpoints(phase31_client):
    """Test 4: GET /api/cycles/{id} → 200；GET /api/cycles?machine_id= → 回未終結循環或 null。"""
    res1 = phase31_client.post(
        "/api/cycles",
        json={"command_id": CMD_1, "machine_id": MACHINE_1},
        headers=KEY,
    )
    cid = res1.get_json()["cycle"]["cycle_id"]

    # 依 cycle_id 查詢
    res_by_id = phase31_client.get(f"/api/cycles/{cid}", headers=KEY)
    assert res_by_id.status_code == 200
    assert res_by_id.get_json()["cycle"]["cycle_id"] == cid

    # 依 machine_id 查詢
    res_by_m = phase31_client.get(f"/api/cycles?machine_id={MACHINE_1}", headers=KEY)
    assert res_by_m.status_code == 200
    assert res_by_m.get_json()["cycle"]["cycle_id"] == cid

    # 查無未終結循環之 machine_id
    res_m2 = phase31_client.get(f"/api/cycles?machine_id={MACHINE_2}", headers=KEY)
    assert res_m2.status_code == 200
    assert res_m2.get_json()["cycle"] is None


def test_stop_cycle_recording(phase31_client):
    """Test 5: POST /api/cycles/{id}/stop → AWAITING_DRAFT；重送冪等；不同 command_id 重試 409。"""
    res_init = phase31_client.post(
        "/api/cycles",
        json={"command_id": CMD_1, "machine_id": MACHINE_1},
        headers=KEY,
    )
    cid = res_init.get_json()["cycle"]["cycle_id"]

    # 正常停止錄音
    res_stop1 = phase31_client.post(
        f"/api/cycles/{cid}/stop",
        json={"command_id": CMD_STOP_1},
        headers=KEY,
    )
    assert res_stop1.status_code == 200
    assert res_stop1.get_json()["cycle"]["state"] == STATE_AWAITING_DRAFT

    # 同一 stop command_id 重送 → 200
    res_stop_idem = phase31_client.post(
        f"/api/cycles/{cid}/stop",
        json={"command_id": CMD_STOP_1},
        headers=KEY,
    )
    assert res_stop_idem.status_code == 200

    # 不同的 command_id 嘗試再次停止已停止的循環 → 409
    res_stop_diff = phase31_client.post(
        f"/api/cycles/{cid}/stop",
        json={"command_id": CMD_STOP_2},
        headers=KEY,
    )
    assert res_stop_diff.status_code == 409


def test_abandon_cycle_flow(phase31_app, phase31_client):
    """Test 6: POST /api/cycles/{id}/abandon；放棄後可建新循環；CONFIRMED 狀態不可 abandon。"""
    store = phase31_app.case_store
    res_init = phase31_client.post(
        "/api/cycles",
        json={"command_id": CMD_1, "machine_id": MACHINE_1},
        headers=KEY,
    )
    cid = res_init.get_json()["cycle"]["cycle_id"]

    # 放棄循環
    res_abandon = phase31_client.post(
        f"/api/cycles/{cid}/abandon",
        json={"reason_code": "start_failed"},
        headers=KEY,
    )
    assert res_abandon.status_code == 200
    assert res_abandon.get_json()["cycle"]["state"] == STATE_ABANDONED

    # 放棄後同機可建立新循環
    res_new = phase31_client.post(
        "/api/cycles",
        json={"command_id": CMD_2, "machine_id": MACHINE_1},
        headers=KEY,
    )
    assert res_new.status_code == 201

    # 佈置為 CONFIRMED 狀態
    cid_new = res_new.get_json()["cycle"]["cycle_id"]
    transition_cycle(store, cid_new, STATE_AWAITING_DRAFT)
    from elc_audit_engine.cycles.states import STATE_AWAITING_CONFIRM
    transition_cycle(store, cid_new, STATE_AWAITING_CONFIRM)
    transition_cycle(store, cid_new, STATE_CONFIRMED)

    # 於 CONFIRMED 狀態呼叫 abandon 應回 409
    res_abandon_confirmed = phase31_client.post(
        f"/api/cycles/{cid_new}/abandon",
        json={"reason_code": "test"},
        headers=KEY,
    )
    assert res_abandon_confirmed.status_code == 409


def test_auth_and_format_validation(phase31_client):
    """Test 7: 無 key 401；Agent 金鑰 403；錯誤格式 422。"""
    # 1. 無 key → 401
    assert phase31_client.post("/api/cycles", json={}).status_code == 401
    assert phase31_client.get("/api/cycles").status_code == 401

    # 2. Agent 金鑰 → 403 (不在 AGENT_ALLOWED_ENDPOINTS)
    res_agent = phase31_client.post(
        "/api/cycles",
        json={"command_id": CMD_1, "machine_id": MACHINE_1},
        headers=AGENT_KEY,
    )
    assert res_agent.status_code == 403

    # 3. 欄位格式錯誤 → 422
    # 錯誤的 command_id
    res_bad_cmd = phase31_client.post(
        "/api/cycles",
        json={"command_id": "not-hex-32", "machine_id": MACHINE_1},
        headers=KEY,
    )
    assert res_bad_cmd.status_code == 422

    # 錯誤的 machine_id
    res_bad_m = phase31_client.post(
        "/api/cycles",
        json={"command_id": CMD_1, "machine_id": "bad machine id with spaces!"},
        headers=KEY,
    )
    assert res_bad_m.status_code == 422

    # 錯誤的 room_id (過長或特殊字元)
    res_bad_room = phase31_client.post(
        "/api/cycles",
        json={"command_id": CMD_1, "machine_id": MACHINE_1, "room_id": "a" * 35},
        headers=KEY,
    )
    assert res_bad_room.status_code == 422


def test_cycle_events_logged_and_files_not_deleted(phase31_app, phase31_client, tmp_path):
    """Test 8: cycle_events 記錄轉換且 abandon 絕對不刪除磁碟檔案 (D-31-29)。"""
    store = phase31_app.case_store
    res = phase31_client.post(
        "/api/cycles",
        json={"command_id": CMD_1, "machine_id": MACHINE_1},
        headers=KEY,
    )
    cid = res.get_json()["cycle"]["cycle_id"]

    # 在 cycles/{cid} 建立測試檔案
    cdir = cycle_dir(cid)
    cdir.mkdir(parents=True, exist_ok=True)
    sample_file = cdir / "audio.pcm"
    sample_file.write_bytes(b"test audio content")
    assert sample_file.exists()

    # 停止錄音再放棄
    phase31_client.post(f"/api/cycles/{cid}/stop", json={"command_id": CMD_STOP_1}, headers=KEY)
    phase31_client.post(f"/api/cycles/{cid}/abandon", json={"reason_code": "cancel"}, headers=KEY)

    # 驗證檔案依然存在，絕無刪除
    assert sample_file.exists()

    # 驗證 cycle_events 表紀錄
    conn = store._connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT from_state, to_state, reason_code FROM cycle_events WHERE cycle_id = ? ORDER BY id ASC", (cid,))
        events = cur.fetchall()
        assert len(events) == 3
        assert events[0]["from_state"] is None and events[0]["to_state"] == "RECORDING"
        assert events[1]["from_state"] == "RECORDING" and events[1]["to_state"] == "AWAITING_DRAFT"
        assert events[2]["from_state"] == "AWAITING_DRAFT" and events[2]["to_state"] == "ABANDONED"
        assert events[2]["reason_code"] == "cancel"
    finally:
        conn.close()
