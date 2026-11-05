"""Build script and configuration generator for ClinicClientInstaller.exe (Phase 26).

Packages:
1. Little B Floating Assistant (SoapVoice LAN Client + Floating UI)
2. agent-desktop Windows UIA Automation Engine + his_profiles.json
3. WebBrain Local Extension Bridge (ws://127.0.0.1:17374/extension)
4. Offline RetryManager (local pending/queue.json spooler)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


INSTALLER_CONFIG: Dict[str, Any] = {
    "app_name": "Elcinsurrence Clinic Client Suite",
    "app_version": "5.0.0",
    "publisher": "Elcinsurrence Medical Systems",
    "output_dir": "dist/installer",
    "installer_name": "ClinicClientInstaller.exe",
    "components": [
        {
            "name": "LittleB",
            "description": "診間語音助理小B (即時字幕、健保紅綠燈、自費推薦)",
            "entry_point": "SoapVoice/client/lan_client.py",
            "binary": "bin/LittleB.exe",
        },
        {
            "name": "AgentDesktop",
            "description": "Windows 原生 HIS 無頭寫入引擎 (UIA Observe-Act-Verify)",
            "binary": "bin/agent-desktop.exe",
            "ffi_library": "bin/libagent_desktop_ffi.dll",
            "profiles": "config/his_profiles.json",
        },
        {
            "name": "WebBrainBridge",
            "description": "健保 VPN 雲端藥歷 2.0 預讀服務 (Protocol v2)",
            "package": "@webbrain/mcp-server",
            "ws_port": 17374,
        },
        {
            "name": "RetryManager",
            "description": "斷線自動暫存與佇列重試守護進程",
            "spool_dir": "data/pending_queue",
        },
    ],
}


def generate_inno_setup_script(config: Dict[str, Any] = INSTALLER_CONFIG) -> str:
    """Generate Inno Setup script (.iss) for building ClinicClientInstaller.exe."""
    app_name = config["app_name"]
    app_version = config["app_version"]
    publisher = config["publisher"]
    output_dir = config["output_dir"]
    output_base = Path(config["installer_name"]).stem

    iss = f"""[Setup]
AppName={app_name}
AppVersion={app_version}
AppPublisher={publisher}
DefaultDirName={{autopf}}\\{app_name}
DefaultGroupName={app_name}
OutputDir={output_dir}
OutputBaseFilename={output_base}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest

[Files]
Source: "bin\\*"; DestDir: "{{app}}\\bin"; Flags: ignoreversion recursesubdirs
Source: "config\\*"; DestDir: "{{app}}\\config"; Flags: ignoreversion
Source: "data\\*"; DestDir: "{{app}}\\data"; Flags: ignoreversion createallsubdirs

[Icons]
Name: "{{autoprograms}}\\{app_name}\\診間小B 語音助理"; Filename: "{{app}}\\bin\\LittleB.exe"
Name: "{{autoprograms}}\\{app_name}\\HIS 自動寫入設定精靈"; Filename: "{{app}}\\bin\\agent-desktop.exe"
Name: "{{commondesktop}}\\診間小B 助理"; Filename: "{{app}}\\bin\\LittleB.exe"

[Run]
Filename: "{{app}}\\bin\\LittleB.exe"; Description: "立即啟動診間小B 語音助理"; Flags: postinstall nowait skipifsilent
"""
    return iss


def generate_launcher_bat() -> str:
    """Generate Windows batch runner for clinic workstation startup."""
    return """@echo off
title Elcinsurrence Clinic Client Suite
echo ====================================================
echo  Elcinsurrence 診間一體化客戶端啟動中...
echo ====================================================

REM 1. 啟動 WebBrain Local Extension Bridge (Port 17374)
start "WebBrain Bridge" /B npx -y @webbrain/mcp-server

REM 2. 啟動診間小B 浮動視窗助理 (UDP 5001 自動探索機房)
start "Little B" /B bin\\LittleB.exe --always-on-top

echo [OK] 診間小B 與 HIS 背景自動化已就緒。
exit 0
"""


def export_installer_bundle(base_dir: Path | str = ".") -> Dict[str, Path]:
    """Export Inno Setup script and batch launcher into installer directory."""
    target_dir = Path(base_dir) / "installer"
    target_dir.mkdir(parents=True, exist_ok=True)

    iss_path = target_dir / "clinic_installer.iss"
    iss_content = generate_inno_setup_script()
    iss_path.write_text(iss_content, encoding="utf-8")

    bat_path = target_dir / "start_clinic_client.bat"
    bat_content = generate_launcher_bat()
    bat_path.write_text(bat_content, encoding="utf-8")

    config_path = target_dir / "installer_manifest.json"
    config_path.write_text(json.dumps(INSTALLER_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "iss": iss_path,
        "bat": bat_path,
        "manifest": config_path,
    }


if __name__ == "__main__":
    paths = export_installer_bundle()
    print(f"Generated installer bundle: {paths}")
