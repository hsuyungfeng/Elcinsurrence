"""Windows Agent Main Entrypoint & Startup Workflow (Phase 30: D-30-06, D-30-07, D-30-08, D-30-09).

Entry point supporting:
- --selftest: Local workstation health check (zero network calls, no PHI, returns 2 if agent-desktop missing).
- --calibrate: Explicitly launches calibration wizard.
- --run: Startup discovery flow, calibration gate check, and polling worker loop with exponential backoff.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Ensure project root and src are on sys.path
_project_root = Path(__file__).resolve().parent.parent.parent
_src_dir = str(_project_root / "src")
_root_dir = str(_project_root)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)
if _root_dir not in sys.path:
    sys.path.insert(0, _root_dir)

from deploy.windows_agent.config import (
    AgentSettings,
    default_calibration_dir,
    default_settings_path,
    load_settings,
    save_settings,
)
from deploy.windows_agent.discovery import (
    DiscoveryResult,
    default_probe,
    discover_server,
    validate_manual_server_url,
)
from elc_audit_engine.his_calibration import (
    CalibrationStore,
    is_ready,
)

logger = logging.getLogger("windows_agent.main")


def default_probe_authenticated(server_url: str, auth_key: str) -> bool:
    """Default probe with authentication header against server /api/soap/drafts/pending-review."""
    import urllib.error
    import urllib.request

    if not auth_key:
        return False

    url = server_url.rstrip("/") + "/api/soap/drafts/pending-review"
    req = urllib.request.Request(url, headers={"X-API-Key": auth_key})
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        return exc.code == 200
    except Exception:
        return False


# 診所中央伺服器預設位址（區網）。第一次啟動、尚未記住位址時先探測此位址；
# 仍須通過 /api/health 的 service 身分檢查，不是盲目信任。
DEFAULT_CENTRAL_SERVER_URL = "http://192.168.68.118:5000"


def run_startup_flow(
    settings: AgentSettings,
    discovery: Optional[Callable[[], DiscoveryResult]] = None,
    confirm_candidate: Optional[Callable[[str], bool]] = None,
    prompt_manual: Optional[Callable[[], Optional[str]]] = None,
    probe_authenticated: Optional[Callable[[str, str], bool]] = None,
    probe_unauthenticated: Optional[Callable[[str], bool]] = None,
    settings_path: Optional[Path] = None,
) -> Optional[str]:
    """Execute startup server connection sequence.

    Order:
    1. Test last_server_url (unauthenticated probe first). If OK, authenticate and return without subnet scanning.
    2. Run discovery probe (unauthenticated). If candidate found, ask user confirmation before sending key.
    3. If candidate rejected or not found, fall back to manual entry (validated with validate_manual_server_url).
    """
    probe_unauth = probe_unauthenticated or (lambda u: default_probe(u, 2.0)[0] == 200)
    probe_auth = probe_authenticated or default_probe_authenticated
    auth_key = settings.operator_key or settings.agent_key

    # Step 1: Try last known server URL（尚未記住時使用診所預設位址）
    seed_url = settings.last_server_url or DEFAULT_CENTRAL_SERVER_URL
    if seed_url:
        if probe_unauth(seed_url):
            if probe_auth(seed_url, auth_key):
                return seed_url

    # Step 2: Auto-discovery
    discovery_fn = discovery or discover_server
    try:
        disc_res = discovery_fn()
    except Exception as exc:
        logger.warning("Discovery error: %s", exc)
        disc_res = DiscoveryResult()

    candidates = disc_res.candidates
    if not candidates and disc_res.chosen_url:
        candidates = [disc_res.chosen_url]

    for cand in candidates:
        confirmed = confirm_candidate(cand) if confirm_candidate else True
        if not confirmed:
            # Candidate rejected: NEVER call probe_authenticated or save (D-30-09)
            continue

        if probe_auth(cand, auth_key):
            settings.last_server_url = cand
            save_settings(settings_path, settings)
            return cand

    # Step 3: Manual input fallback
    if prompt_manual:
        manual_url = prompt_manual()
        if manual_url:
            validated_url = validate_manual_server_url(manual_url)
            if probe_auth(validated_url, auth_key):
                settings.last_server_url = validated_url
                save_settings(settings_path, settings)
                return validated_url

    return None


def find_agent_desktop_binary(custom_path: Optional[str] = None) -> Optional[Path]:
    """Locate agent-desktop executable locally."""
    if custom_path:
        p = Path(custom_path)
        if p.exists() and p.is_file():
            return p

    # Check relative to script / executable directory
    base_dir = Path(__file__).resolve().parent
    candidates = [
        base_dir / "bin" / "agent-desktop.exe",
        base_dir / "bin" / "agent-desktop",
        base_dir.parent.parent / "bin" / "agent-desktop.exe",
        base_dir.parent.parent / "bin" / "agent-desktop",
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return c

    # Check system PATH
    found = shutil.which("agent-desktop.exe") or shutil.which("agent-desktop")
    if found:
        return Path(found)

    return None


def run_selftest(
    settings: AgentSettings,
    store: Optional[CalibrationStore] = None,
    custom_agent_desktop_bin: Optional[str] = None,
) -> int:
    """Run local self-test without network activity or PHI exposure.

    Returns:
    - 0: Local checks passed (prints calibration status: '尚未校正' or '已完成校正')
    - 2: agent-desktop executable is missing
    """
    # 1. Config check
    print("自我檢查：設定檔載入正常")

    # 2. agent-desktop executable check
    bin_path = find_agent_desktop_binary(custom_agent_desktop_bin)
    if not bin_path:
        print("自我檢查失敗：找不到 agent-desktop 執行檔")
        return 2
    print("自我檢查：agent-desktop 執行檔存在")

    # 3. Calibration status check
    cal_store = store or CalibrationStore(base_dir=default_calibration_dir())
    profile = cal_store.load(settings.vendor_key, settings.machine_id)
    if profile and is_ready(profile):
        print("自我檢查：校正狀態：已完成校正")
    else:
        print("自我檢查：校正狀態：尚未校正")

    return 0


def make_snapshot_fn(custom_bin: Optional[str] = None) -> Callable[[str], List[Any]]:
    """建立校正精靈用的 UIA 快照函式（接 agent-desktop，唯讀）。

    取代先前永遠回傳空清單的 stub。HIS 未開啟時回傳空清單並記錄警告，不中斷精靈。
    """
    from elc_audit_engine.agent_desktop_bridge import AgentDesktopRunner

    bin_path = find_agent_desktop_binary(custom_bin)
    runner = AgentDesktopRunner(executable_path=str(bin_path) if bin_path else "agent-desktop")

    def _snapshot(app: str) -> List[Any]:
        try:
            return runner.snapshot(app)
        except Exception as exc:
            logger.warning("UIA 快照失敗（請確認 %s 已開啟）：%s", app, exc)
            return []

    return _snapshot


def main(
    argv: Optional[List[str]] = None,
    settings_override: Optional[AgentSettings] = None,
    calibration_store_override: Optional[CalibrationStore] = None,
    calibration_launcher: Optional[Callable[[], None]] = None,
    startup_flow_override: Optional[Callable[[AgentSettings], Optional[str]]] = None,
    agent_factory: Optional[Callable[..., Any]] = None,
    sleep_fn: Optional[Callable[[float], None]] = None,
) -> int:
    """Main CLI entry point for Windows Agent."""
    parser = argparse.ArgumentParser(description="Elcinsurrence Windows Agent")
    parser.add_argument("--selftest", action="store_true", help="執行本機自我檢查並退出")
    parser.add_argument("--check-connection", action="store_true", help="只檢查與伺服器的連線與認證後結束（不校正、不讀取畫面）")
    parser.add_argument("--calibrate", action="store_true", help="啟動 HIS 首次使用校正精靈")
    parser.add_argument("--run", action="store_true", help="啟動常駐執行模式")
    parser.add_argument("--config", type=str, default=None, help="設定檔路徑")
    parser.add_argument("--agent-desktop-bin", type=str, default=None, help="agent-desktop 執行檔路徑")

    args = parser.parse_args(argv)
    cfg_path = Path(args.config) if args.config else None
    settings = settings_override or load_settings(cfg_path)
    store = calibration_store_override or CalibrationStore(base_dir=default_calibration_dir())
    sleeper = sleep_fn or time.sleep

    # Handle --selftest
    if args.selftest:
        return run_selftest(
            settings=settings,
            store=store,
            custom_agent_desktop_bin=args.agent_desktop_bin,
        )

    # Handle --check-connection：只做連線與認證，不啟動校正、不讀取畫面
    if args.check_connection:
        check_fn = startup_flow_override or (lambda s: run_startup_flow(s, settings_path=cfg_path))
        url = check_fn(settings)
        if url:
            print(f"連線成功：{url}（已通過認證）")
            return 0
        print("連線失敗：無法連上伺服器或認證未通過。")
        return 1

    # Handle --calibrate
    if args.calibrate:
        if calibration_launcher:
            calibration_launcher()
        else:
            from deploy.windows_agent.calibration_view import run_calibration_wizard
            from deploy.windows_agent.calibration_wizard import CalibrationWizard
            wizard = CalibrationWizard(
                vendor_key=settings.vendor_key,
                app_name=settings.app_name,
                runner_snapshot_fn=make_snapshot_fn(args.agent_desktop_bin),
                store=store,
                machine_id=settings.machine_id,
                actor_id="operator",
            )
            run_calibration_wizard(wizard)
        return 0

    # Default / --run mode
    startup_fn = startup_flow_override or (lambda s: run_startup_flow(s, settings_path=cfg_path))
    server_url = startup_fn(settings)
    if not server_url:
        logger.error("無法連線至診所 central server，終止執行。")
        return 1

    # Check calibration readiness before entering polling loop
    prof = store.load(settings.vendor_key, settings.machine_id)
    if not prof or not is_ready(prof):
        logger.info("工作站尚未完成 HIS 校正，啟動校正精靈...")
        if calibration_launcher:
            calibration_launcher()
        else:
            from deploy.windows_agent.calibration_view import run_calibration_wizard
            from deploy.windows_agent.calibration_wizard import CalibrationWizard
            wizard = CalibrationWizard(
                vendor_key=settings.vendor_key,
                app_name=settings.app_name,
                runner_snapshot_fn=make_snapshot_fn(args.agent_desktop_bin),
                store=store,
                machine_id=settings.machine_id,
                actor_id="operator",
            )
            run_calibration_wizard(wizard)

    # Re-check calibration readiness after wizard (or initial check)
    prof_current = store.load(settings.vendor_key, settings.machine_id)
    is_standby = not (prof_current and is_ready(prof_current))
    if is_standby:
        logger.warning("HIS 校正尚未完成，進入「連線待命（STANDBY）」模式：允許連線與回報心跳，但禁止任何 HIS 寫入。")
        print("\n【提示】工作站尚未完成 HIS 校正，目前以「連線待命（STANDBY）」模式運行。")
        print("代理人將維持伺服器連線並定期回報心跳，但會安全阻擋任何 HIS 病歷寫入。\n")
    else:
        logger.info("HIS 校正已完成（READY），已啟用 HIS 病歷寫入。")

    # Create WindowsAgent instance
    from deploy.windows_agent.agent import AgentConfig, WindowsAgent
    agent_cfg = AgentConfig(
        server_url=server_url,
        agent_id=settings.agent_id,
        agent_key=settings.agent_key,
        vendor_key=settings.vendor_key,
        app_name=settings.app_name,
        calibrated=not is_standby,
    )
    if agent_factory:
        agent = agent_factory(agent_cfg, store, settings.machine_id)
    else:
        agent = WindowsAgent(
            config=agent_cfg,
            calibration_store=store,
            machine_id=settings.machine_id,
            allow_uncalibrated=is_standby,
        )

    # Worker loop with exponential backoff (2s -> 300s)
    backoff = 2.0
    max_backoff = 300.0
    try:
        while True:
            try:
                res = agent.run_once()
                if res is not None and res.get("status") == "success":
                    backoff = 2.0
                else:
                    sleeper(backoff)
                    backoff = min(backoff * 2.0, max_backoff)
            except Exception as exc:
                logger.warning("Polling error: %s, backing off %0.1fs", exc, backoff)
                sleeper(backoff)
                backoff = min(backoff * 2.0, max_backoff)
    except KeyboardInterrupt:
        logger.info("收到中斷信號，結束工作輪詢迴圈。")
        return 0


if __name__ == "__main__":
    _exit_code = main()
    if getattr(sys, "frozen", False):
        # 雙擊執行時主控台會在程式結束後立即關閉，使用者看不到錯誤訊息；停住等待確認。
        try:
            input("\n程式已結束（代碼 %d）。按 Enter 關閉視窗..." % _exit_code)
        except EOFError:
            pass
    sys.exit(_exit_code)
