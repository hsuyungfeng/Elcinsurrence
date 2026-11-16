"""Tests for Windows Agent system tray module (Phase 32 Plan 32-05, B5)."""

import queue
from unittest.mock import patch

from deploy.windows_agent.tray import (
    TRAY_ACTIONS,
    TrayController,
    build_menu_spec,
    start_tray,
)


def test_tray_actions_keys():
    expected = {"toggle_bar", "connection_status", "recalibrate", "quit"}
    assert set(TRAY_ACTIONS) == expected


def test_build_menu_spec_toggle_and_connection():
    # 1. Bar visible -> "隱藏快捷列"
    spec1 = build_menu_spec(bar_visible=True, connection_text="連線正常")
    assert len(spec1) == 4
    labels = [s[0] for s in spec1]
    keys = [s[1] for s in spec1]

    assert keys == ["toggle_bar", "connection_status", "recalibrate", "quit"]
    assert "隱藏快捷列" in labels[0]
    assert "連線正常" in labels[1]
    assert "重新校正 HIS" in labels[2]
    assert "結束" in labels[3]

    # 2. Bar hidden -> "顯示快捷列"
    spec2 = build_menu_spec(bar_visible=False, connection_text="伺服器離線")
    assert "顯示快捷列" in spec2[0][0]
    assert "伺服器離線" in spec2[1][0]


def test_tray_controller_dispatch():
    q = queue.Queue()
    controller = TrayController(q)

    # Valid keys put into queue
    controller.dispatch("toggle_bar")
    controller.dispatch("quit")
    assert q.get_nowait() == "toggle_bar"
    assert q.get_nowait() == "quit"

    # Unknown key ignored and does not raise
    controller.dispatch("unknown_action")
    assert q.empty()


def test_start_tray_non_windows_returns_none():
    q = queue.Queue()
    controller = TrayController(q)

    with patch("sys.platform", "linux"):
        res = start_tray(controller)
        assert res is None
