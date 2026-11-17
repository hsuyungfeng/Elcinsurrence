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


# ── 2026-11-17：視窗標題匹配收緊（資源管理器誤判）────────────────────


def test_explorer_window_named_after_mockhis_folder_is_excluded():
    # 實機案例：資料夾 MockHIS_new 的檔案總管視窗被誤認為測試替身
    assert probe.is_mock_his_candidate_title("MockHIS_new - 檔案總管", ["MockHIS"]) is False


def test_powershell_window_with_mockhis_in_path_is_excluded():
    assert probe.is_mock_his_candidate_title("Windows PowerShell - C:\\MockHIS_new", ["MockHIS"]) is False


def test_real_mockhis_test_window_is_candidate():
    title = "VisionHIS - MockHIS（測試替身，非真實 HIS）"
    assert probe.is_mock_his_candidate_title(title, ["MockHIS"]) is True


def test_unrelated_his_window_is_not_candidate():
    assert probe.is_mock_his_candidate_title("VisionHIS - 門診系統", ["MockHIS"]) is False


def test_find_target_windows_returns_only_mockhis_test_window(monkeypatch):
    listing = {
        "data": {"windows": [
            {"id": "w-394322", "title": "MockHIS_new - 檔案總管"},
            {"id": "w-2164520", "title": "VisionHIS - MockHIS（測試替身，非真實 HIS）"},
        ]}
    }
    monkeypatch.setattr(probe, "execute_agent_desktop_cmd",
                        lambda ad_path, args: (0, json.dumps(listing), ""))
    found = probe.find_target_windows(Path("agent-desktop.exe"), ["MockHIS"])
    assert [w["id"] for w in found] == ["w-2164520"]
