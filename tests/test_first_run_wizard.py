"""B6 首次啟動精靈邏輯與視窗測試 (Plan 32-17, D-32-14, D-31-03)."""

from typing import Any, Dict, List
import pytest
from deploy.windows_agent.first_run_wizard import (
    DEFAULT_VENDORS,
    TEXTS,
    FirstRunFlow,
    FirstRunResult,
    run_first_run_wizard,
)
from deploy.windows_agent.traffic_bar.server_client import CycleServerClient, ServerUnavailable


class MockCycleServerClient:
    def __init__(
        self,
        base_url: str,
        fail: bool = False,
        health_data: Dict[str, Any] = None,
        rooms_data: List[Dict[str, Any]] = None,
        facility_name: str = "",
        facility_code: str = "",
    ):
        self.base_url = base_url
        self.fail = fail
        self.health_data = health_data or {
            "service": "elc-audit-engine",
            "facility_code": facility_code or "3501180000",
            "facility_name": facility_name or "安平心血管專科診所",
            "version": "1.0.0",
        }
        self.rooms_data = rooms_data if rooms_data is not None else [
            {"id": "R01", "name": "第 1 診間"},
            {"id": "R02", "name": "第 2 診間"},
        ]

    def get_health(self) -> Dict[str, Any]:
        if self.fail:
            raise ServerUnavailable("無法連線至 Mock Server")
        return self.health_data

    def get_rooms(self) -> List[Dict[str, Any]]:
        if self.fail:
            raise ServerUnavailable("無法連線至 Mock Server")
        return self.rooms_data


def test_texts_contain_no_technical_jargon():
    """TEXTS 字典不包含使用者不需理解之技術詞彙（JSON、金鑰、API、URL）。"""
    forbidden = ["JSON", "json", "金鑰", "API", "api", "URL", "url"]
    for k, v in TEXTS.items():
        for f in forbidden:
            assert f not in v, f"TEXTS['{k}'] 含有禁用技術詞彙 '{f}': {v}"


def test_first_run_flow_happy_path_three_clicks():
    """正常路徑：自動發現 → 確認 (是) → 選診間 (下一步) → 選 HIS (完成)。三次點擊即成。"""
    clients_map = {
        "http://192.168.1.100:5000": MockCycleServerClient("http://192.168.1.100:5000"),
    }

    flow = FirstRunFlow(
        discover_fn=lambda: ["http://192.168.1.100:5000"],
        client_factory=lambda url: clients_map[url],
    )

    # 1. 啟動搜尋 → 自動找到並進入 confirm_server
    ok = flow.start()
    assert ok is True
    assert flow.state == "confirm_server"
    assert flow.server_url == "http://192.168.1.100:5000"
    assert flow.facility_name == "安平心血管專科診所"
    assert flow.facility_code == "3501180000"

    # 點擊 1: 「是」
    flow.confirm(True)
    assert flow.state == "choose_room"
    assert len(flow.rooms) == 2

    # 點擊 2: 「下一步」
    flow.choose_room("R01")
    assert flow.state == "choose_vendor"
    assert flow.selected_room_id == "R01"

    # 點擊 3: 「完成」
    flow.choose_vendor("vision")
    assert flow.state == "done"
    assert flow.selected_vendor_key == "vision"

    # 完成結果產出
    res = flow.finish()
    assert isinstance(res, FirstRunResult)
    assert res.server_url == "http://192.168.1.100:5000"
    assert res.facility_code == "3501180000"
    assert res.facility_name == "安平心血管專科診所"
    assert res.room_id == "R01"
    assert res.vendor_key == "vision"


def test_first_run_flow_multiple_candidates_fallback():
    """多個候選時，第一個失敗自動嘗試第二個成功者。"""
    clients_map = {
        "http://192.168.1.10:5000": MockCycleServerClient("http://192.168.1.10:5000", fail=True),
        "http://192.168.1.20:5000": MockCycleServerClient("http://192.168.1.20:5000", facility_name="博仁家醫科診所"),
    }

    flow = FirstRunFlow(
        discover_fn=lambda: ["http://192.168.1.10:5000", "http://192.168.1.20:5000"],
        client_factory=lambda url: clients_map[url],
    )

    ok = flow.start()
    assert ok is True
    assert flow.state == "confirm_server"
    assert flow.server_url == "http://192.168.1.20:5000"
    assert flow.facility_name == "博仁家醫科診所"


def test_first_run_flow_not_found_and_retry():
    """候選全部失敗進入 not_found，retry() 重試探索。"""
    attempts = [0]

    def mock_discover():
        attempts[0] += 1
        if attempts[0] == 1:
            return []
        return ["http://192.168.1.50:5000"]

    clients_map = {
        "http://192.168.1.50:5000": MockCycleServerClient("http://192.168.1.50:5000"),
    }

    flow = FirstRunFlow(
        discover_fn=mock_discover,
        client_factory=lambda url: clients_map[url],
    )

    ok = flow.start()
    assert ok is False
    assert flow.state == "not_found"

    # 點擊重試
    ok_retry = flow.retry()
    assert ok_retry is True
    assert flow.state == "confirm_server"
    assert flow.server_url == "http://192.168.1.50:5000"


def test_first_run_flow_manual_url_entry():
    """手動輸入私有網段位址驗證與採納。"""
    clients_map = {
        "http://192.168.2.88:5000": MockCycleServerClient("http://192.168.2.88:5000", facility_name="和平診所"),
    }

    flow = FirstRunFlow(
        discover_fn=lambda: [],
        client_factory=lambda url: clients_map.get(url, MockCycleServerClient(url, fail=True)),
    )

    flow.start()
    assert flow.state == "not_found"

    # 輸入非私有網段位址被拒
    res_bad = flow.manual("8.8.8.8:5000")
    assert res_bad is False
    assert flow.state == "not_found"
    assert "非私有區域網路" in flow.error_message

    # 輸入有效私有位址
    res_good = flow.manual("192.168.2.88:5000")
    assert res_good is True
    assert flow.state == "confirm_server"
    assert flow.server_url == "http://192.168.2.88:5000"
    assert flow.facility_name == "和平診所"


def test_first_run_flow_confirm_no_rejects_candidate():
    """醫師按「不是」排除該伺服器，若無其他候選則進入 not_found。"""
    flow = FirstRunFlow(
        discover_fn=lambda: ["http://192.168.1.99:5000"],
        client_factory=lambda url: MockCycleServerClient(url, facility_name="其他診所"),
    )

    flow.start()
    assert flow.state == "confirm_server"

    # 按「不是」
    flow.confirm(False)
    assert flow.state == "not_found"
    assert flow.server_url == ""


def test_first_run_flow_single_room_and_single_vendor_preselection():
    """單一診間或單一廠商時自動預選。"""
    flow = FirstRunFlow(
        discover_fn=lambda: ["http://192.168.1.50:5000"],
        client_factory=lambda url: MockCycleServerClient(
            url,
            rooms_data=[{"id": "R01", "name": "一般診間"}],
        ),
        vendors={"vision": "展望"},
    )

    flow.start()
    flow.confirm(True)
    assert flow.state == "choose_room"
    # 自動預選單一診間
    assert flow.selected_room_id == "R01"

    flow.choose_room("R01")
    assert flow.state == "choose_vendor"
    # 自動預選單一廠商
    assert flow.selected_vendor_key == "vision"


def test_first_run_flow_empty_rooms_allowed():
    """伺服器尚未設定診間時允許略過（room_id 為空字串）。"""
    flow = FirstRunFlow(
        discover_fn=lambda: ["http://192.168.1.50:5000"],
        client_factory=lambda url: MockCycleServerClient(url, rooms_data=[]),
    )

    flow.start()
    flow.confirm(True)
    assert flow.state == "choose_room"
    assert flow.rooms == []

    # 允許以空診間進入下一步
    flow.choose_room("")
    assert flow.state == "choose_vendor"
    assert flow.selected_room_id == ""


def test_cycle_server_client_get_health_and_get_rooms(monkeypatch):
    """驗證 CycleServerClient 的 get_health 與 get_rooms 方法。"""
    client = CycleServerClient("http://127.0.0.1:5000")

    def mock_request(method, path, body=None, allow_statuses=(200,)):
        if path == "/api/health":
            return 200, {"service": "elc-audit-engine", "facility_name": "測試診所"}
        if path == "/api/rooms":
            return 200, {"rooms": [{"id": "R1", "name": "診間1"}]}
        return 404, {}

    monkeypatch.setattr(client, "_request", mock_request)

    health = client.get_health()
    assert health["facility_name"] == "測試診所"

    rooms = client.get_rooms()
    assert len(rooms) == 1
    assert rooms[0]["id"] == "R1"


def test_run_first_run_wizard_callable():
    """驗證 run_first_run_wizard 可呼叫（在非 GUI 或測試中安全返回）。"""
    assert callable(run_first_run_wizard)
