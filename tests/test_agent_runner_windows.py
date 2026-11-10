from __future__ import annotations

import subprocess
import pytest
from elc_audit_engine.agent_desktop_bridge import (
    AgentDesktopError,
    AgentDesktopRunner,
    _run_agent_desktop,
)


def test_agent_runner_creationflags_on_windows(monkeypatch):
    """Test 1: 在模擬 Windows 時，subprocess.run 收到 creationflags 等於 CREATE_NO_WINDOW 值"""
    recorded_kwargs = {}

    def fake_run(cmd, **kwargs):
        recorded_kwargs.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "run", fake_run)

    _run_agent_desktop(["agent-desktop", "snapshot"])
    assert recorded_kwargs.get("creationflags") == 0x08000000


def test_agent_runner_encoding_utf8_and_no_text_flag(monkeypatch):
    """Test 2: 呼叫參數含 encoding='utf-8' 與 errors='replace'，且不含 text=True"""
    recorded_kwargs = {}

    def fake_run(cmd, **kwargs):
        recorded_kwargs.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    _run_agent_desktop(["agent-desktop", "snapshot"])
    assert recorded_kwargs.get("encoding") == "utf-8"
    assert recorded_kwargs.get("errors") == "replace"
    assert "text" not in recorded_kwargs


def test_agent_runner_timeout_and_stdin_devnull(monkeypatch):
    """Test 3: 呼叫參數含 timeout 與 stdin=subprocess.DEVNULL"""
    recorded_kwargs = {}

    def fake_run(cmd, **kwargs):
        recorded_kwargs.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    _run_agent_desktop(["agent-desktop", "snapshot"])
    assert recorded_kwargs.get("timeout") == 30.0
    assert recorded_kwargs.get("stdin") == subprocess.DEVNULL


def test_agent_runner_error_does_not_leak_raw_output(monkeypatch):
    """Test 4: 非零返回碼時的錯誤訊息不含 stdout/stderr 原文（只含 returncode 與 cmd 的首元素）"""
    secret_leaked_text = "SECRET_PATIENT_RAW_DIAGNOSIS_DATA"

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            1,
            stdout=secret_leaked_text,
            stderr=secret_leaked_text,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    runner = AgentDesktopRunner(executable_path="agent-desktop")
    with pytest.raises(AgentDesktopError) as exc_info:
        runner.set_value("@ref1", "some_value")

    err_msg = str(exc_info.value)
    assert secret_leaked_text not in err_msg
    assert "agent-desktop" in err_msg
    assert "returncode 1" in err_msg


def test_agent_runner_mock_driver_does_not_invoke_subprocess(monkeypatch):
    """Test 5: mock_driver 路徑不呼叫 subprocess.run"""
    called = []

    def fake_run(cmd, **kwargs):
        called.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    runner = AgentDesktopRunner()
    mock_calls = []
    runner.set_mock_driver(lambda action, **kw: mock_calls.append((action, kw)) or [])

    elements = runner.snapshot("TestApp.exe")
    assert elements == []
    assert len(mock_calls) == 1
    assert len(called) == 0  # subprocess.run never called
