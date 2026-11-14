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
import threading
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

_SINGLE_INSTANCE_MUTEX = None


def _ensure_single_instance() -> None:
    """Windows 具名 Mutex 強制單一實例。若已存在，提示並結束。"""
    global _SINGLE_INSTANCE_MUTEX
    if sys.platform != "win32":
        return

    import ctypes

    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.windll.kernel32
    mutex_name = "ElcAgentSingleInstance"
    mutex = kernel32.CreateMutexW(None, False, mutex_name)
    last_err = kernel32.GetLastError()
    if last_err == ERROR_ALREADY_EXISTS:
        _notify_already_running()
        sys.exit(0)
    _SINGLE_INSTANCE_MUTEX = mutex


def _notify_already_running() -> None:
    """彈出提示視窗提醒醫師已有實例在運行。"""
    msg = "ElcAgent 已經在運行中。\n請檢查右下角系統匣圖示或工作列快捷列。"
    logger.info("偵測到重複實例，程式退出。")
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("ElcAgent 已在運行", msg)
        root.destroy()
    except Exception:
        if sys.stderr is not None:
            print(msg, file=sys.stderr)


def _check_or_run_first_setup(
    settings: AgentSettings,
    cfg_path: Optional[Path],
    flow_factory: Optional[Callable[[], Any]] = None,
    wizard_runner: Optional[Callable[[Any], Any]] = None,
) -> Optional[AgentSettings]:
    """若設定檔缺少 facility_code 或 room_id，喚起首次啟動精靈（32-17 B6）。"""
    if settings.facility_code and settings.room_id:
        return settings

    from deploy.windows_agent.first_run_wizard import FirstRunFlow, run_first_run_wizard

    flow = flow_factory() if flow_factory else FirstRunFlow()
    runner = wizard_runner or run_first_run_wizard
    res = runner(flow)
    if res is None:
        logger.info("使用者取消首次設定精靈，結束程式。")
        return None

    settings.last_server_url = res.server_url
    settings.facility_code = res.facility_code
    settings.room_id = res.room_id
    settings.vendor_key = res.vendor_key
    save_settings(cfg_path, settings)
    logger.info("首次啟動精靈設定已成功儲存至 %s", cfg_path)
    return settings


def default_log_path() -> Path:
    """診斷日誌路徑（Phase 32-A／B2：無主控台後的唯一輸出去向）。"""
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "ElcAgent" / "logs" / "agent.log"
    return Path.home() / ".elcagent" / "logs" / "agent.log"


def say(message: str) -> None:
    """輸出使用者訊息，在無主控台（PyInstaller windowed）環境下安全。

    windowed 模式的 `sys.stdout` 為 None，直接 `print()` 會拋
    AttributeError；一律改走日誌，並在有主控台時才額外印出。
    """
    logger.info(message)
    if sys.stdout is not None:
        try:
            print(message)  # noqa: T201 - 刻意：有主控台時給使用者即時回饋
        except (OSError, ValueError):
            # 主控台已關閉或重導失敗；日誌已留存，不中斷流程。
            pass


def _setup_file_logging(log_path: Optional[Path] = None) -> None:
    """將日誌寫入檔案，讓無主控台的執行檔仍可排錯。

    失敗時（唯讀目錄、權限不足）不得讓程式無法啟動——診斷能力是附加價值，
    不是啟動條件。
    """
    target = log_path or default_log_path()
    handlers: List[logging.Handler] = []
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(target, encoding="utf-8"))
    except OSError as exc:  # noqa: BLE001 - 已降級處理
        if sys.stderr is not None:
            print(f"（警告）無法寫入日誌檔 {target}：{exc}", file=sys.stderr)
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers or [logging.NullHandler()],
        force=True,
    )


def _notify_exit_failure(exit_code: int) -> None:
    """以視窗告知醫師啟動失敗與日誌位置（無主控台時唯一的可見提示）。"""
    message = (
        f"ElcAgent 無法啟動（代碼 {exit_code}）。\n\n"
        f"請聯絡安裝人員，並提供此檔案：\n{default_log_path()}"
    )
    logger.error("啟動失敗，代碼 %d", exit_code)
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("ElcAgent 啟動失敗", message)
        root.destroy()
    except Exception:
        # 無顯示環境（例如伺服器或 CI）時退回文字輸出。
        if sys.stderr is not None:
            print(message, file=sys.stderr)


def default_probe_authenticated(server_url: str, auth_key: str = "") -> bool:
    """Probe a real business endpoint to confirm the server accepts this workstation.

    Phase 32-A：院內網路不需驗證，故不再附帶金鑰。本探測仍有意義——它確認
    本機來源位址落在伺服器的信任網段內（非信任來源會得到 403），因此是
    「這台電腦能不能用」的真正答案，而 /api/health 只回答「伺服器活著嗎」。

    原本實作在 `auth_key` 為空時直接回傳 False，導致未注入金鑰的客戶端
    永遠連不上伺服器。
    """
    import urllib.error
    import urllib.request

    url = server_url.rstrip("/") + "/api/soap/drafts/pending-review"
    req = urllib.request.Request(url, headers={"User-Agent": "ElcAgent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        return exc.code == 200
    except Exception:
        return False


# Phase 32-A（改進計畫 C1）：移除寫死的診所伺服器位址。
# 原本寫死 `http://192.168.68.118:5000`——那是某一間診所的位址，換分享器
# 或 DHCP 重發就連不上，且會讓其他診所的客戶端去探測不存在的主機。
# 位址只應來自：① 本機記住的上次位址 ② 區網自動探索 ③ 使用者手動輸入。


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

    # Step 1: Try last known server URL（無寫死預設位址，見上方 C1 註解）
    seed_url = settings.last_server_url
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
    say("自我檢查：設定檔載入正常")

    # 2. agent-desktop executable check
    bin_path = find_agent_desktop_binary(custom_agent_desktop_bin)
    if not bin_path:
        say("自我檢查失敗：找不到 agent-desktop 執行檔")
        return 2
    say("自我檢查：agent-desktop 執行檔存在")

    # 3. Calibration status check
    cal_store = store or CalibrationStore(base_dir=default_calibration_dir())
    profile = cal_store.load(settings.vendor_key, settings.machine_id)
    if profile and is_ready(profile):
        say("自我檢查：校正狀態：已完成校正")
    else:
        say("自我檢查：校正狀態：尚未校正")

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
    ensure_single_instance_fn: Optional[Callable[[], None]] = None,
    first_run_launcher: Optional[Callable[[AgentSettings, Optional[Path]], Optional[AgentSettings]]] = None,
) -> int:
    """Main CLI entry point for Windows Agent."""
    if ensure_single_instance_fn:
        ensure_single_instance_fn()
    elif settings_override is None:
        _ensure_single_instance()

    parser = argparse.ArgumentParser(description="Elcinsurrence Windows Agent")
    parser.add_argument("--selftest", action="store_true", help="執行本機自我檢查並退出")
    parser.add_argument("--check-connection", action="store_true", help="只檢查與伺服器的連線與認證後結束（不校正、不讀取畫面）")
    parser.add_argument("--calibrate", action="store_true", help="啟動 HIS 首次使用校正精靈")
    parser.add_argument("--run", action="store_true", help="啟動常駐執行模式")
    parser.add_argument("--config", type=str, default=None, help="設定檔路徑")
    parser.add_argument("--agent-desktop-bin", type=str, default=None, help="agent-desktop 執行檔路徑")
    parser.add_argument(
        "--no-bar",
        action="store_true",
        help="不啟動快捷列，只在背景輪詢 HIS 寫入任務（維護與排錯用）",
    )

    args = parser.parse_args(argv)
    # 無主控台的執行檔（B2）唯一的診斷來源；測試注入 settings_override 時
    # 不設定，避免污染 pytest 的 logging 設定。
    if settings_override is None:
        _setup_file_logging()
    no_bar = args.no_bar
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

    # First Run Wizard check (B6)
    if not args.check_connection and not args.calibrate:
        if not settings.facility_code or not settings.room_id:
            if first_run_launcher is not None:
                updated = first_run_launcher(settings, cfg_path)
                if updated is None:
                    return 0
                settings = updated
            elif startup_flow_override is None and agent_factory is None:
                updated = _check_or_run_first_setup(settings, cfg_path)
                if updated is None:
                    return 0
                settings = updated

    # Handle --check-connection：只做連線與認證，不啟動校正、不讀取畫面
    if args.check_connection:
        check_fn = startup_flow_override or (lambda s: run_startup_flow(s, settings_path=cfg_path))
        url = check_fn(settings)
        if url:
            say(f"連線成功：{url}（已通過認證）")
            return 0
        say("連線失敗：無法連上伺服器或認證未通過。")
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
        say("\n【提示】工作站尚未完成 HIS 校正，目前以「連線待命（STANDBY）」模式運行。")
        say("代理人將維持伺服器連線並定期回報心跳，但會安全阻擋任何 HIS 病歷寫入。\n")
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

    # Phase 32-A（改進計畫 B1）：預設啟動快捷列，HIS 輪詢移至背景執行緒。
    #
    # 為何需要這段：Phase 31 交付了 `run_traffic_bar`，但正式程式中沒有任何
    # 呼叫者，`ElcAgent.spec` 也未收錄——醫師拿到的執行檔看不到紅綠黃燈。
    #
    # 執行緒配置：Tkinter 的事件迴圈必須在主執行緒（Windows 上於非主執行緒
    # 建立視窗會直接失敗），故快捷列佔用主執行緒，HIS 寫入輪詢改為 daemon
    # 背景執行緒。daemon=True 讓關閉快捷列即可結束整個程式，不留殘餘程序。
    #
    # 注入 agent_factory（測試替身）時一律走無頭路徑：測試不應依賴顯示環境，
    # 且會讓 tkinter 被匯入而污染其他測試的 sys.modules 斷言。
    if no_bar or agent_factory is not None:
        return _run_polling_loop(agent, sleeper)

    stop_polling = threading.Event()
    poller = threading.Thread(
        target=_run_polling_loop,
        args=(agent, sleeper, stop_polling),
        name="his-push-poller",
        daemon=True,
    )
    poller.start()

    try:
        _launch_traffic_bar(settings, server_url, cfg_path)
    except KeyboardInterrupt:
        # 輪詢迴圈已移至背景執行緒，Ctrl+C 現在落在主執行緒的 Tk 事件迴圈，
        # 不再由該迴圈自己的 handler 接到；在此收斂為正常結束。
        logger.info("收到中斷信號，關閉快捷列並結束。")
    except Exception as exc:
        # 快捷列失敗不得讓 HIS 回寫一起停擺：退回純輪詢模式繼續服務
        # （例如伺服器無顯示環境、Tk 未安裝、SoapVoice 控制通道異常）。
        logger.error("快捷列啟動失敗，退回背景輪詢模式：%s", exc)
        stop_polling.set()
        poller.join(timeout=5.0)
        return _run_polling_loop(agent, sleeper)

    stop_polling.set()
    return 0


def _run_polling_loop(
    agent: Any,
    sleeper: Callable[[float], None],
    stop_event: Optional[Any] = None,
) -> int:
    """HIS 寫入任務輪詢迴圈，指數退避 2s → 300s。

    Args:
        agent: WindowsAgent（或測試替身），需有 `run_once()`。
        sleeper: 休眠函式（測試可注入）。
        stop_event: `threading.Event`；設定後迴圈結束（背景執行緒用）。
    """
    backoff = 2.0
    max_backoff = 300.0
    try:
        while not (stop_event is not None and stop_event.is_set()):
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


def _launch_traffic_bar(
    settings: AgentSettings,
    server_url: str,
    cfg_path: Optional[Path],
    supervisor_factory: Optional[Callable[..., Any]] = None,
    tray_launcher: Optional[Callable[..., Any]] = None,
) -> None:
    """組裝快捷列的相依元件並進入 Tk 主迴圈（阻塞至醫師關閉視窗）。"""
    import atexit
    import queue
    from deploy.windows_agent.traffic_bar.controller import BarController
    from deploy.windows_agent.traffic_bar.server_client import CycleServerClient
    from deploy.windows_agent.traffic_bar.soapvoice_client import SoapVoiceControlClient
    from deploy.windows_agent.traffic_bar import run_traffic_bar
    from deploy.windows_agent.supervisor import SoapVoiceSupervisor, default_soapvoice_exe_path
    from deploy.windows_agent.tray import TrayController, start_tray

    sv_client = SoapVoiceControlClient(port=settings.soapvoice_control_port)
    server_client = CycleServerClient(base_url=server_url)

    # 1. Supervisor 看管 SoapVoice (B4)
    sv_exe = settings.soapvoice_exe_path or default_soapvoice_exe_path()
    supervisor: Optional[SoapVoiceSupervisor] = None
    if supervisor_factory:
        supervisor = supervisor_factory()
        if supervisor:
            supervisor.start()
    elif sv_exe and Path(sv_exe).exists():
        try:
            supervisor = SoapVoiceSupervisor(
                exe_path=str(sv_exe),
                port=settings.soapvoice_control_port,
            )
            supervisor.start()
            logger.info("SoapVoice Supervisor 已啟動並看管：%s", sv_exe)
        except Exception as exc:
            logger.warning("SoapVoice Supervisor 啟動失敗: %s", exc)

    if supervisor:
        atexit.register(supervisor.stop)

    def _open_confirm_window(cycle_id: str) -> None:
        """草稿就緒時跳出 SOAP 確認視窗（D-31-05 的醫師確認步驟）。"""
        from deploy.windows_agent.review_client import ReviewClient
        from deploy.windows_agent.review_window import run_review_window

        try:
            client = ReviewClient(base_url=server_url, machine_id=settings.machine_id)
            run_review_window(client)
        except Exception as exc:
            logger.error("開啟 SOAP 確認視窗失敗（循環 %s）：%s", cycle_id, exc)

    controller = BarController(
        sv_client=sv_client,
        server_client=server_client,
        settings=settings,
        open_confirm_window=_open_confirm_window,
    )

    # 2. 系統匣圖示整合 (B5)
    tray_queue: queue.Queue[str] = queue.Queue()
    tray_ctrl = TrayController(tray_queue)
    tray_icon = None
    launcher = tray_launcher or start_tray
    try:
        tray_icon = launcher(tray_ctrl)
    except Exception as exc:
        logger.warning("啟動 System Tray 圖示失敗: %s", exc)

    logger.info("啟動快捷列（紅綠黃燈），伺服器：%s", server_url)
    try:
        run_traffic_bar(controller, settings, cfg_path)
    finally:
        if supervisor:
            supervisor.stop()
        if tray_icon:
            try:
                tray_icon.stop()
            except Exception:
                pass


if __name__ == "__main__":
    _exit_code = main()
    # Phase 32-A（B2）：無主控台視窗後不得再呼叫 input()。
    # PyInstaller windowed 模式下 sys.stdin/stdout 為 None，input() 會直接
    # 拋 RuntimeError——原本「停住等待確認」的好意會變成當掉。
    # 失敗原因改以視窗提示（醫師看得到）＋日誌檔（工程師可查）呈現。
    if _exit_code != 0:
        _notify_exit_failure(_exit_code)
    sys.exit(_exit_code)
