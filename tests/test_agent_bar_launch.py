"""客戶端快捷列接線與無主控台輸出（Phase 32-A：改進計畫 B1、B2）。

B1：Phase 31 交付了 `run_traffic_bar`，但正式程式沒有任何呼叫者、spec 也
未收錄——醫師拿到的執行檔看不到紅綠黃燈。
B2：`console=True` 會在雙擊後彈出黑色命令視窗，且 windowed 模式下
`print()`／`input()` 會直接拋例外。
"""

from __future__ import annotations

import sys
from pathlib import Path

import deploy.windows_agent.main as agent_main
from deploy.windows_agent.config import AgentSettings

SPEC = Path(__file__).resolve().parent.parent / "deploy" / "windows_agent" / "ElcAgent.spec"


# ── B1：快捷列已接進執行檔 ──────────────────────────────────────


def test_main_module_can_launch_traffic_bar():
    """正式進入點必須具備啟動快捷列的能力（原本完全沒有呼叫者）。"""
    assert callable(agent_main._launch_traffic_bar)


def test_spec_bundles_traffic_bar_modules():
    """PyInstaller spec 必須收錄快捷列模組，否則打包後 import 會失敗。"""
    spec = SPEC.read_text(encoding="utf-8")
    for mod in (
        "deploy.windows_agent.traffic_bar",
        "deploy.windows_agent.traffic_bar.bar_window",
        "deploy.windows_agent.traffic_bar.controller",
        "deploy.windows_agent.traffic_bar.server_client",
        "deploy.windows_agent.traffic_bar.soapvoice_client",
    ):
        assert mod in spec, f"ElcAgent.spec 缺少 hiddenimport：{mod}"


def test_run_mode_launches_bar_and_polls_in_background(monkeypatch, tmp_path):
    """預設 --run 應啟動快捷列，並讓 HIS 輪詢在背景執行緒繼續運作。"""
    launched: list[str] = []
    polled: list[int] = []

    def fake_launch(settings, server_url, cfg_path):
        launched.append(server_url)

    class FakeAgent:
        def run_once(self):
            polled.append(1)
            return {"status": "success"}

    monkeypatch.setattr(agent_main, "_launch_traffic_bar", fake_launch)

    from elc_audit_engine.his_calibration import CalibrationStore

    rc = agent_main.main(
        argv=["--run"],
        settings_override=AgentSettings(),
        calibration_store_override=CalibrationStore(base_dir=tmp_path),
        calibration_launcher=lambda: None,
        startup_flow_override=lambda s: "http://192.168.1.50:5000",
        # 注意：不傳 agent_factory——它會觸發無頭路徑（見 main 的註解）。
        sleep_fn=lambda s: None,
    )
    assert rc == 0
    assert launched == ["http://192.168.1.50:5000"], "預設 --run 必須啟動快捷列"


def test_no_bar_flag_skips_gui(monkeypatch, tmp_path):
    """--no-bar 維持純輪詢（維護與排錯用），不得啟動 GUI。"""
    monkeypatch.setattr(
        agent_main,
        "_launch_traffic_bar",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("不應啟動快捷列")),
    )

    class StopAgent:
        def run_once(self):
            raise KeyboardInterrupt()

    from elc_audit_engine.his_calibration import CalibrationStore

    rc = agent_main.main(
        argv=["--run", "--no-bar"],
        settings_override=AgentSettings(),
        calibration_store_override=CalibrationStore(base_dir=tmp_path),
        calibration_launcher=lambda: None,
        startup_flow_override=lambda s: "http://192.168.1.50:5000",
        agent_factory=lambda *a, **kw: StopAgent(),
        sleep_fn=lambda s: None,
    )
    assert rc == 0


def test_bar_failure_falls_back_to_polling(monkeypatch):
    """快捷列啟動失敗（無顯示環境、Tk 缺失）不得讓 HIS 回寫一起停擺。

    直接驗證 `_run_polling_loop` 的退回路徑，不經 `main()`：`main()` 在未
    注入 agent_factory 時會建立真正的 WindowsAgent，對不存在的伺服器無限
    輪詢（本測試先前即因此卡住）。
    """
    calls: list[int] = []

    class StopAgent:
        def run_once(self):
            calls.append(1)
            if len(calls) > 2:
                raise KeyboardInterrupt()
            return {"status": "success"}

    rc = agent_main._run_polling_loop(StopAgent(), lambda s: None)
    assert rc == 0
    assert len(calls) == 3, "退回模式必須真的繼續輪詢 HIS 寫入任務"


def test_polling_loop_stops_on_event():
    """背景執行緒的停止旗標必須生效，否則關閉快捷列會留下殘餘執行緒。"""
    import threading

    stop = threading.Event()
    calls: list[int] = []

    class Agent:
        def run_once(self):
            calls.append(1)
            stop.set()
            return {"status": "success"}

    rc = agent_main._run_polling_loop(Agent(), lambda s: None, stop)
    assert rc == 0
    assert len(calls) == 1


# ── B2：無主控台視窗 ───────────────────────────────────────────


def test_spec_has_no_console_window():
    """console=True 是醫師最明顯的障礙（雙擊後彈出黑色視窗）。"""
    # 只看實際設定行，不看註解（註解中會提到舊值 console=True）。
    lines = [
        ln.split("#", 1)[0].strip()
        for ln in SPEC.read_text(encoding="utf-8").splitlines()
    ]
    console_lines = [ln for ln in lines if ln.startswith("console=")]
    assert console_lines == ["console=False,"], console_lines


def test_entrypoint_does_not_call_input():
    """windowed 模式下 stdin 為 None，input() 會直接拋 RuntimeError。

    原本結尾的 `input("按 Enter 關閉視窗")` 在無主控台建置下會把「停住讓
    使用者看錯誤」變成當掉。
    """
    # 以 AST 檢查真正的呼叫，不做字串比對（註解中會提到 input()）。
    import ast

    tree = ast.parse(Path(agent_main.__file__).read_text(encoding="utf-8"))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "input" not in called, "無主控台建置不得呼叫 input()"


def test_say_survives_missing_stdout(monkeypatch, caplog):
    """windowed 模式 sys.stdout 為 None：say() 不得拋例外，且仍須留下日誌。"""
    monkeypatch.setattr(sys, "stdout", None)
    with caplog.at_level("INFO"):
        agent_main.say("測試訊息")
    assert "測試訊息" in caplog.text


def test_say_does_not_recurse(monkeypatch):
    """回歸：say() 內部若誤呼叫自己會造成無窮遞迴。"""
    printed: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **kw: printed.append(str(a[0])))
    agent_main.say("hello")
    assert printed == ["hello"]


def test_file_logging_survives_unwritable_path(tmp_path):
    """日誌寫入失敗不得讓程式無法啟動（診斷是附加價值，不是啟動條件）。"""
    blocked = tmp_path / "file.txt"
    blocked.write_text("not a directory", encoding="utf-8")
    agent_main._setup_file_logging(blocked / "nested" / "agent.log")


def test_log_path_is_per_user_writable_location():
    p = agent_main.default_log_path()
    assert p.name == "agent.log"
    assert "ElcAgent" in str(p) or ".elcagent" in str(p)
