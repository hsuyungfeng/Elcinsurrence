"""Tests for Inno Setup installer script and build_installer.py (Phase 32 Plan 32-14, B3, B4)."""

import hashlib
from pathlib import Path
import pytest

from installer.build_installer import compute_sha256, main


def test_inno_setup_script_contract():
    iss_file = Path("installer/elc_agent.iss")
    if not iss_file.exists():
        pytest.fail("installer/elc_agent.iss does not exist")

    content = iss_file.read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in content
    assert "{userstartup}" in content
    assert "CloseApplications=yes" in content

    # Components and destination directories
    assert "Source: \"..\\dist\\ElcAgent\\*\"" in content
    assert "Source: \"..\\SoapVoice\\dist\\SoapVoiceClient\\*\"" in content
    assert "DestDir: \"{app}\\SoapVoice\"" in content

    # Forbidden patterns
    forbidden = ["{commonstartup}", "{pf}\\", "LittleB", "npx", "PrivilegesRequired=admin"]
    for bad in forbidden:
        assert bad not in content, f"Forbidden installer directive found: {bad}"

    # Do not delete user settings on uninstall
    if "[UninstallDelete]" in content:
        assert "{localappdata}\\ElcAgent" not in content


def test_build_installer_compute_sha256(tmp_path):
    test_file = tmp_path / "sample.bin"
    test_file.write_bytes(b"installer bytes for sha256 testing")

    expected = hashlib.sha256(b"installer bytes for sha256 testing").hexdigest()
    assert compute_sha256(str(test_file)) == expected


def test_build_installer_check_flag(monkeypatch, tmp_path):
    """驗證 --check 參數在缺漏目錄時回傳非 0，目錄齊全時回傳 0。"""
    # 模擬目錄缺漏
    fake_root = tmp_path / "fake_repo"
    fake_root.mkdir()
    monkeypatch.setattr("installer.build_installer.PROJECT_ROOT", fake_root)

    ret_missing = main(["--check"])
    assert ret_missing == 1

    # 模擬目錄存在
    (fake_root / "dist" / "ElcAgent").mkdir(parents=True)
    (fake_root / "SoapVoice" / "dist" / "SoapVoiceClient").mkdir(parents=True)

    ret_ok = main(["--check"])
    assert ret_ok == 0
