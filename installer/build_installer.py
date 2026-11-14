"""Build script for Windows Agent Inno Setup Installer (Phase 32 Plan 32-14, B3, D-32-10).

Usage:
    python -m installer.build_installer --check
    python -m installer.build_installer [--skip-pyinstaller]
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("installer.build")

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def compute_sha256(path: str) -> str:
    """計算指定檔案之 SHA-256 雜湊值（hex digest）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def check_dist_dirs() -> int:
    """檢查打包輸出目錄是否存在，供 CI 或 Linux 預先驗證。"""
    elc_dist = PROJECT_ROOT / "dist" / "ElcAgent"
    soap_dist = PROJECT_ROOT / "SoapVoice" / "dist" / "SoapVoiceClient"

    missing: List[str] = []
    if not elc_dist.is_dir():
        missing.append(f"ElcAgent 目錄不存在: {elc_dist}")
    if not soap_dist.is_dir():
        missing.append(f"SoapVoiceClient 目錄不存在: {soap_dist}")

    if missing:
        logger.error("建置檢查失敗，缺少必要的打包輸出：")
        for m in missing:
            logger.error("  - %s", m)
        return 1

    logger.info("建置檢查通過：dist/ElcAgent 與 SoapVoice/dist/SoapVoiceClient 皆已就緒。")
    return 0


def build_pyinstaller_bundles() -> bool:
    """依序編譯 ElcAgent 與 SoapVoiceClient。"""
    logger.info("開始編譯 ElcAgent (PyInstaller)...")
    build_agent_script = PROJECT_ROOT / "scripts" / "build_windows_agent.py"
    res1 = subprocess.run([sys.executable, str(build_agent_script)], cwd=str(PROJECT_ROOT))
    if res1.returncode != 0:
        logger.error("ElcAgent 編譯失敗 (exit %d)", res1.returncode)
        return False

    logger.info("開始編譯 SoapVoiceClient (PyInstaller)...")
    soap_dir = PROJECT_ROOT / "SoapVoice"
    soap_spec = soap_dir / "soapvoice_client.spec"
    res2 = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--clean", str(soap_spec)],
        cwd=str(soap_dir),
    )
    if res2.returncode != 0:
        logger.error("SoapVoiceClient 編譯失敗 (exit %d)", res2.returncode)
        return False

    return True


def compile_installer(iss_path: Path) -> Optional[Path]:
    """呼叫 Inno Setup iscc 編譯安裝檔。"""
    iscc_bin = os.environ.get("ELC_ISCC", "iscc")
    logger.info("呼叫 Inno Setup 編譯器：%s %s", iscc_bin, iss_path)

    try:
        res = subprocess.run([iscc_bin, str(iss_path)], cwd=str(iss_path.parent))
        if res.returncode != 0:
            logger.error("Inno Setup 編譯失敗 (exit %d)", res.returncode)
            return None
    except FileNotFoundError:
        logger.error("找不到 Inno Setup 編譯器 '%s'。請安裝 Inno Setup 6 並加入 PATH，或設定 ELC_ISCC 環境變數。", iscc_bin)
        return None

    setup_exe = PROJECT_ROOT / "dist" / "ElcAgentSetup.exe"
    if not setup_exe.is_file():
        logger.error("編譯完成但未找到輸出檔案: %s", setup_exe)
        return None

    return setup_exe


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="建置 ElcAgent Inno Setup 安裝檔")
    parser.add_argument("--check", action="store_true", help="僅檢查相依目錄是否存在")
    parser.add_argument("--skip-pyinstaller", action="store_true", help="跳過 PyInstaller 編譯，直接打包既有 dist")
    args = parser.parse_args(argv)

    if args.check:
        return check_dist_dirs()

    if not args.skip_pyinstaller:
        if not build_pyinstaller_bundles():
            return 1

    check_code = check_dist_dirs()
    if check_code != 0:
        return check_code

    iss_file = PROJECT_ROOT / "installer" / "elc_agent.iss"
    setup_exe = compile_installer(iss_file)
    if not setup_exe:
        return 1

    sha256 = compute_sha256(str(setup_exe))
    sha_file = setup_exe.with_suffix(".exe.sha256")
    sha_file.write_text(f"{sha256}  {setup_exe.name}\n", encoding="utf-8")

    logger.info("==================================================")
    logger.info("安裝檔建置完成: %s", setup_exe)
    logger.info("SHA256 雜湊值 : %s", sha256)
    logger.info("雜湊值已存入  : %s", sha_file)
    logger.info("==================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
