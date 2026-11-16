"""Tests for calibration_view without askstring and without JSON (Phase 32 Plan 32-04, B7)."""

from pathlib import Path
from unittest.mock import MagicMock

from deploy.windows_agent.calibration_view import (
    describe_item,
    handle_pick_result,
)


def test_calibration_view_source_no_askstring_or_json_prompts():
    view_path = Path("deploy/windows_agent/calibration_view.py")
    assert view_path.exists(), "calibration_view.py must exist"
    content = view_path.read_text(encoding="utf-8")

    assert "askstring" not in content, "calibration_view.py must not call askstring"
    assert "選擇器 JSON" not in content, "calibration_view.py must not prompt for 選擇器 JSON"
    assert "import json" not in content, "calibration_view.py should not import json"


def test_handle_pick_result_corrected():
    wizard = MagicMock()
    selector = {"automation_id": "txtSubjective"}

    status = handle_pick_result(wizard, selector)
    assert status == "corrected"
    wizard.correct.assert_called_once_with(selector)
    wizard.skip.assert_not_called()


def test_handle_pick_result_need_installer():
    wizard = MagicMock()

    status = handle_pick_result(wizard, None)
    assert status == "need_installer"
    wizard.skip.assert_called_once()
    wizard.correct.assert_not_called()


def test_describe_item_no_curly_brackets():
    item_detected = MagicMock()
    item_detected.section = "S"
    item_detected.item_key = "s_field"
    item_detected.detected = {"automation_id": "field1"}
    item_detected.suggested = {"automation_id": "field1"}

    desc1 = describe_item(item_detected)
    assert "{" not in desc1 and "}" not in desc1
    assert "已找到" in desc1 or "相符" in desc1

    item_missing = MagicMock()
    item_missing.section = "O"
    item_missing.item_key = "o_field"
    item_missing.detected = None
    item_missing.suggested = None

    desc2 = describe_item(item_missing)
    assert "{" not in desc2 and "}" not in desc2
    assert "未偵測到" in desc2 or "找不到" in desc2
