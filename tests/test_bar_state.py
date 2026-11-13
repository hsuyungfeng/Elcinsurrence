"""Tests for deploy.windows_agent.traffic_bar.bar_state (Phase 31 Task 1)."""


from deploy.windows_agent.traffic_bar.bar_state import (
    ALL_BAR_STATES,
    ENABLED,
    STATE_AWAITING_CONFIRM,
    STATE_AWAITING_DRAFT,
    STATE_ARCHIVE_FAILED,
    STATE_ARCHIVING,
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
    project,
    status_text,
)


def test_no_tkinter_imported():
    import ast
    import sys
    import deploy.windows_agent.traffic_bar.bar_state as bs

    assert "tkinter" not in sys.modules
    with open(bs.__file__, "r", encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "tkinter" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            assert node.module is None or "tkinter" not in node.module
    assert "import tkinter" not in src


def test_on_press_behavior_across_all_states():
    """Test 1: 對每個 BarState 與每個按鈕（red、green、yellow），on_press 只在 ENABLED 允許時回 (True, None)，其餘回 (False, 非空中文提示)。"""
    buttons = ("red", "green", "yellow")
    for state in ALL_BAR_STATES:
        allowed_set = ENABLED.get(state, frozenset())
        for btn in buttons:
            allowed, toast = on_press(btn, state)
            if btn in allowed_set:
                assert allowed is True
                assert toast is None
            else:
                assert allowed is False
                assert isinstance(toast, str)
                assert len(toast.strip()) > 0


def test_on_press_pending_action_disables_all_buttons():
    """Test 4: pending_action 存在時所有按鈕停用。"""
    for action in ("starting", "stopping", "archiving", "other"):
        for state in ALL_BAR_STATES:
            for btn in ("red", "green", "yellow"):
                allowed, toast = on_press(btn, state, pending_action=action)
                assert allowed is False
                assert toast == "操作處理中，請稍候"


def test_project_rules():
    """Test 2: project 依 interfaces 規則 1–5 的每一條至少一個案例。"""
    # 規則 1: pending_action
    assert project(None, None, server_online=True, sv_online=True, pending_action="starting") == STATE_STARTING
    assert project(None, None, server_online=True, sv_online=True, pending_action="stopping") == STATE_STOPPING
    assert project(None, None, server_online=True, sv_online=True, pending_action="archiving") == STATE_ARCHIVING

    # 規則 2: 離線
    assert project(None, None, server_online=True, sv_online=False) == STATE_SOAPVOICE_OFFLINE
    assert project(None, None, server_online=False, sv_online=True) == STATE_SERVER_OFFLINE
    # 當兩者都離線時 sv_offline 先判定
    assert project(None, None, server_online=False, sv_online=False) == STATE_SOAPVOICE_OFFLINE

    # 規則 3: server_cycle 為 None
    # 3a: sv_status.state 為 RECORDING -> INTERRUPTED (SoapVoice 仍在錄、server 無循環，不得靜默丟棄)
    assert project(None, {"state": "RECORDING"}, server_online=True, sv_online=True) == STATE_INTERRUPTED
    # 3b: sv_status.state 為 ERROR -> ERROR
    assert project(None, {"state": "ERROR", "last_error": "mic fail"}, server_online=True, sv_online=True) == STATE_ERROR
    # 3c: 一般 -> IDLE
    assert project(None, {"state": "IDLE"}, server_online=True, sv_online=True) == STATE_IDLE
    assert project(None, None, server_online=True, sv_online=True) == STATE_IDLE

    # 3d: server_cycle 為 ARCHIVED 或 ABANDONED (視同無循環)
    archived_cycle = {"cycle_id": "c1", "state": "ARCHIVED"}
    assert project(archived_cycle, {"state": "IDLE"}, server_online=True, sv_online=True) == STATE_IDLE
    assert project(archived_cycle, {"state": "RECORDING"}, server_online=True, sv_online=True) == STATE_INTERRUPTED

    abandoned_cycle = {"cycle_id": "c2", "state": "ABANDONED"}
    assert project(abandoned_cycle, {"state": "IDLE"}, server_online=True, sv_online=True) == STATE_IDLE

    # 規則 4: 活躍循環對應
    # 4a: RECORDING 正常相符
    rec_cycle = {"cycle_id": "c-100", "state": "RECORDING"}
    sv_rec_ok = {"cycle_id": "c-100", "state": "RECORDING"}
    assert project(rec_cycle, sv_rec_ok, server_online=True, sv_online=True) == STATE_RECORDING

    # 4b: RECORDING 中斷成因 1: sv_cycle_id 不等於 server cycle_id
    sv_rec_mismatch = {"cycle_id": "c-999", "state": "RECORDING"}
    assert project(rec_cycle, sv_rec_mismatch, server_online=True, sv_online=True) == STATE_INTERRUPTED

    # 4c: RECORDING 中斷成因 2: sv 非 RECORDING (例如 IDLE 或已掛)
    sv_rec_dead = {"cycle_id": "c-100", "state": "IDLE"}
    assert project(rec_cycle, sv_rec_dead, server_online=True, sv_online=True) == STATE_INTERRUPTED

    # 4d: AWAITING_DRAFT 區分 UPLOADING vs AWAITING_DRAFT
    draft_cycle = {"cycle_id": "c-100", "state": "AWAITING_DRAFT"}
    sv_uploading = {"cycle_id": "c-100", "state": "UPLOADING", "chunks_pending": 3}
    assert project(draft_cycle, sv_uploading, server_online=True, sv_online=True) == STATE_UPLOADING

    sv_pending_chunks = {"cycle_id": "c-100", "state": "IDLE", "chunks_pending": 2}
    assert project(draft_cycle, sv_pending_chunks, server_online=True, sv_online=True) == STATE_UPLOADING

    sv_upload_done = {"cycle_id": "c-100", "state": "IDLE", "chunks_pending": 0}
    assert project(draft_cycle, sv_upload_done, server_online=True, sv_online=True) == STATE_AWAITING_DRAFT

    # 4e: AWAITING_CONFIRM, DRAFT_UNUSABLE, CONFIRMED, ARCHIVING, ARCHIVE_FAILED 直接對應
    for st in (STATE_AWAITING_CONFIRM, STATE_DRAFT_UNUSABLE, STATE_CONFIRMED, STATE_ARCHIVING, STATE_ARCHIVE_FAILED):
        c = {"cycle_id": "c-100", "state": st}
        assert project(c, {"state": "IDLE"}, server_online=True, sv_online=True) == st

    # 規則 5: sv_status 為 ERROR 且非終態 -> ERROR
    assert project(draft_cycle, {"state": "ERROR", "last_error": "upload failure"}, server_online=True, sv_online=True) == STATE_ERROR


def test_status_text_formatting_and_phi_leak_prevention():
    """Test 3: status_text 格式驗證與嚴禁外洩病人資料。"""
    # 待命
    assert status_text(STATE_IDLE) == "待命"

    # 錄音中
    rec_text_bound = status_text(STATE_RECORDING, {"elapsed_seconds": 192, "patient_bound": True})
    assert rec_text_bound == "錄音中 03:12（已綁定病人）"

    rec_text_unbound = status_text(STATE_RECORDING, {"elapsed_seconds": 9, "patient_bound": False})
    assert rec_text_unbound == "錄音中 00:09（未綁定病人）"

    # 上傳中
    up_text = status_text(STATE_UPLOADING, {"chunks_acked": 4, "chunks_total": 7})
    assert up_text == "上傳中 4/7"

    # 封存失敗含原因
    fail_text = status_text(STATE_ARCHIVE_FAILED, server_cycle={"last_error": "HIS 斷線"})
    assert fail_text == "封存失敗：HIS 斷線，可再按黃燈重試"

    # 錯誤
    err_text = status_text(STATE_ERROR, sv_status={"last_error": "麥克風無回應"})
    assert err_text == "錯誤：麥克風無回應"

    # 注入敏感資料測試 (T-31-20: Information Disclosure)
    leak_target = "王小明"
    sv_with_phi = {
        "elapsed_seconds": 120,
        "patient_bound": True,
        "patient_name": leak_target,
        "chart_no": "12345",
        "soap_text": "S: 主訴喉嚨痛",
    }
    cycle_with_phi = {
        "patient_name": leak_target,
        "patient_id": "A123456789",
        "last_error": "伺服器逾時",
    }
    for st in ALL_BAR_STATES:
        rendered = status_text(st, sv_status=sv_with_phi, server_cycle=cycle_with_phi)
        assert leak_target not in rendered
        assert "A123456789" not in rendered
        assert "喉嚨痛" not in rendered
