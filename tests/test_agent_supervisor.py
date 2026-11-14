"""Tests for SoapVoice Supervisor (Phase 32 Plan 32-12, B4)."""

import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import MagicMock
import pytest

from deploy.windows_agent.supervisor import (
    SoapVoiceSupervisor,
    assign_kill_on_close_job,
    default_soapvoice_exe_path,
    run_in_thread,
)


class MockProcess:
    def __init__(self, alive=True):
        self._alive = alive
        self.terminated = False
        self.killed = False
        self.pid = 12345

    def poll(self):
        return None if self._alive else 1

    def terminate(self):
        self.terminated = True
        self._alive = False

    def kill(self):
        self.killed = True
        self._alive = False


def test_supervisor_lifecycle_and_backoff():
    sleep_calls = []

    def mock_sleep(s):
        sleep_calls.append(s)

    mock_proc = MockProcess(alive=True)

    def mock_popen(cmd, **kwargs):
        return mock_proc

    # 1. Missing executable
    sup = SoapVoiceSupervisor(
        exe_path="/nonexistent/SoapVoice.exe",
        popen_factory=mock_popen,
        sleep_fn=mock_sleep,
        exists_fn=lambda p: False,
    )
    assert sup.poll_once() == "missing"

    # 2. Running
    sup_running = SoapVoiceSupervisor(
        exe_path="/bin/SoapVoice.exe",
        popen_factory=mock_popen,
        sleep_fn=mock_sleep,
        exists_fn=lambda p: True,
    )
    sup_running.start()
    assert sup_running.poll_once() == "running"

    # 3. Process exits -> restarts with backoff
    mock_proc._alive = False
    assert sup_running.poll_once() == "restarting"
    assert len(sleep_calls) > 0

    # 4. Stop
    sup_running.stop()
    assert mock_proc.terminated


def test_supervisor_external_detection():
    """當 health_fn 回傳 True 時，不啟動子行程，狀態為 external。"""
    popen_called = False

    def mock_popen(cmd, **kwargs):
        nonlocal popen_called
        popen_called = True
        return MockProcess(alive=True)

    sup = SoapVoiceSupervisor(
        exe_path="/bin/SoapVoice.exe",
        popen_factory=mock_popen,
        health_fn=lambda: True,
        exists_fn=lambda p: True,
    )
    st = sup.start()
    assert st == "external"
    assert sup.poll_once() == "external"
    assert popen_called is False


def test_supervisor_stable_run_resets_restart_count():
    """穩定運行超過 stable_seconds 後，重啟次數歸零。"""
    current_time = 1000.0

    def mock_clock():
        return current_time

    mock_proc = MockProcess(alive=True)
    sup = SoapVoiceSupervisor(
        exe_path="/bin/SoapVoice.exe",
        popen_factory=lambda cmd, **kwargs: mock_proc,
        clock_fn=mock_clock,
        sleep_fn=lambda s: None,
        exists_fn=lambda p: True,
        stable_seconds=300.0,
    )
    sup.start()
    sup.restart_count = 3

    # 運行 350 秒
    current_time += 350.0
    assert sup.poll_once() == "running"
    assert sup.restart_count == 0


def test_supervisor_gives_up_after_max_restarts():
    """超過 max_restarts 次失敗後，狀態轉為 gave_up 不再重試。"""
    state_history = []
    dead_proc = MockProcess(alive=False)

    sup = SoapVoiceSupervisor(
        exe_path="/bin/SoapVoice.exe",
        popen_factory=lambda cmd, **kwargs: dead_proc,
        sleep_fn=lambda s: None,
        exists_fn=lambda p: True,
        on_state=lambda s: state_history.append(s),
        max_restarts=3,
    )
    sup.start()

    # 模擬連續失敗
    for _ in range(3):
        assert sup.poll_once() == "restarting"

    # 第 4 次超過 max_restarts=3
    assert sup.poll_once() == "gave_up"
    assert "gave_up" in state_history
    # 後續再 poll 仍維持 gave_up
    assert sup.poll_once() == "gave_up"


def test_assign_kill_on_close_job_non_windows():
    """在 Linux/macOS 上呼叫 assign_kill_on_close_job 應安全回傳 False。"""
    if sys.platform != "win32":
        assert assign_kill_on_close_job(MockProcess()) is False


def test_assign_kill_on_close_job_windows_mock(monkeypatch):
    """在 Windows 模擬環境下驗證 ctypes kernel32 呼叫順序。"""
    import ctypes
    monkeypatch.setattr(sys, "platform", "win32")

    fake_kernel32 = MagicMock()
    fake_kernel32.CreateJobObjectW.return_value = 100
    fake_kernel32.SetInformationJobObject.return_value = 1
    fake_kernel32.AssignProcessToJobObject.return_value = 1

    fake_windll = MagicMock()
    fake_windll.kernel32 = fake_kernel32
    monkeypatch.setattr(ctypes, "windll", fake_windll, raising=False)

    proc = MockProcess()
    proc._handle = 200

    ok = assign_kill_on_close_job(proc)
    assert ok is True
    fake_kernel32.CreateJobObjectW.assert_called_once()
    fake_kernel32.SetInformationJobObject.assert_called_once()
    fake_kernel32.AssignProcessToJobObject.assert_called_once_with(100, 200)


def test_run_in_thread_stops_cleanly():
    """run_in_thread 啟動背景執行緒，當 stop_event 設定時能呼叫 stop 並退出。"""
    mock_proc = MockProcess(alive=True)
    sup = SoapVoiceSupervisor(
        exe_path="/bin/SoapVoice.exe",
        popen_factory=lambda cmd, **kwargs: mock_proc,
        exists_fn=lambda p: True,
    )
    stop_evt = threading.Event()
    th = run_in_thread(sup, interval=0.05, stop_event=stop_evt)
    assert th.is_alive()

    time.sleep(0.1)
    stop_evt.set()
    th.join(timeout=1.0)
    assert not th.is_alive()
    assert sup.state == "stopped"


def test_default_soapvoice_exe_path():
    """default_soapvoice_exe_path 回傳正確之相對路徑或自訂設定。"""
    p = default_soapvoice_exe_path()
    assert p.name == "SoapVoice.exe"

    class CustomSettings:
        soapvoice_exe_path = "/opt/custom/SoapVoice.exe"

    assert default_soapvoice_exe_path(CustomSettings()) == Path("/opt/custom/SoapVoice.exe")
