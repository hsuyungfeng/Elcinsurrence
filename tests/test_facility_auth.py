"""測試機構代碼作為授權金鑰、院所設定檔存取與更新、以及停用 Email 之安全政策。"""

import json
import pytest

from config import settings
from elc_audit_engine import auth


def test_save_facility_config(tmp_path, monkeypatch):
    """測試 save_facility_config 正確更新欄位並保留舊設定。"""
    cfg_file = tmp_path / "facility.json"
    cfg_file.write_text(json.dumps({"code": "01015C", "name": "原始診所", "address": "原地址"}), encoding="utf-8")
    monkeypatch.setattr(settings, "FACILITY_CONFIG_PATH", str(cfg_file))

    updated = settings.save_facility_config({"address": "新地址123號", "physician_name": "王醫師"})
    assert updated["code"] == "01015C"
    assert updated["name"] == "原始診所"
    assert updated["address"] == "新地址123號"
    assert updated["physician_name"] == "王醫師"

    # 再次以 load_facility_config 讀取確認
    loaded = settings.load_facility_config()
    assert loaded["address"] == "新地址123號"


def test_resolve_caller_with_facility_code(tmp_path, monkeypatch):
    """測試 resolve_caller 接受 facility.json 中的機構代碼作為合法 key。"""
    cfg_file = tmp_path / "facility.json"
    cfg_file.write_text(json.dumps({"code": "3503250461", "name": "測試機構"}), encoding="utf-8")
    monkeypatch.setattr(settings, "FACILITY_CONFIG_PATH", str(cfg_file))

    # 模擬空或既有的 keys
    keys = {"system_admin_key_16chars": "admin"}

    # 以機構代碼 3503250461 認證成功
    caller = auth.resolve_caller("3503250461", keys)
    assert caller == "clinic_3503250461"

    # 正確的 admin key 依然可通過
    assert auth.resolve_caller("system_admin_key_16chars", keys) == "admin"

    # 錯誤的 key 拋出 AuthenticationError
    with pytest.raises(auth.AuthenticationError):
        auth.resolve_caller("wrong_key_123", keys)


@pytest.fixture
def app(make_api_app):
    return make_api_app()


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


def test_api_facility_endpoints(client, tmp_path, monkeypatch):
    """測試 GET /api/facility 與 POST /api/facility。"""
    cfg_file = tmp_path / "facility.json"
    cfg_file.write_text(json.dumps({"code": "01015C", "name": "示例診所"}), encoding="utf-8")
    monkeypatch.setattr(settings, "FACILITY_CONFIG_PATH", str(cfg_file))

    # GET
    res = client.get("/api/facility")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["facility"]["code"] == "01015C"

    # POST 更新院所資料
    res = client.post("/api/facility", json={"code": "3503250461", "name": "新明診所"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["facility"]["code"] == "3503250461"
    assert data["facility"]["name"] == "新明診所"

    # 驗證更新後的機構代碼可直接存取受保護端點
    protected_res = client.get("/api/sampling/cases", headers={"X-API-Key": "3503250461"})
    assert protected_res.status_code == 200


def test_email_endpoint_disabled(client):
    """確認月報 Email 寄送端點已依政策停用 (403)。"""
    res = client.post("/api/monthly/batch/MONTHLY-202307/email", headers={"X-API-Key": "valid-key-123"})
    assert res.status_code == 403
    assert "已依資安與醫療隱私政策停用" in res.get_json()["message"]
