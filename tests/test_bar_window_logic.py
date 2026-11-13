"""Phase 31: 快捷列 Tk 視窗純邏輯測試 (D-31-09, D-31-10, D-31-11).

完全不依賴 Tkinter 或 X11，可在 Linux 無顯示環境下直接以 pytest 執行。
驗證項目：
1. 15 種狀態下紅綠黃三鈕之啟用/禁用與背景色投影 (D-31-11)。
2. 收合 (160x44) 與展開 (250x100) 檢視模型之尺寸與欄位切換 (D-31-10)。
3. 連線狀態文字與中斷提示 (D-31-10)。
4. 非法點擊阻絕與 Toast 覆蓋訊息。
5. 視窗拖曳記憶座標夾取與多螢幕防脫逸 (D-31-09, bar_position)。
"""

from __future__ import annotations


from deploy.windows_agent.config import AgentSettings, save_settings
from deploy.windows_agent.traffic_bar.bar_position import clamp_position, default_position
from deploy.windows_agent.traffic_bar.bar_state import (
    STATE_ARCHIVE_FAILED,
    STATE_ARCHIVING,
    STATE_AWAITING_CONFIRM,
    STATE_AWAITING_DRAFT,
    STATE_CONFIRMED,
    STATE_DRAFT_UNUSABLE,
    STATE_ERROR,
    STATE_IDLE,
    STATE_INTERRUPTED,
    STATE_RECORDING,
    STATE_SERVER_OFFLINE,
    STATE_SOAPVOICE_OFFLINE,
    STATE_STARTING,
    STATE_STOPPING,
    STATE_UPLOADING,
    on_press,
)
from deploy.windows_agent.traffic_bar.bar_window import (
    COLLAPSED_HEIGHT,
    COLLAPSED_WIDTH,
    COLOR_GREEN_ACTIVE,
    COLOR_GREEN_DIM,
    COLOR_RED_ACTIVE,
    COLOR_RED_DIM,
    COLOR_YELLOW_ACTIVE,
    COLOR_YELLOW_DIM,
    EXPANDED_HEIGHT,
    EXPANDED_WIDTH,
    build_view_model,
)


class MockController:
    """純邏輯模擬 Controller，提供 BarViewModel 測試所需狀態。"""

    def __init__(
        self,
        state: str = STATE_IDLE,
        status_msg: str = "待命",
        server_online: bool = True,
        sv_online: bool = True,
        pending_action: str | None = None,
    ):
        self._state = state
        self._status_msg = status_msg
        self.server_online = server_online
        self.sv_online = sv_online
        self.pending_action = pending_action

    def bar_state(self) -> str:
        return self._state

    def status(self) -> str:
        return self._status_msg


def test_button_enabled_and_colors_idle():
    """IDLE 狀態：僅紅燈啟用（鮮紅），綠黃禁用（暗色）。"""
    ctrl = MockController(state=STATE_IDLE, status_msg="待命")
    vm = build_view_model(ctrl, is_expanded=False)

    assert vm.red_enabled is True
    assert vm.green_enabled is False
    assert vm.yellow_enabled is False

    assert vm.red_bg == COLOR_RED_ACTIVE
    assert vm.green_bg == COLOR_GREEN_DIM
    assert vm.yellow_bg == COLOR_YELLOW_DIM
    assert vm.status_text == "待命"


def test_button_enabled_and_colors_recording():
    """RECORDING 狀態：僅綠燈啟用（鮮綠），紅黃禁用（暗色）。"""
    ctrl = MockController(state=STATE_RECORDING, status_msg="錄音中 01:20（已綁定病人）")
    vm = build_view_model(ctrl, is_expanded=False)

    assert vm.red_enabled is False
    assert vm.green_enabled is True
    assert vm.yellow_enabled is False

    assert vm.red_bg == COLOR_RED_DIM
    assert vm.green_bg == COLOR_GREEN_ACTIVE
    assert vm.yellow_bg == COLOR_YELLOW_DIM
    assert "錄音中" in vm.status_text


def test_button_enabled_and_colors_confirmed_and_archive_failed():
    """CONFIRMED 與 ARCHIVE_FAILED 狀態：僅黃燈啟用（鮮黃），紅綠禁用。"""
    for st, msg in [(STATE_CONFIRMED, "可封存"), (STATE_ARCHIVE_FAILED, "封存失敗：逾時，可再按黃燈重試")]:
        ctrl = MockController(state=st, status_msg=msg)
        vm = build_view_model(ctrl, is_expanded=False)

        assert vm.red_enabled is False
        assert vm.green_enabled is False
        assert vm.yellow_enabled is True

        assert vm.red_bg == COLOR_RED_DIM
        assert vm.green_bg == COLOR_GREEN_DIM
        assert vm.yellow_bg == COLOR_YELLOW_ACTIVE
        assert vm.status_text == msg


def test_button_disabled_in_intermediate_states():
    """中介狀態 (UPLOADING, AWAITING_CONFIRM, ARCHIVING 等)：紅綠黃三鈕皆禁用。"""
    states = [
        STATE_STARTING,
        STATE_STOPPING,
        STATE_UPLOADING,
        STATE_AWAITING_DRAFT,
        STATE_AWAITING_CONFIRM,
        STATE_DRAFT_UNUSABLE,
        STATE_ARCHIVING,
        STATE_INTERRUPTED,
        STATE_ERROR,
        STATE_SERVER_OFFLINE,
        STATE_SOAPVOICE_OFFLINE,
    ]
    for st in states:
        ctrl = MockController(state=st, status_msg=f"狀態-{st}")
        vm = build_view_model(ctrl, is_expanded=False)
        assert vm.red_enabled is False, f"red should be disabled in {st}"
        assert vm.green_enabled is False, f"green should be disabled in {st}"
        assert vm.yellow_enabled is False, f"yellow should be disabled in {st}"


def test_collapsed_vs_expanded_view_model():
    """收合與展開檢視模型尺寸與狀態 (D-31-10)。"""
    ctrl = MockController(state=STATE_IDLE, status_msg="待命")

    # 收合
    vm_c = build_view_model(ctrl, is_expanded=False)
    assert vm_c.is_expanded is False
    assert vm_c.width == COLLAPSED_WIDTH
    assert vm_c.height == COLLAPSED_HEIGHT

    # 展開
    vm_e = build_view_model(ctrl, is_expanded=True)
    assert vm_e.is_expanded is True
    assert vm_e.width == EXPANDED_WIDTH
    assert vm_e.height == EXPANDED_HEIGHT


def test_connection_status_text_formatting():
    """連線狀態文字反映伺服器與 SoapVoice 狀態 (D-31-10)。"""
    # 雙在線
    ctrl1 = MockController(server_online=True, sv_online=True)
    vm1 = build_view_model(ctrl1)
    assert "Server 連線正常" in vm1.connection_text
    assert "SoapVoice 正常" in vm1.connection_text

    # Server 離線
    ctrl2 = MockController(server_online=False, sv_online=True)
    vm2 = build_view_model(ctrl2)
    assert "Server 斷線" in vm2.connection_text
    assert "SoapVoice 正常" in vm2.connection_text

    # SoapVoice 離線
    ctrl3 = MockController(server_online=True, sv_online=False)
    vm3 = build_view_model(ctrl3)
    assert "Server 連線正常" in vm3.connection_text
    assert "SoapVoice 斷線" in vm3.connection_text


def test_toast_override_display():
    """當有操作錯誤提示 (Toast) 時，display_status 應優先顯示 Toast 內容。"""
    ctrl = MockController(state=STATE_IDLE, status_msg="待命")
    toast_msg = "目前非錄音狀態，無法結束錄音"

    vm = build_view_model(ctrl, toast_override=toast_msg)
    assert vm.status_text == toast_msg
    assert vm.toast == toast_msg


def test_illegal_button_press_validation():
    """按鈕點擊合法性驗證 (D-31-11, on_press)。"""
    # 1. IDLE 下按綠燈與黃燈應被拒絕
    ok_g, toast_g = on_press("green", STATE_IDLE)
    assert ok_g is False
    assert "無法結束錄音" in toast_g

    ok_y, toast_y = on_press("yellow", STATE_IDLE)
    assert ok_y is False
    assert "無可封存草稿" in toast_y

    # 2. RECORDING 下按紅燈應被拒絕
    ok_r, toast_r = on_press("red", STATE_RECORDING)
    assert ok_r is False
    assert "無法開始錄音" in toast_r

    # 3. 處理中 pending_action 應拒絕所有按鈕
    ok_p, toast_p = on_press("red", STATE_IDLE, pending_action="starting")
    assert ok_p is False
    assert "操作處理中" in toast_p


def test_position_clamping_and_persistence(tmp_path):
    """視窗拖曳記憶座標之夾取、防脫逸與設定檔儲存 (D-31-09)。"""
    screen = (0, 0, 1920, 1080)
    monitors = [screen]

    # 正常螢幕內座標不變
    cx1, cy1 = clamp_position((500, 400), monitors, bar_w=COLLAPSED_WIDTH, bar_h=COLLAPSED_HEIGHT)
    assert (cx1, cy1) == (500, 400)

    # 部分超出右下邊界自動夾回
    cx2, cy2 = clamp_position((1800, 1060), monitors, bar_w=COLLAPSED_WIDTH, bar_h=COLLAPSED_HEIGHT)
    assert cx2 == 1920 - COLLAPSED_WIDTH
    assert cy2 == 1080 - COLLAPSED_HEIGHT

    # 完全落在螢幕外回傳主螢幕預設位置
    cx3, cy3 = clamp_position((-5000, -5000), monitors, bar_w=COLLAPSED_WIDTH, bar_h=COLLAPSED_HEIGHT)
    def_x, def_y = default_position(1920, 1080, COLLAPSED_WIDTH, COLLAPSED_HEIGHT)
    assert (cx3, cy3) == (def_x, def_y)

    # 測試設定檔持久化記憶
    settings_file = tmp_path / "agent_settings.json"
    settings = AgentSettings(bar_x=cx1, bar_y=cy1)
    save_settings(settings_file, settings)

    assert settings_file.is_file()
    from deploy.windows_agent.config import load_settings
    loaded = load_settings(settings_file)
    assert loaded.bar_x == 500
    assert loaded.bar_y == 400
