"""30-09 探針偵測：MockHIS 證據判定（純函式，可在 Linux 執行）。"""

import importlib.util
import json
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "deploy/windows_agent/mock_his/probe_readback_check.py"
_spec = importlib.util.spec_from_file_location("probe_readback_check", _PATH)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)


def test_window_title_with_mockhis_is_evidence():
    assert probe.has_mock_evidence("{}", ["VisionHIS - MockHIS（測試替身，非真實 HIS）"]) is True


def test_snapshot_string_with_mockhis_is_evidence_at_any_depth():
    snap = json.dumps({"root": {"children": [{"name": "MockHIS：僅供校正測試"}]}})
    assert probe.has_mock_evidence(snap, []) is True


def test_real_his_snapshot_without_mock_marker_is_rejected():
    snap = json.dumps({"elements": [{"name": "病患：王大明 A123456789"}]})
    assert probe.has_mock_evidence(snap, ["VisionHIS - 門診系統"]) is False


def test_non_json_snapshot_without_title_is_rejected():
    assert probe.has_mock_evidence("not json", []) is False


def test_test_vendor_mode_is_off_by_default():
    assert probe.TEST_VENDOR_TITLE is None
