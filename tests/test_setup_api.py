"""Tests for Setup API and Rooms API (Phase 32 Plan 32-13, D2)."""

import json
import pytest

from elc_audit_engine.api.app import create_app


@pytest.fixture
def temp_facility_path(tmp_path, monkeypatch):
    fac_file = tmp_path / "facility.json"
    initial_data = {
        "code": "",
        "name": "",
        "address": "台北市大安區和平東路一段1號",
        "physician_name": "",
        "rooms": [],
    }
    fac_file.write_text(json.dumps(initial_data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("config.settings.FACILITY_CONFIG_PATH", str(fac_file))
    monkeypatch.setenv("ELC_TRUSTED_SUBNETS", "192.168.1.0/24")
    return fac_file


def test_setup_state_needs_setup(temp_facility_path):
    """GET /api/setup/state 在 code 為空時 needs_setup 為 True。"""
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        resp = client.get("/api/setup/state", environ_base={"REMOTE_ADDR": "127.0.0.1"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["needs_setup"] is True
        assert data["write_allowed"] is True
        assert data["write_hint"] == ""
        assert data["facility"]["code"] == ""


def test_setup_state_write_allowed_for_lan(temp_facility_path):
    """D-32-19 已撤回：GET /api/setup/state 在院內非本機時 write_allowed 為 True。"""
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        resp = client.get("/api/setup/state", environ_base={"REMOTE_ADDR": "192.168.1.50"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["write_allowed"] is True
        assert data["write_hint"] == ""


def test_save_setup_validation_errors(temp_facility_path):
    """POST /api/setup 欄位驗證失敗時回 422 與中文錯誤。"""
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        # 1. 院所代碼長度不合、名稱為空、診間為空
        bad_payload = {
            "code": "123",
            "name": "",
            "physician_name": "王醫師",
            "rooms": [],
        }
        resp = client.post("/api/setup", json=bad_payload, environ_base={"REMOTE_ADDR": "127.0.0.1"})
        assert resp.status_code == 422
        data = resp.get_json()
        assert "code" in data["errors"]
        assert "name" in data["errors"]
        assert "rooms" in data["errors"]

        # 2. 診間代號不合法或重複
        bad_rooms = {
            "code": "3501020000",
            "name": "測試診所",
            "physician_name": "王醫師",
            "rooms": [
                {"id": "invalid room id with space!", "name": "第 1 診"},
            ],
        }
        resp2 = client.post("/api/setup", json=bad_rooms, environ_base={"REMOTE_ADDR": "127.0.0.1"})
        assert resp2.status_code == 422
        data2 = resp2.get_json()
        assert "rooms" in data2["errors"]

        # 3. 診間名稱重複
        dup_names = {
            "code": "3501020000",
            "name": "測試診所",
            "rooms": [
                {"id": "r1", "name": "第 1 診"},
                {"id": "r2", "name": "第 1 診"},
            ],
        }
        resp3 = client.post("/api/setup", json=dup_names, environ_base={"REMOTE_ADDR": "127.0.0.1"})
        assert resp3.status_code == 422
        data3 = resp3.get_json()
        assert "重複" in data3["errors"]["rooms"]


def test_save_setup_success_and_preserves_other_keys(temp_facility_path):
    """POST /api/setup 成功儲存，原子寫入且保留既有 address 欄位。"""
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        payload = {
            "code": "3501020000",
            "name": "大安健康診所",
            "physician_name": "林醫師",
            "rooms": [
                {"id": "room-1", "name": "第 1 診間"},
                {"id": "room-2", "name": "第 2 診間"},
            ],
        }
        resp = client.post("/api/setup", json=payload, environ_base={"REMOTE_ADDR": "127.0.0.1"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["facility"]["code"] == "3501020000"

        # 檢查檔案實際內容
        saved = json.loads(temp_facility_path.read_text(encoding="utf-8"))
        assert saved["code"] == "3501020000"
        assert saved["name"] == "大安健康診所"
        assert saved["physician_name"] == "林醫師"
        assert saved["address"] == "台北市大安區和平東路一段1號"  # 保留未被修改欄位
        assert len(saved["rooms"]) == 2

        # 再次檢查 GET /api/setup/state
        state_resp = client.get("/api/setup/state", environ_base={"REMOTE_ADDR": "127.0.0.1"})
        state_data = state_resp.get_json()
        assert state_data["needs_setup"] is False


def test_save_setup_allowed_from_lan(temp_facility_path):
    """D-32-19 已撤回：院內網路的診間電腦可完成初次設定（不限伺服器本機）。"""
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        payload = {
            "code": "3501020000",
            "name": "大安健康診所",
            "rooms": [{"id": "r1", "name": "第 1 診"}],
        }
        resp = client.post("/api/setup", json=payload, environ_base={"REMOTE_ADDR": "192.168.1.100"})
        assert resp.status_code == 200
        state = client.get("/api/setup/state", environ_base={"REMOTE_ADDR": "192.168.1.100"}).get_json()
        assert state["write_allowed"] is True
def test_get_rooms_api(temp_facility_path):
    """GET /api/rooms 回傳診間清單供客戶端下拉使用。"""
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        # 尚未設定時回傳空清單
        r1 = client.get("/api/rooms")
        assert r1.status_code == 200
        assert r1.get_json()["rooms"] == []

        # 寫入診間
        temp_facility_path.write_text(json.dumps({
            "code": "3501020000",
            "name": "診所",
            "rooms": [
                {"id": "r-ped", "name": "小兒科診間"},
                {"id": "r-ent", "name": "耳鼻喉診間"},
            ]
        }, ensure_ascii=False), encoding="utf-8")

        r2 = client.get("/api/rooms")
        assert r2.status_code == 200
        rooms = r2.get_json()["rooms"]
        assert len(rooms) == 2
        assert rooms[0]["id"] == "r-ped"
        assert rooms[1]["name"] == "耳鼻喉診間"


def test_get_setup_html_page():
    """GET /setup 回傳 200 且包含 HTML 內容。"""
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        resp = client.get("/setup")
        assert resp.status_code == 200
        assert "第一次設定" in resp.get_data(as_text=True)
