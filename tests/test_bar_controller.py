"""Phase 31: 快捷列 BarController 流程整合測試 (D-31-03, D-31-05 ~ D-31-08, D-31-11, D-31-12, D-31-16, D-31-24, D-31-33)."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from deploy.windows_agent.config import AgentSettings
from deploy.windows_agent.traffic_bar.controller import BarController
from deploy.windows_agent.traffic_bar.server_client import ServerRejected, ServerUnavailable
from deploy.windows_agent.traffic_bar.soapvoice_client import IpcRejected, IpcUnavailable


class FakeSoapVoiceClient:
    """測試用 SoapVoice 控制客戶端假物件。"""

    def __init__(self, state: str = "IDLE", cycle_id: Optional[str] = None):
        self.current_state = state
        self.current_cycle_id = cycle_id
        self.chunks_pending = 0
        self.last_error = None
        self.calls: List[str] = []
        self.start_fail: Optional[Exception] = None
        self.stop_fail: Optional[Exception] = None
        self.archived_fail: Optional[Exception] = None

    def status(self) -> Dict[str, Any]:
        self.calls.append("status")
        return {
            "contract": "elc-p31-ipc/1",
            "state": self.current_state,
            "cycle_id": self.current_cycle_id,
            "elapsed_seconds": 5.0,
            "patient_bound": False,
            "chunks_total": 1,
            "chunks_acked": 1 if self.chunks_pending == 0 else 0,
            "chunks_pending": self.chunks_pending,
            "draft_submitted": False,
            "last_error": self.last_error,
        }

    def start(self, command_id: str, cycle_id: str) -> Dict[str, Any]:
        self.calls.append(f"start:{command_id}:{cycle_id}")
        if self.start_fail:
            raise self.start_fail
        self.current_state = "RECORDING"
        self.current_cycle_id = cycle_id
        return self.status()

    def stop(self, command_id: str, cycle_id: str) -> Dict[str, Any]:
        self.calls.append(f"stop:{command_id}:{cycle_id}")
        if self.stop_fail:
            raise self.stop_fail
        self.current_state = "UPLOADING"
        return self.status()

    def archived(self, cycle_id: str) -> Dict[str, Any]:
        self.calls.append(f"archived:{cycle_id}")
        if self.archived_fail:
            raise self.archived_fail
        self.current_state = "IDLE"
        self.current_cycle_id = None
        return {"cycle_id": cycle_id, "cleanup_eligible": True}


class FakeServerClient:
    """測試用 Server 循環客戶端假物件。"""

    def __init__(self):
        self.cycles: Dict[str, Dict[str, Any]] = {}
        self.active_cycle_id: Optional[str] = None
        self.calls: List[str] = []
        self.create_fail: Optional[Exception] = None
        self.stop_fail: Optional[Exception] = None
        self.archive_responses: List[tuple[int, dict]] = []
        self.archive_fail: Optional[Exception] = None
        self.heartbeat_notify: Optional[Dict[str, Any]] = None
        self.recorded_heartbeats: List[Dict[str, Any]] = []

    def create_cycle(self, command_id: str, machine_id: str, room_id: Optional[str] = None) -> Dict[str, Any]:
        self.calls.append(f"create_cycle:{command_id}")
        if self.create_fail:
            raise self.create_fail
        cid = uuid.uuid4().hex
        cycle = {
            "cycle_id": cid,
            "machine_id": machine_id,
            "room_id": room_id,
            "state": "RECORDING",
            "chunks_received": 0,
            "total_chunks": None,
            "upload_complete": False,
        }
        self.cycles[cid] = cycle
        self.active_cycle_id = cid
        return cycle

    def get_active(self, machine_id: str) -> Optional[Dict[str, Any]]:
        self.calls.append(f"get_active:{machine_id}")
        if self.active_cycle_id:
            return self.cycles.get(self.active_cycle_id)
        return None

    def get_cycle(self, cycle_id: str) -> Dict[str, Any]:
        self.calls.append(f"get_cycle:{cycle_id}")
        return self.cycles[cycle_id]

    def stop(self, cycle_id: str, command_id: str) -> Dict[str, Any]:
        self.calls.append(f"stop:{cycle_id}")
        if self.stop_fail:
            raise self.stop_fail
        c = self.cycles[cycle_id]
        c["state"] = "AWAITING_DRAFT"
        return c

    def confirm(self, cycle_id: str, content_hash: str, soap: Optional[dict] = None, reviewer_id: Optional[str] = None) -> Dict[str, Any]:
        self.calls.append(f"confirm:{cycle_id}")
        c = self.cycles[cycle_id]
        c["state"] = "CONFIRMED"
        return {"status": "ok", "cycle": c}

    def archive(self, cycle_id: str, command_id: str) -> tuple[int, dict]:
        self.calls.append(f"archive:{cycle_id}")
        if self.archive_fail:
            raise self.archive_fail
        if self.archive_responses:
            code, body = self.archive_responses.pop(0)
            if code == 200:
                self.cycles[cycle_id]["state"] = "ARCHIVED"
                self.active_cycle_id = None
            elif code == 202:
                self.cycles[cycle_id]["state"] = "ARCHIVING"
            elif code == 409:
                self.cycles[cycle_id]["state"] = "ARCHIVE_FAILED"
            return code, body
        return 200, {"status": "archived"}

    def abandon(self, cycle_id: str, reason_code: str) -> Dict[str, Any]:
        self.calls.append(f"abandon:{cycle_id}:{reason_code}")
        c = self.cycles[cycle_id]
        c["state"] = "ABANDONED"
        if self.active_cycle_id == cycle_id:
            self.active_cycle_id = None
        return c

    def heartbeat(self, machine_id: str, **kwargs) -> Dict[str, Any]:
        self.recorded_heartbeats.append({"machine_id": machine_id, **kwargs})
        return {
            "status": "ok",
            "server_time": "2026-11-12T00:00:00Z",
            "notify": self.heartbeat_notify,
        }


@pytest.fixture
def test_setup():
    settings = AgentSettings(
        machine_id="test-machine-uuid",
        app_name="TestHIS.exe",
        room_id="room_101",
        schema_version=1,
    )
    sv = FakeSoapVoiceClient()
    server = FakeServerClient()
    open_confirm = MagicMock()
    ctrl = BarController(sv, server, settings, open_confirm_window=open_confirm, auto_recover=False)
    return ctrl, sv, server, open_confirm, settings


def test_happy_path(test_setup):
    """Test 1 happy_path: IDLE → on_red → RECORDING → on_green → UPLOADING/AWAITING_DRAFT → AWAITING_CONFIRM (通知開啟視窗一次) → on_confirm_save → CONFIRMED → on_yellow (202) → ARCHIVING → tick_server (200) → archived → IDLE。"""
    ctrl, sv, server, open_confirm, settings = test_setup

    # 1. 初始 IDLE
    assert ctrl.bar_state == "IDLE"

    # 2. 按紅燈開始錄音
    res = ctrl.on_red()
    assert res is True
    assert ctrl.bar_state == "RECORDING"
    assert ctrl.current_cycle is not None
    cid = ctrl.current_cycle["cycle_id"]

    # 3. 按綠燈結束錄音
    sv.chunks_pending = 2  # 模擬尚有分段上傳中
    res_green = ctrl.on_green()
    assert res_green is True
    assert ctrl.bar_state == "UPLOADING"

    # 分段上傳完畢
    sv.chunks_pending = 0
    sv.current_state = "IDLE"
    ctrl.tick_soapvoice()
    assert ctrl.bar_state == "AWAITING_DRAFT"

    # 4. 心跳搭便車通知：AWAITING_CONFIRM
    server.heartbeat_notify = {
        "cycle_id": cid,
        "state": "AWAITING_CONFIRM",
        "draft_id": "draft_001",
        "draft_version": 1,
    }
    ctrl.tick_server()
    assert ctrl.bar_state == "AWAITING_CONFIRM"
    open_confirm.assert_called_once_with(cid)

    # 重複心跳通知不再重複觸發開啟視窗 (D-31-12)
    ctrl.tick_server()
    assert open_confirm.call_count == 1

    # 5. 確認存檔
    ctrl.on_confirm_save(cid, content_hash="hash_abc")
    assert ctrl.bar_state == "CONFIRMED"

    # 6. 按黃燈觸發封存，回 202
    server.archive_responses = [
        (202, {"status": "his_pending"}),
        (200, {"status": "archived"}),
    ]
    res_yellow = ctrl.on_yellow()
    assert res_yellow is True
    assert ctrl.bar_state == "ARCHIVING"

    # 7. 下次 tick_server 自動重試得 200 回到 IDLE，並呼叫 SoapVoice archived
    ctrl.tick_server()
    assert ctrl.bar_state == "IDLE"
    assert f"archived:{cid}" in sv.calls


def test_soapvoice_start_failure(test_setup):
    """Test 2: SoapVoice start 回 503 → controller 呼叫 server abandon(start_failed)，回 IDLE。"""
    ctrl, sv, server, _, _ = test_setup

    sv.start_fail = IpcRejected(503, error_code="recorder_unavailable")
    res = ctrl.on_red()
    assert res is False
    assert ctrl.bar_state == "IDLE"
    assert any("abandon" in c and "start_failed" in c for c in server.calls)
    assert "失敗" in (ctrl.last_toast or "")


def test_server_create_cycle_exists(test_setup):
    """Test 3: server create 回 409 active_cycle_exists → 不呼叫 SoapVoice start，改用既有循環。"""
    ctrl, sv, server, _, settings = test_setup

    existing_cid = uuid.uuid4().hex
    server.cycles[existing_cid] = {
        "cycle_id": existing_cid,
        "machine_id": settings.machine_id,
        "state": "RECORDING",
        "chunks_received": 1,
    }
    server.active_cycle_id = existing_cid
    server.create_fail = ServerRejected(409, message="active_cycle_exists", body={"error": "active_cycle_exists", "active_cycle_id": existing_cid})

    res = ctrl.on_red()
    assert res is True
    assert ctrl.current_cycle["cycle_id"] == existing_cid
    # 不呼叫 SoapVoice start，防重設進行中錄音 (Pitfall 5)
    assert not any("start" in c for c in sv.calls)


def test_on_green_server_unavailable_resend(test_setup):
    """Test 4: on_green 時 server 無法連線 → pending_server_stop 記錄，server 恢復後補送。"""
    ctrl, sv, server, _, _ = test_setup

    ctrl.on_red()
    cid = ctrl.current_cycle["cycle_id"]

    # 模擬 server 斷線
    server.stop_fail = ServerUnavailable("Server unreachable")
    res_green = ctrl.on_green()
    assert res_green is True
    assert ctrl.pending_server_stop == cid

    # 恢復連線，tick_server 補送
    server.stop_fail = None
    ctrl.tick_server()
    assert ctrl.pending_server_stop is None
    assert any(f"stop:{cid}" in c for c in server.calls)


def test_archive_his_failed_and_retry(test_setup):
    """Test 5: archive 回 409 his_failed → ARCHIVE_FAILED；再按黃燈重試。"""
    ctrl, sv, server, _, _ = test_setup

    ctrl.on_red()
    cid = ctrl.current_cycle["cycle_id"]
    sv.current_state = "IDLE"
    ctrl.tick_soapvoice()
    ctrl.current_cycle["state"] = "CONFIRMED"

    server.archive_responses = [
        (409, {"status": "his_failed", "reason": "COM Port Timeout"}),
        (200, {"status": "archived"}),
    ]

    res1 = ctrl.on_yellow()
    assert res1 is False
    assert ctrl.bar_state == "ARCHIVE_FAILED"
    assert "COM Port Timeout" in (ctrl.last_toast or "")

    # 再按黃燈重試成功
    res2 = ctrl.on_yellow()
    assert res2 is True
    assert ctrl.bar_state == "IDLE"


def test_archive_soapvoice_ack_failure_retry(test_setup):
    """Test 6: archive 200 但 SoapVoice archived 失敗 → bar 回 IDLE，pending_archived_ack 重送。"""
    ctrl, sv, server, _, _ = test_setup

    ctrl.on_red()
    cid = ctrl.current_cycle["cycle_id"]
    sv.current_state = "IDLE"
    ctrl.tick_soapvoice()
    ctrl.current_cycle["state"] = "CONFIRMED"

    sv.archived_fail = IpcUnavailable("connection refused")
    ctrl.on_yellow()
    assert ctrl.bar_state == "IDLE"
    assert cid in ctrl.pending_archived_ack

    # 下次 tick_soapvoice 恢復連線，補送成功
    sv.archived_fail = None
    ctrl.tick_soapvoice()
    assert cid not in ctrl.pending_archived_ack


def test_invalid_button_presses(test_setup):
    """Test 7: 非法按鍵（RECORDING 按紅、IDLE 按黃、AWAITING_CONFIRM 按黃）不呼叫客戶端。"""
    ctrl, sv, server, _, _ = test_setup

    # IDLE 按黃
    assert ctrl.on_yellow() is False
    assert len(server.calls) == 0

    # 進入 RECORDING
    ctrl.on_red()
    server.calls.clear()
    sv.calls.clear()

    # RECORDING 按紅
    assert ctrl.on_red() is False
    assert len(server.calls) == 0
    assert len(sv.calls) == 0

    # 進入 AWAITING_CONFIRM
    ctrl.current_cycle["state"] = "AWAITING_CONFIRM"
    assert ctrl.on_yellow() is False
    assert len(server.calls) == 0


def test_restart_recovery_scenarios():
    """Test 8 restart_recovery: 新建 controller 的啟動還原邏輯 (Pitfall 8)。"""
    settings = AgentSettings(machine_id="m_recovery", schema_version=1)
    open_confirm = MagicMock()

    # Case A: 兩端皆 RECORDING 且同 cycle_id → 維持 RECORDING，不呼叫 start
    cid_a = uuid.uuid4().hex
    sv_a = FakeSoapVoiceClient(state="RECORDING", cycle_id=cid_a)
    srv_a = FakeServerClient()
    srv_a.cycles[cid_a] = {"cycle_id": cid_a, "machine_id": "m_recovery", "state": "RECORDING"}
    srv_a.active_cycle_id = cid_a

    ctrl_a = BarController(sv_a, srv_a, settings, open_confirm_window=open_confirm)
    assert ctrl_a.bar_state == "RECORDING"
    assert not any("start" in c for c in sv_a.calls)

    # Case B: Server RECORDING 但 SoapVoice IDLE 且 chunks_received=0 → 自動 abandon(start_incomplete)
    cid_b = uuid.uuid4().hex
    sv_b = FakeSoapVoiceClient(state="IDLE")
    srv_b = FakeServerClient()
    srv_b.cycles[cid_b] = {"cycle_id": cid_b, "machine_id": "m_recovery", "state": "RECORDING", "chunks_received": 0}
    srv_b.active_cycle_id = cid_b

    ctrl_b = BarController(sv_b, srv_b, settings, open_confirm_window=open_confirm)
    assert ctrl_b.bar_state == "IDLE"
    assert any("start_incomplete" in c for c in srv_b.calls)

    # Case C: Server RECORDING 但 SoapVoice IDLE 且 chunks_received > 0 → INTERRUPTED
    cid_c = uuid.uuid4().hex
    sv_c = FakeSoapVoiceClient(state="IDLE")
    srv_c = FakeServerClient()
    srv_c.cycles[cid_c] = {"cycle_id": cid_c, "machine_id": "m_recovery", "state": "RECORDING", "chunks_received": 2}
    srv_c.active_cycle_id = cid_c

    ctrl_c = BarController(sv_c, srv_c, settings, open_confirm_window=open_confirm)
    assert ctrl_c.bar_state == "INTERRUPTED"


def test_heartbeat_body_no_phi(test_setup):
    """Test 9: 心跳 body 含機器與狀態資訊，絕無病人與病歷欄位。"""
    ctrl, sv, server, _, settings = test_setup

    ctrl.tick_server()
    assert len(server.recorded_heartbeats) == 1
    hb = server.recorded_heartbeats[0]

    assert hb["machine_id"] == settings.machine_id
    assert hb["machine_name"] == settings.app_name
    assert hb["room_id"] == settings.room_id
    assert hb["bar_state"] == "IDLE"

    forbidden = {"soap", "transcript", "patient", "patient_name", "patient_ref", "record_no"}
    for k in hb.keys():
        assert k not in forbidden
        assert not k.startswith("patient")


def test_draft_unusable_notification(test_setup):
    """Test 10: DRAFT_UNUSABLE 通知也觸發開啟確認視窗。"""
    ctrl, sv, server, open_confirm, _ = test_setup

    cid = uuid.uuid4().hex
    server.heartbeat_notify = {
        "cycle_id": cid,
        "state": "DRAFT_UNUSABLE",
        "draft_id": "draft_unusable_01",
        "draft_version": 1,
    }
    ctrl.tick_server()
    open_confirm.assert_called_once_with(cid)


def test_controller_no_tkinter_import():
    """驗證 controller 模組純邏輯性，絕對未 import tkinter。"""
    import ast
    import inspect
    from deploy.windows_agent.traffic_bar import controller

    src = inspect.getsource(controller)
    tree = ast.parse(src)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    assert not any("tkinter" in m for m in imports)
