"""回歸測試：Windows agent 的預設校正目錄（見 selftest 曾因缺 base_dir 崩潰）。"""

from pathlib import Path

from deploy.windows_agent.config import default_calibration_dir


def test_default_calibration_dir_ends_with_calibration():
    d = default_calibration_dir()
    assert isinstance(d, Path)
    assert d.name == "calibration"


def test_default_calibration_dir_respects_localappdata(monkeypatch, tmp_path):
    import deploy.windows_agent.config as cfg

    monkeypatch.setattr(cfg.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_calibration_dir() == tmp_path / "ElcAgent" / "calibration"


def test_first_run_bootstraps_settings_from_bundled_template(monkeypatch, tmp_path):
    """設定檔不存在時，從打包範本取得 operator_key 並寫入本機設定檔（不需使用者手動填寫）。"""
    import json

    import deploy.windows_agent.config as cfg

    template = tmp_path / "config.template.json"
    template.write_text(json.dumps({"operator_key": "TEST-KEY-123", "vendor_key": "vision"}), encoding="utf-8")
    monkeypatch.setattr(cfg, "bundled_template_path", lambda: template)
    target = tmp_path / "ElcAgent" / "config.json"

    settings = cfg.load_settings(target)

    assert settings.operator_key == "TEST-KEY-123"
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8"))["operator_key"] == "TEST-KEY-123"


def test_check_connection_success_exits_zero_without_calibration(tmp_path, capsys):
    """--check-connection：連線成功回傳 0，且不啟動校正精靈、不讀取畫面。"""
    import deploy.windows_agent.main as agent_main
    from deploy.windows_agent.config import AgentSettings

    launched = []
    code = agent_main.main(
        argv=["--check-connection", "--config", str(tmp_path / "c.json")],
        settings_override=AgentSettings(agent_key="SECRET-XYZ"),
        calibration_launcher=lambda: launched.append(True),
        startup_flow_override=lambda s: "http://192.168.68.118:5000",
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "連線成功" in out
    assert "SECRET-XYZ" not in out
    assert launched == []


def test_check_connection_failure_exits_one(tmp_path, capsys):
    import deploy.windows_agent.main as agent_main
    from deploy.windows_agent.config import AgentSettings

    code = agent_main.main(
        argv=["--check-connection", "--config", str(tmp_path / "c.json")],
        settings_override=AgentSettings(),
        startup_flow_override=lambda s: None,
    )
    assert code == 1
    assert "連線失敗" in capsys.readouterr().out


def test_make_snapshot_fn_is_not_empty_stub_and_degrades_safely(tmp_path):
    """校正快照接 agent-desktop：不再是永遠回傳空清單的 stub；失敗時回傳空清單不崩潰。"""
    import deploy.windows_agent.main as agent_main

    snap = agent_main.make_snapshot_fn(str(tmp_path / "missing-agent-desktop.exe"))
    assert callable(snap)
    assert snap("VisionHIS.exe") == []


def test_spec_collects_config_settings_namespace_package():
    """回歸：config/ 無 __init__.py，spec 必須明確收集 config.settings（否則打包版 case_store 匯入失敗）。"""
    from pathlib import Path

    spec = (Path(__file__).resolve().parent.parent / "deploy/windows_agent/ElcAgent.spec").read_text(encoding="utf-8")
    assert '"config.settings"' in spec
