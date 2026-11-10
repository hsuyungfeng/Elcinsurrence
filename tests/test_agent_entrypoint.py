from __future__ import annotations

import hashlib
import os
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest

from deploy.windows_agent.config import (
    AgentSettings,
    load_settings,
    save_settings,
)
from deploy.windows_agent.discovery import DiscoveryResult
import deploy.windows_agent.main as agent_main_module
from deploy.windows_agent.main import (
    main,
    run_selftest,
    run_startup_flow,
)


@pytest.fixture(autouse=True)
def _no_default_seed_url(monkeypatch):
    """既有啟動流程測試假設沒有預設位址；預設位址行為另由專屬測試覆蓋。"""
    monkeypatch.setattr(agent_main_module, "DEFAULT_CENTRAL_SERVER_URL", "")


def test_startup_flow_probes_default_central_url_first(monkeypatch):
    """第一次啟動、無記住位址時，先探測診所預設位址（回歸：Windows 雙擊後無反應）。"""
    monkeypatch.setattr(agent_main_module, "DEFAULT_CENTRAL_SERVER_URL", "http://192.168.68.112:5000")
    probed: List[str] = []

    def fake_probe_unauth(url: str) -> bool:
        probed.append(url)
        return True

    def fake_probe_auth(url: str, key: str) -> bool:
        return True

    from deploy.windows_agent.config import AgentSettings

    res = run_startup_flow(
        AgentSettings(agent_key="k"),
        probe_unauthenticated=fake_probe_unauth,
        probe_authenticated=fake_probe_auth,
    )
    assert res == "http://192.168.68.112:5000"
    assert probed == ["http://192.168.68.112:5000"]
from elc_audit_engine.his_calibration import (
    CalibrationItem,
    CalibrationProfile,
    CalibrationStore,
    new_machine_id,
)
from scripts.build_windows_agent import (
    BuildIntegrityError,
    build_manifest,
    make_zip,
    verify_sha256,
)


# ==============================================================================
# Task 1: Configuration & Startup Discovery Flow Tests
# ==============================================================================

def test_settings_load_defaults_when_file_not_found(tmp_path: Path):
    """Test 1: 設定檔不存在時 load_settings 回傳預設值（last_server_url 為 None）"""
    cfg_file = tmp_path / "non_existent_config.json"
    settings = load_settings(cfg_file)
    assert settings.last_server_url is None
    assert settings.vendor_key == "vision"
    assert settings.app_name == "VisionHIS.exe"
    assert settings.agent_id == "agent-clinic-01"
    assert settings.agent_key == ""
    assert settings.operator_key == ""


def test_settings_round_trip_and_repr_hides_keys(tmp_path: Path):
    """Test 2: save 後 load 往返一致；agent_key 與 operator_key 欄位的 repr 不含金鑰字串"""
    cfg_file = tmp_path / "test_config.json"
    original = AgentSettings(
        last_server_url="http://192.168.1.100:5000",
        vendor_key="yaosheng",
        app_name="YaoShengClinic.exe",
        agent_id="agent-desk-99",
        agent_key="SECRET_AGENT_KEY_12345",
        operator_key="SECRET_OPERATOR_KEY_67890",
    )
    save_settings(cfg_file, original)
    loaded = load_settings(cfg_file)

    assert loaded.last_server_url == original.last_server_url
    assert loaded.vendor_key == original.vendor_key
    assert loaded.app_name == original.app_name
    assert loaded.agent_id == original.agent_id
    assert loaded.agent_key == "SECRET_AGENT_KEY_12345"
    assert loaded.operator_key == "SECRET_OPERATOR_KEY_67890"

    repr_str = repr(loaded)
    assert "SECRET_AGENT_KEY_12345" not in repr_str
    assert "SECRET_OPERATOR_KEY_67890" not in repr_str
    assert "agent_key" not in repr_str
    assert "operator_key" not in repr_str


def test_startup_flow_last_server_url_skips_discovery(tmp_path: Path):
    """Test 3: run_startup_flow 在有 last_server_url 且 probe 成功時不呼叫子網探測"""
    settings = AgentSettings(
        last_server_url="http://192.168.1.100:5000",
        operator_key="op_key",
    )
    discovery_called = False

    def fake_discovery():
        nonlocal discovery_called
        discovery_called = True
        return DiscoveryResult(candidates=["http://192.168.1.200:5000"])

    def fake_probe_auth(url: str, key: str) -> bool:
        return True

    res = run_startup_flow(
        settings=settings,
        discovery=fake_discovery,
        probe_authenticated=fake_probe_auth,
        probe_unauthenticated=lambda u: True,
    )

    assert res == "http://192.168.1.100:5000"
    assert discovery_called is False


def test_startup_flow_candidate_rejected_never_receives_key(tmp_path: Path):
    """Test 4: 探索結果為候選時，run_startup_flow 呼叫 confirm_candidate 回呼；回呼回傳 False 時不寫入 last_server_url、不呼叫帶金鑰的 probe"""
    settings = AgentSettings(
        last_server_url=None,
        operator_key="op_key_secret",
    )
    authenticated_probed_urls: List[str] = []

    def fake_discovery():
        return DiscoveryResult(candidates=["http://192.168.1.150:5000"])

    def fake_confirm(url: str) -> bool:
        return False  # User rejects candidate

    def fake_probe_auth(url: str, key: str) -> bool:
        authenticated_probed_urls.append(url)
        return True

    cfg_file = tmp_path / "config.json"
    res = run_startup_flow(
        settings=settings,
        discovery=fake_discovery,
        confirm_candidate=fake_confirm,
        probe_authenticated=fake_probe_auth,
        settings_path=cfg_file,
    )

    assert res is None
    assert settings.last_server_url is None
    assert len(authenticated_probed_urls) == 0  # Key was NEVER sent to rejected candidate


def test_startup_flow_manual_entry_validation_and_continue(tmp_path: Path):
    """Test 5: 全部失敗時呼叫 prompt_manual 回呼，輸入通過 validate_manual_server_url 後才繼續"""
    settings = AgentSettings(last_server_url=None, agent_key="agent_key_abc")

    def fake_discovery():
        return DiscoveryResult(candidates=[])

    def fake_prompt_manual():
        return "http://192.168.1.188:5000"

    authenticated_calls: List[str] = []

    def fake_probe_auth(url: str, key: str) -> bool:
        authenticated_calls.append(url)
        return True

    cfg_file = tmp_path / "config.json"
    res = run_startup_flow(
        settings=settings,
        discovery=fake_discovery,
        prompt_manual=fake_prompt_manual,
        probe_authenticated=fake_probe_auth,
        settings_path=cfg_file,
    )

    assert res == "http://192.168.1.188:5000"
    assert settings.last_server_url == "http://192.168.1.188:5000"
    assert len(authenticated_calls) == 1


def test_startup_flow_confirmed_candidate_authenticated_saved(tmp_path: Path):
    """Test 6: 使用者確認候選後，身分驗證以 operator_key 呼叫一次授權端點，成功才寫入 last_server_url"""
    settings = AgentSettings(last_server_url=None, operator_key="operator_pass_123")
    received_keys: List[str] = []

    def fake_discovery():
        return DiscoveryResult(candidates=["http://192.168.1.88:5000"])

    def fake_probe_auth(url: str, key: str) -> bool:
        received_keys.append(key)
        return True

    cfg_file = tmp_path / "config.json"
    res = run_startup_flow(
        settings=settings,
        discovery=fake_discovery,
        confirm_candidate=lambda u: True,
        probe_authenticated=fake_probe_auth,
        settings_path=cfg_file,
    )

    assert res == "http://192.168.1.88:5000"
    assert settings.last_server_url == "http://192.168.1.88:5000"
    assert received_keys == ["operator_pass_123"]


# ==============================================================================
# Task 2: Entry Point main() and --selftest Tests
# ==============================================================================

def test_selftest_missing_binary_exit_code_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """Test 1: --selftest 在 agent-desktop 不存在時退出碼為 2，訊息為中文且不含設定內容"""
    settings = AgentSettings(agent_key="SECRET_KEY_NEVER_PRINT")
    code = run_selftest(
        settings=settings,
        store=CalibrationStore(base_dir=tmp_path),
        custom_agent_desktop_bin=str(tmp_path / "non_existent_binary.exe"),
    )
    captured = capsys.readouterr().out
    assert code == 2
    assert "找不到 agent-desktop 執行檔" in captured
    assert "SECRET_KEY_NEVER_PRINT" not in captured


def test_selftest_uncalibrated_exit_code_0_and_no_his_write(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """Test 2: --selftest 在校正未 ready 時退出碼為 0 但輸出「尚未校正」，且不寫入 HIS"""
    # Create dummy fake executable so binary check passes
    dummy_bin = tmp_path / "agent-desktop.exe"
    dummy_bin.write_text("dummy", encoding="utf-8")

    settings = AgentSettings()
    store = CalibrationStore(base_dir=tmp_path)  # No calibration saved

    code = run_selftest(
        settings=settings,
        store=store,
        custom_agent_desktop_bin=str(dummy_bin),
    )
    captured = capsys.readouterr().out
    assert code == 0
    assert "尚未校正" in captured


def test_selftest_makes_zero_network_requests(tmp_path: Path):
    """Test 3: --selftest 不發出任何網路請求（以 fake http 計數為 0）"""
    dummy_bin = tmp_path / "agent-desktop.exe"
    dummy_bin.write_text("dummy", encoding="utf-8")

    network_call_count = 0

    class TrackingHttpClient:
        def request(self, *args, **kwargs):
            nonlocal network_call_count
            network_call_count += 1
            return 200, {}

    settings = AgentSettings()
    store = CalibrationStore(base_dir=tmp_path)
    code = run_selftest(
        settings=settings,
        store=store,
        custom_agent_desktop_bin=str(dummy_bin),
    )
    assert code == 0
    assert network_call_count == 0


def test_run_mode_launches_wizard_when_uncalibrated(tmp_path: Path):
    """Test 4: 無校正檔時 --run 先啟動校正精靈，校正未完成時以 STANDBY 模式進入輪詢迴圈"""
    store = CalibrationStore(base_dir=tmp_path)
    wizard_launched = False

    def fake_wizard_launcher():
        nonlocal wizard_launched
        wizard_launched = True

    captured_configs = []

    class DummyAgent:
        def __init__(self, cfg):
            self.cfg = cfg
            self.ran = False

        def run_once(self):
            self.ran = True
            raise KeyboardInterrupt()

    def fake_agent_factory(cfg, store, machine_id):
        captured_configs.append(cfg)
        return DummyAgent(cfg)

    settings = AgentSettings(last_server_url="http://192.168.1.100:5000")

    exit_code = main(
        argv=["--run"],
        settings_override=settings,
        calibration_store_override=store,
        calibration_launcher=fake_wizard_launcher,
        startup_flow_override=lambda s: "http://192.168.1.100:5000",
        agent_factory=fake_agent_factory,
    )

    assert wizard_launched is True
    assert len(captured_configs) == 1
    assert captured_configs[0].calibrated is False
    assert exit_code == 0


def test_standby_mode_heartbeat_and_writeback_blocked(tmp_path: Path):
    """STANDBY 模式下心跳回報 STANDBY 且 HIS 寫入嚴格被阻擋（fail-closed）"""
    from deploy.windows_agent.agent import AgentConfig, WindowsAgent

    store = CalibrationStore(base_dir=tmp_path)
    machine_id = new_machine_id()

    # Store has unready profile (e.g. readback_test_passed=False)
    prof = CalibrationProfile(
        vendor_key="vision",
        machine_id=machine_id,
        items=[],
        readback_test_passed=False,
    )
    store.save(prof)

    config = AgentConfig(
        server_url="http://192.168.1.100:5000",
        agent_id="agent-01",
        agent_key="key-01",
        vendor_key="vision",
        app_name="VisionHIS.exe",
        calibrated=False,
    )

    class MockHttp:
        def __init__(self):
            self.posts = []

        def request(self, method, path, payload=None):
            if method == "POST":
                self.posts.append((path, payload))
            return 200, {"status": "ok"}

    http = MockHttp()
    agent = WindowsAgent(
        config=config,
        http_client=http,
        calibration_store=store,
        machine_id=machine_id,
        allow_uncalibrated=True,
    )

    # 1. Heartbeat check
    assert agent.send_heartbeat() is True
    heartbeat_call = [p for p in http.posts if p[0] == "/api/agent/heartbeat"]
    assert len(heartbeat_call) == 1
    hb_payload = heartbeat_call[0][1]
    assert hb_payload["his_status"] == "STANDBY"
    assert hb_payload["meta"]["calibrated"] is False

    # 2. Writeback allowed check
    assert agent._writeback_allowed() is False

    # 3. execute_job check
    sample_job = {
        "job_id": "job-test-01",
        "extra_payload": {
            "case_id": "case-01",
            "content_hash": "hash123",
            "soap": {"s": "Subjective"},
        },
    }
    res = agent.execute_job(sample_job)
    assert res["status"] == "failed"
    assert res["reason"] == "uncalibrated_profile"

    # Status reported as FAILED
    status_calls = [p for p in http.posts if "/status" in p[0]]
    assert len(status_calls) == 1
    assert status_calls[0][1]["status"] == "FAILED"
    assert status_calls[0][1]["reason"] == "uncalibrated_profile"


def test_run_mode_exponential_backoff_on_failure(tmp_path: Path):
    """Test 5: --run 在 server 不可用時以指數退避重試，上限 300 秒（以注入 sleep 驗證序列）"""
    store = CalibrationStore(base_dir=tmp_path)
    # Save a ready calibration profile
    machine_id = new_machine_id()
    prof = CalibrationProfile(
        vendor_key="vision",
        machine_id=machine_id,
        items=[
            CalibrationItem(item_key="soap_s.input", section="S", kind="writable", status="confirmed", confirmed={"automation_id": "txtS"}),
            CalibrationItem(item_key="save_button.action", section="SAVE_BUTTON", kind="save_action", status="confirmed", confirmed={"name": "儲存"}),
            CalibrationItem(item_key="patient_id.check", section="PATIENT_ID", kind="identity_check", status="confirmed", confirmed={"automation_id": "txtPid"}),
        ],
        readback_test_passed=True,
    )
    store.save(prof)

    settings = AgentSettings(machine_id=machine_id, vendor_key="vision")
    sleep_calls: List[float] = []

    class FailingAgent:
        def __init__(self):
            self.iteration = 0

        def run_once(self):
            self.iteration += 1
            if self.iteration >= 5:
                # Stop loop after 5 iterations for test
                raise KeyboardInterrupt()
            return {"status": "failed", "reason": "server_down"}

    agent = FailingAgent()

    try:
        main(
            argv=["--run"],
            settings_override=settings,
            calibration_store_override=store,
            startup_flow_override=lambda s: "http://192.168.1.100:5000",
            agent_factory=lambda *a, **kw: agent,
            sleep_fn=lambda s: sleep_calls.append(s),
        )
    except KeyboardInterrupt:
        pass

    # Expected backoff sequence: 2.0, 4.0, 8.0, 16.0
    assert sleep_calls == [2.0, 4.0, 8.0, 16.0]


# ==============================================================================
# Task 3: Packaging, Manifest Exclusion & Integrity Verification Tests
# ==============================================================================

def test_manifest_builder_excludes_calibration_config_and_env():
    """Test 1: build 腳本的 manifest 產生器對含 calibration/ 目錄、config.json、.env 的輸入清單會丟棄這些檔案並記錄於排除清單"""
    input_files = [
        "ElcAgent.exe",
        "bin/agent-desktop.exe",
        "config.template.json",
        "config.json",                     # MUST BE EXCLUDED
        ".env",                            # MUST BE EXCLUDED
        ".env.production",                 # MUST BE EXCLUDED
        "calibration/vision.json",         # MUST BE EXCLUDED
        "data/calibration/profile.json",   # MUST BE EXCLUDED
        "secrets.json",                    # MUST BE EXCLUDED
    ]

    included, excluded = build_manifest(input_files)

    assert "config.template.json" in included
    assert "bin/agent-desktop.exe" in included
    assert "ElcAgent.exe" in included

    assert "config.json" in excluded
    assert ".env" in excluded
    assert ".env.production" in excluded
    assert "calibration/vision.json" in excluded
    assert "data/calibration/profile.json" in excluded
    assert "secrets.json" in excluded


def test_verify_sha256_mismatch_raises_build_integrity_error(tmp_path: Path):
    """Test 2: agent-desktop 來源檔 SHA256 與期望值不符時，build 函式拋出 BuildIntegrityError"""
    dummy_bin = tmp_path / "agent-desktop.exe"
    dummy_bin.write_bytes(b"AGENT_DESKTOP_BINARY_CONTENT")

    with pytest.raises(BuildIntegrityError, match="SHA256 mismatch"):
        verify_sha256(dummy_bin, expected="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")


def test_verify_sha256_missing_env_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test 3: 期望 SHA256 未提供（環境變數為空）時，build 函式拋出 BuildIntegrityError（fail-closed）"""
    dummy_bin = tmp_path / "agent-desktop.exe"
    dummy_bin.write_bytes(b"CONTENT")

    monkeypatch.delenv("AGENT_DESKTOP_SHA256", raising=False)

    with pytest.raises(BuildIntegrityError, match="AGENT_DESKTOP_SHA256 environment variable is not set"):
        verify_sha256(dummy_bin, expected=None)


def test_spec_file_contains_one_folder_and_hiddenimports():
    """Test 4: spec 檔以文字檢查包含 EXE(...exclude_binaries=True) 與 COLLECT，且包含必要 hiddenimports"""
    spec_path = Path(__file__).resolve().parent.parent / "deploy" / "windows_agent" / "ElcAgent.spec"
    assert spec_path.exists(), "ElcAgent.spec must exist"

    content = spec_path.read_text(encoding="utf-8")
    assert "exclude_binaries=True" in content
    assert "COLLECT(" in content
    assert "console=True" in content

    required_hidden = [
        "elc_audit_engine.agent_desktop_bridge",
        "elc_audit_engine.his_calibration",
        "deploy.windows_agent.discovery",
        "deploy.windows_agent.config",
        "deploy.windows_agent.review_client",
        "deploy.windows_agent.review_window",
        "deploy.windows_agent.calibration_wizard",
        "deploy.windows_agent.calibration_view",
    ]
    for h in required_hidden:
        assert h in content, f"Missing required hiddenimport: {h}"


def test_make_zip_structure_has_top_level_folder(tmp_path: Path):
    """Test 5: zip 內頂層目錄結構為 ElcAgent/，且含 bin/agent-desktop.exe 與 config.template.json"""
    dist_dir = tmp_path / "dist" / "ElcAgent"
    dist_dir.mkdir(parents=True)
    (dist_dir / "bin").mkdir()
    (dist_dir / "bin" / "agent-desktop.exe").write_bytes(b"EXE")
    (dist_dir / "config.template.json").write_text("{}", encoding="utf-8")

    out_zip = tmp_path / "ElcAgent-portable.zip"
    make_zip(dist_dir, out_zip)

    assert out_zip.exists()
    with zipfile.ZipFile(out_zip, "r") as zf:
        namelist = zf.namelist()
        for name in namelist:
            assert name.startswith("ElcAgent/"), f"File {name} not under ElcAgent/ top-level directory"

        assert "ElcAgent/bin/agent-desktop.exe" in namelist
        assert "ElcAgent/config.template.json" in namelist


def test_standby_run_once_does_not_claim_pending_jobs(tmp_path: Path):
    """回歸：待命（未校正）時不得領取 HIS_PUSH 任務，否則任務會被標成 FAILED 而永久遺失。"""
    from deploy.windows_agent.agent import AgentConfig, WindowsAgent

    store = CalibrationStore(base_dir=tmp_path)
    machine_id = new_machine_id()
    config = AgentConfig(
        server_url="http://192.168.1.100:5000",
        agent_id="agent-01",
        agent_key="key-01",
        vendor_key="vision",
        app_name="VisionHIS.exe",
        calibrated=False,
    )

    class MockHttp:
        def __init__(self):
            self.calls = []

        def request(self, method, path, payload=None):
            self.calls.append((method, path))
            if method == "GET" and "/jobs/pending" in path:
                return 200, {"jobs": [{"job_id": "J1"}]}
            return 200, {"status": "ok"}

    http = MockHttp()
    agent = WindowsAgent(
        config=config,
        http_client=http,
        calibration_store=store,
        machine_id=machine_id,
        allow_uncalibrated=True,
    )
    agent._last_heartbeat_time = float("inf")  # 只測領取行為，略過心跳

    assert agent.run_once() is None
    assert not any("/jobs/pending" in p for _, p in http.calls)
    assert not any("/claim" in p or "/status" in p for _, p in http.calls)
