# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for ElcAgent (Phase 30: D-30-06, D-30-07).

One-folder portable distribution format.
Excludes sensitive configuration, environment files, and local calibration files.
"""

import os
from pathlib import Path

block_cipher = None
agent_dir = Path(SPECPATH).resolve()
root_dir = agent_dir.parent.parent

datas = [
    # 建置時可用 ELC_BUILD_TEMPLATE 指向含 operator_key 的暫存範本（不進 repo）
    (os.environ.get("ELC_BUILD_TEMPLATE") or str(agent_dir / "config.template.json"), "."),
    (str(agent_dir / "bin"), "bin"),
]

hiddenimports = [
    "elc_audit_engine.agent_desktop_bridge",
    "elc_audit_engine.his_calibration",
    "deploy.windows_agent.discovery",
    "deploy.windows_agent.config",
    "deploy.windows_agent.review_client",
    "deploy.windows_agent.review_window",
    "deploy.windows_agent.calibration_wizard",
    "deploy.windows_agent.calibration_view",
    "deploy.windows_agent.window_utils",
    # config/ 為 namespace 套件（無 __init__.py），PyInstaller 不會自動收集；
    # case_store 透過 `from config.settings import ...` 匯入，缺它會在校正精靈關閉後崩潰。
    "config",
    "config.settings",
]

a = Analysis(
    [str(agent_dir / "main.py")],
    pathex=[str(root_dir), str(root_dir / "src"), str(agent_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter.test",
        "unittest",
        "llama_cpp",
        "whisper",
        "torch",
        "transformers",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ElcAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ElcAgent",
)
