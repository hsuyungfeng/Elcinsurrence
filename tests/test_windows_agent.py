from __future__ import annotations

import logging
import pytest
from typing import Any, Dict, List, Optional

from deploy.windows_agent.agent import AgentConfig, UncalibratedVendorProfileError, WindowsAgent
from elc_audit_engine.agent_desktop_bridge import (
    AgentDesktopError,
    AgentDesktopRunner,
    HISPushAutomator,
    StaleRefError,
    UIElementRef,
    WriteResult,
)
from elc_audit_engine.case_store.soap_draft_states import compute_soap_content_hash
from elc_audit_engine.his_calibration import (
    CalibrationItem,
    CalibrationProfile,
    CalibrationStore,
    new_machine_id,
)


class MockHttpClient:
    def __init__(self, pending_jobs: Optional[List[Dict[str, Any]]] = None):
        self.pending_jobs = pending_jobs or []
        self.recorded_requests: List[Dict[str, Any]] = []

    def request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> tuple[int, Dict[str, Any]]:
        self.recorded_requests.append({"method": method, "path": path, "body": json_body})

        if method == "POST" and path == "/api/agent/heartbeat":
            return 200, {"status": "success", "agent_id": json_body.get("agent_id")}

        if method == "GET" and "/api/bridge/jobs/pending" in path:
            return 200, {"jobs": self.pending_jobs}

        if method == "POST" and "/status" in path:
            return 200, {"status": "success"}

        return 404, {"error": "not found"}


class FakeAutomator:
    def __init__(
        self,
        override_readback: Optional[Dict[str, str]] = None,
        raise_exc: Optional[Exception] = None,
        profiles: Optional[Dict[str, Any]] = None,
    ):
        self.override_readback = override_readback
        self.raise_exc = raise_exc
        self.profiles = (
            profiles if profiles is not None else {"vision": {"calibrated": True}}
        )
        self.calls: List[Dict[str, Any]] = []

    def push_case_to_his(
        self,
        vendor_key: str,
        app_name: str,
        case_payload: Dict[str, Any],
        max_retries: int = 2,
        write_soap_only: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        self.calls.append({
            "vendor_key": vendor_key,
            "app_name": app_name,
            "payload": case_payload,
            "write_soap_only": write_soap_only,
        })
        if self.raise_exc:
            raise self.raise_exc

        soap = case_payload.get("soap") or {}
        s_val = (self.override_readback.get("s") if self.override_readback and "s" in self.override_readback else soap.get("s", ""))
        o_val = (self.override_readback.get("o") if self.override_readback and "o" in self.override_readback else soap.get("o", ""))
        a_val = (self.override_readback.get("a") if self.override_readback and "a" in self.override_readback else soap.get("a", ""))
        p_val = (self.override_readback.get("p") if self.override_readback and "p" in self.override_readback else soap.get("p", ""))

        return {
            "status": "success",
            "vendor_key": vendor_key,
            "app_name": app_name,
            "results": {
                "soap_s": {"actual_value": s_val, "verified": True},
                "soap_o": {"actual_value": o_val, "verified": True},
                "soap_a": {"actual_value": a_val, "verified": True},
                "soap_p": {"actual_value": p_val, "verified": True},
            },
        }


def _make_sample_job(case_id="CASE-WIN-01", s="S-text", o="O-text", a="A-text", p="P-text") -> Dict[str, Any]:
    soap = {"s": s, "o": o, "a": a, "p": p}
    content_hash = compute_soap_content_hash(soap)
    return {
        "job_id": "job_win_1001",
        "s_type_code": "HIS_PUSH",
        "extra_payload": {
            "case_id": case_id,
            "order_code": "28016C",
            "content_hash": content_hash,
            "soap": soap,
        },
    }


def test_windows_agent_successful_writeback():
    sample_job = _make_sample_job()
    http_mock = MockHttpClient(pending_jobs=[sample_job])
    automator = FakeAutomator()

    config = AgentConfig(
        server_url="http://localhost:5000",
        agent_id="agent-desk-01",
        agent_key="key_agent_123",
        calibrated=True,
    )
    agent = WindowsAgent(
        config=config,
        automator=automator,
        http_client=http_mock,
        current_patient_getter=lambda: "CASE-WIN-01",
    )

    # 1. Heartbeat
    assert agent.send_heartbeat() is True

    # 2. Run once
    res = agent.run_once()
    assert res is not None
    assert res["status"] == "success"
    assert res["job_id"] == "job_win_1001"

    # Verify requests sent to HTTP mock
    claim_reqs = [r for r in http_mock.recorded_requests if r["body"] and r["body"].get("status") == "SENDING"]
    assert len(claim_reqs) == 1
    success_reqs = [r for r in http_mock.recorded_requests if r["body"] and r["body"].get("status") == "SUCCESS"]
    assert len(success_reqs) == 1


def test_windows_agent_startup_rejects_uncalibrated():
    """§7.4: 未校準的廠商設定不得用於正式寫入（Agent 啟動時檢查並拒絕）。"""
    config = AgentConfig(
        server_url="http://localhost:5000",
        agent_id="agent-desk-01",
        agent_key="key_agent_123",
        vendor_key="vision",
        calibrated=False,
    )
    with pytest.raises(UncalibratedVendorProfileError) as exc_info:
        WindowsAgent(config=config, automator=FakeAutomator(), http_client=MockHttpClient())
    assert "尚未於現場完成校準" in str(exc_info.value)


def test_windows_agent_uncalibrated_profile_rejected():
    sample_job = _make_sample_job()
    http_mock = MockHttpClient(pending_jobs=[sample_job])
    automator = FakeAutomator()

    # calibrated = False, but allow_uncalibrated=True to bypass startup check for test
    config = AgentConfig(
        server_url="http://localhost:5000",
        agent_id="agent-desk-01",
        agent_key="key_agent_123",
        calibrated=False,
    )
    agent = WindowsAgent(
        config=config,
        automator=automator,
        http_client=http_mock,
        allow_uncalibrated=True,
    )
    # 領取前即被閘門擋下；execute_job 仍需獨立拒絕寫入（縱深防禦）
    res = agent.execute_job({"job_id": "J1", "payload": {}})
    assert res["status"] == "failed"
    assert res["reason"] == "uncalibrated_profile"

    fail_reqs = [r for r in http_mock.recorded_requests if r["body"] and r["body"].get("status") == "FAILED"]
    assert len(fail_reqs) == 1
    assert fail_reqs[0]["body"]["reason"] == "uncalibrated_profile"


def test_windows_agent_writes_only_soap_never_icd10():
    """§8.9: 只寫 S/O/A/P，診斷/醫令/藥令僅建議不寫入。"""
    soap = {"s": "S text", "o": "O text", "a": "A text", "p": "P text"}
    content_hash = compute_soap_content_hash(soap)
    sample_job = {
        "job_id": "job_soap_only_01",
        "s_type_code": "HIS_PUSH",
        "extra_payload": {
            "case_id": "CASE-SOAP-ONLY",
            "order_code": "28016C",
            "icd10_code": "K35.80",
            "medication": "Amoxicillin 500mg tid",
            "content_hash": content_hash,
            "soap": soap,
        },
    }
    http_mock = MockHttpClient(pending_jobs=[sample_job])
    real_automator = HISPushAutomator(runner=AgentDesktopRunner())
    written_fields = {}

    def mock_driver(action, **kwargs):
        if action == "snapshot":
            return [
                UIElementRef(ref_id="@s", role="Edit", automation_id="txtSubjective", name="主訴"),
                UIElementRef(ref_id="@o", role="Edit", automation_id="txtObjective", name="客觀檢查"),
                UIElementRef(ref_id="@a", role="Edit", automation_id="txtAssessment", name="臨床評估"),
                UIElementRef(ref_id="@p", role="Edit", automation_id="txtPlan", name="治療計畫"),
                UIElementRef(ref_id="@icd", role="Edit", automation_id="txtICD10", name="主診斷碼"),
            ]
        elif action == "set_value":
            written_fields[kwargs["ref_id"]] = kwargs["value"]
            return None
        elif action == "get_value":
            return written_fields.get(kwargs["ref_id"], "")
        return None

    real_automator.runner.set_mock_driver(mock_driver)
    real_automator.profiles = {
        "vision": {
            "calibrated": True,
            "fields": {
                "soap_s": {"automation_id": "txtSubjective", "name": "主訴", "role": "Edit"},
                "soap_o": {"automation_id": "txtObjective", "name": "客觀檢查", "role": "Edit"},
                "soap_a": {"automation_id": "txtAssessment", "name": "臨床評估", "role": "Edit"},
                "soap_p": {"automation_id": "txtPlan", "name": "治療計畫", "role": "Edit"},
                "icd10": {"automation_id": "txtICD10", "name": "主診斷碼", "role": "Edit"},
            },
        }
    }
    config = AgentConfig(
        server_url="http://localhost:5000",
        agent_id="agent-desk-01",
        agent_key="key_agent_123",
        calibrated=True,
    )
    agent = WindowsAgent(
        config=config,
        automator=real_automator,
        http_client=http_mock,
        current_patient_getter=lambda: "CASE-SOAP-ONLY",
    )
    res = agent.run_once()
    assert res is not None
    assert res["status"] == "success"

    # Verify S/O/A/P are written
    assert written_fields["@s"] == "S text"
    assert written_fields["@o"] == "O text"
    assert written_fields["@a"] == "A text"
    assert written_fields["@p"] == "P text"

    # Crucial §8.9 assertion: ICD10 was NEVER written!
    assert "@icd" not in written_fields


def test_windows_agent_patient_mismatch():
    sample_job = _make_sample_job(case_id="CASE-WIN-01")
    http_mock = MockHttpClient(pending_jobs=[sample_job])
    automator = FakeAutomator()

    config = AgentConfig(
        server_url="http://localhost:5000",
        agent_id="agent-desk-01",
        agent_key="key_agent_123",
        calibrated=True,
    )
    # Active case on HIS screen is different!
    agent = WindowsAgent(
        config=config,
        automator=automator,
        http_client=http_mock,
        current_patient_getter=lambda: "CASE-WRONG-PATIENT",
    )
    res = agent.run_once()
    assert res is not None
    assert res["status"] == "failed"
    assert res["reason"] == "patient_mismatch"

    fail_reqs = [r for r in http_mock.recorded_requests if r["body"] and r["body"].get("status") == "FAILED"]
    assert len(fail_reqs) == 1
    assert fail_reqs[0]["body"]["reason"] == "patient_mismatch"


def test_windows_agent_readback_mismatch():
    sample_job = _make_sample_job()
    http_mock = MockHttpClient(pending_jobs=[sample_job])
    # Automator readback returns corrupted text
    automator = FakeAutomator(override_readback={"s": "Corrupted S text"})

    config = AgentConfig(
        server_url="http://localhost:5000",
        agent_id="agent-desk-01",
        agent_key="key_agent_123",
        calibrated=True,
    )
    agent = WindowsAgent(
        config=config,
        automator=automator,
        http_client=http_mock,
        current_patient_getter=lambda: "CASE-WIN-01",
    )
    res = agent.run_once()
    assert res is not None
    assert res["status"] == "failed"
    assert res["reason"] == "readback_mismatch"

    fail_reqs = [r for r in http_mock.recorded_requests if r["body"] and r["body"].get("status") == "FAILED"]
    assert len(fail_reqs) == 1
    assert fail_reqs[0]["body"]["reason"] == "readback_mismatch"


def test_windows_agent_ui_error():
    sample_job = _make_sample_job()
    http_mock = MockHttpClient(pending_jobs=[sample_job])
    automator = FakeAutomator(raise_exc=StaleRefError("UI element went stale"))

    config = AgentConfig(
        server_url="http://localhost:5000",
        agent_id="agent-desk-01",
        agent_key="key_agent_123",
        calibrated=True,
    )
    agent = WindowsAgent(
        config=config,
        automator=automator,
        http_client=http_mock,
        current_patient_getter=lambda: "CASE-WIN-01",
    )
    res = agent.run_once()
    assert res is not None
    assert res["status"] == "failed"
    assert res["reason"] == "ui_error"

    fail_reqs = [r for r in http_mock.recorded_requests if r["body"] and r["body"].get("status") == "FAILED"]
    assert len(fail_reqs) == 1
    assert fail_reqs[0]["body"]["reason"] == "ui_error"


def test_windows_agent_phi_log_safety(caplog):
    caplog.set_level(logging.DEBUG)
    secret_text = "SECRET_SYMPTOM_ABDOMINAL_PAIN_39C"
    sample_job = _make_sample_job(s=secret_text)
    http_mock = MockHttpClient(pending_jobs=[sample_job])
    automator = FakeAutomator()

    config = AgentConfig(
        server_url="http://localhost:5000",
        agent_id="agent-desk-01",
        agent_key="key_agent_123",
        calibrated=True,
    )
    agent = WindowsAgent(
        config=config,
        automator=automator,
        http_client=http_mock,
        current_patient_getter=lambda: "CASE-WIN-01",
    )
    res = agent.run_once()
    assert res["status"] == "success"

    # Verify secret_text is NEVER recorded in logs
    for record in caplog.records:
        assert secret_text not in record.getMessage()


# --- Phase 30 Plan 01 Task 1: Calibration Gate & Fail-Closed Patient Tests ---

def test_windows_agent_config_true_profile_false_fails_execute():
    """Test 1: config.calibrated=True 且 profile.calibrated=False 時，execute_job 不寫入，reason 為 uncalibrated_profile"""
    sample_job = _make_sample_job()
    http_mock = MockHttpClient(pending_jobs=[sample_job])
    automator = FakeAutomator(profiles={"vision": {"calibrated": False}})

    config = AgentConfig(
        server_url="http://localhost:5000",
        agent_id="agent-desk-01",
        agent_key="key_agent_123",
        calibrated=True,
    )
    # allow_uncalibrated=True lets agent start, but execute_job must still reject
    agent = WindowsAgent(
        config=config,
        automator=automator,
        http_client=http_mock,
        allow_uncalibrated=True,
        current_patient_getter=lambda: "CASE-WIN-01",
    )
    # 領取前即被閘門擋下；execute_job 仍需獨立拒絕寫入（縱深防禦）
    res = agent.execute_job({"job_id": "J1", "payload": {}})
    assert res["status"] == "failed"
    assert res["reason"] == "uncalibrated_profile"
    assert len(automator.calls) == 0


def test_windows_agent_config_false_profile_true_startup_raises():
    """Test 2: config.calibrated=False 且 profile.calibrated=True 時，validate_startup_calibration 拋出 UncalibratedVendorProfileError"""
    automator = FakeAutomator(profiles={"vision": {"calibrated": True}})
    config = AgentConfig(
        server_url="http://localhost:5000",
        agent_id="agent-desk-01",
        agent_key="key_agent_123",
        calibrated=False,
    )
    with pytest.raises(UncalibratedVendorProfileError):
        WindowsAgent(config=config, automator=automator, http_client=MockHttpClient())


def test_windows_agent_both_calibrated_success():
    """Test 3: 兩者皆 True 且 getter 回傳與 job case_id 相同的病患，寫入成功"""
    sample_job = _make_sample_job()
    http_mock = MockHttpClient(pending_jobs=[sample_job])
    automator = FakeAutomator(profiles={"vision": {"calibrated": True}})
    config = AgentConfig(
        server_url="http://localhost:5000",
        agent_id="agent-desk-01",
        agent_key="key_agent_123",
        calibrated=True,
    )
    agent = WindowsAgent(
        config=config,
        automator=automator,
        http_client=http_mock,
        current_patient_getter=lambda: "CASE-WIN-01",
    )
    res = agent.run_once()
    assert res is not None
    assert res["status"] == "success"
    assert len(automator.calls) == 1


def test_windows_agent_patient_getter_none_fail_closed():
    """Test 4: current_patient_getter 為 None 時，execute_job 不寫入，reason 為 patient_check_unavailable"""
    sample_job = _make_sample_job()
    http_mock = MockHttpClient(pending_jobs=[sample_job])
    automator = FakeAutomator(profiles={"vision": {"calibrated": True}})
    config = AgentConfig(
        server_url="http://localhost:5000",
        agent_id="agent-desk-01",
        agent_key="key_agent_123",
        calibrated=True,
    )
    agent = WindowsAgent(
        config=config,
        automator=automator,
        http_client=http_mock,
        current_patient_getter=None,
    )
    res = agent.run_once()
    assert res is not None
    assert res["status"] == "failed"
    assert res["reason"] == "patient_check_unavailable"
    assert len(automator.calls) == 0


def test_windows_agent_patient_getter_empty_or_error_fail_closed():
    """Test 5: getter 回傳 None、空字串或拋出例外時，不寫入"""
    sample_job = _make_sample_job()
    config = AgentConfig(
        server_url="http://localhost:5000",
        agent_id="agent-desk-01",
        agent_key="key_agent_123",
        calibrated=True,
    )

    # Empty string
    http_mock1 = MockHttpClient(pending_jobs=[sample_job])
    automator1 = FakeAutomator(profiles={"vision": {"calibrated": True}})
    agent1 = WindowsAgent(config=config, automator=automator1, http_client=http_mock1, current_patient_getter=lambda: "")
    res1 = agent1.run_once()
    assert res1["status"] == "failed"
    assert res1["reason"] == "patient_check_unavailable"
    assert len(automator1.calls) == 0

    # Returns None
    http_mock2 = MockHttpClient(pending_jobs=[sample_job])
    automator2 = FakeAutomator(profiles={"vision": {"calibrated": True}})
    agent2 = WindowsAgent(config=config, automator=automator2, http_client=http_mock2, current_patient_getter=lambda: None)
    res2 = agent2.run_once()
    assert res2["status"] == "failed"
    assert res2["reason"] == "patient_check_unavailable"
    assert len(automator2.calls) == 0

    # Raises Exception
    def _raising_getter():
        raise RuntimeError("UIA inaccessible")

    http_mock3 = MockHttpClient(pending_jobs=[sample_job])
    automator3 = FakeAutomator(profiles={"vision": {"calibrated": True}})
    agent3 = WindowsAgent(config=config, automator=automator3, http_client=http_mock3, current_patient_getter=_raising_getter)
    res3 = agent3.run_once()
    assert res3["status"] == "failed"
    assert res3["reason"] == "patient_check_unavailable"
    assert len(automator3.calls) == 0


def _build_ready_profile(vendor_key: str, machine_id: str) -> CalibrationProfile:
    items = [
        CalibrationItem(item_key="soap_s.input", section="S", kind="writable", status="confirmed", confirmed={"automation_id": "txtSubjective"}),
        CalibrationItem(item_key="soap_o.input", section="O", kind="writable", status="confirmed", confirmed={"automation_id": "txtObjective"}),
        CalibrationItem(item_key="soap_a.input", section="A", kind="writable", status="confirmed", confirmed={"automation_id": "txtAssessment"}),
        CalibrationItem(item_key="soap_p.input", section="P", kind="writable", status="confirmed", confirmed={"automation_id": "txtPlan"}),
        CalibrationItem(item_key="patient_id.check", section="PATIENT_ID", kind="identity_check", status="confirmed", confirmed={"automation_id": "txtPatientId"}),
        CalibrationItem(item_key="save_button.action", section="SAVE_BUTTON", kind="save_action", status="confirmed", confirmed={"automation_id": "btnSave"}),
    ]
    return CalibrationProfile(
        vendor_key=vendor_key,
        machine_id=machine_id,
        items=items,
        readback_test_passed=True,
    )


def test_windows_agent_gate_task2_test1_no_profile_fails(tmp_path):
    """Test 1: 無校正檔（store.load 回傳 None）時 _writeback_allowed 為 False，execute_job 回報 uncalibrated_profile，不呼叫寫入"""
    store = CalibrationStore(base_dir=tmp_path)
    machine_id = new_machine_id()
    config = AgentConfig(
        server_url="http://localhost:5000",
        agent_id="agent-01",
        agent_key="key-01",
        calibrated=True,
    )
    automator = FakeAutomator()
    http_mock = MockHttpClient()
    agent = WindowsAgent(
        config=config,
        automator=automator,
        http_client=http_mock,
        current_patient_getter=lambda: "CASE-WIN-01",
        calibration_store=store,
        machine_id=machine_id,
        allow_uncalibrated=True,
    )
    assert agent._writeback_allowed() is False
    res = agent.execute_job(_make_sample_job())
    assert res["status"] == "failed"
    assert res["reason"] == "uncalibrated_profile"
    assert len(automator.calls) == 0


def test_windows_agent_gate_task2_test2_unready_profile_fails(tmp_path):
    """Test 2: 校正檔存在但 is_ready 為 False 時，同上"""
    store = CalibrationStore(base_dir=tmp_path)
    machine_id = new_machine_id()
    # Profile exists but readback_test_passed=False
    prof = _build_ready_profile("vision", machine_id)
    prof.readback_test_passed = False
    store.save(prof)

    config = AgentConfig(
        server_url="http://localhost:5000",
        agent_id="agent-01",
        agent_key="key-01",
        calibrated=True,
    )
    automator = FakeAutomator()
    http_mock = MockHttpClient()
    agent = WindowsAgent(
        config=config,
        automator=automator,
        http_client=http_mock,
        current_patient_getter=lambda: "CASE-WIN-01",
        calibration_store=store,
        machine_id=machine_id,
        allow_uncalibrated=True,
    )
    assert agent._writeback_allowed() is False
    res = agent.execute_job(_make_sample_job())
    assert res["status"] == "failed"
    assert res["reason"] == "uncalibrated_profile"
    assert len(automator.calls) == 0


def test_windows_agent_gate_task2_test3_ready_profile_and_config_calibrated_success(tmp_path):
    """Test 3: 校正檔 ready 且 config.calibrated=True 時允許寫入"""
    store = CalibrationStore(base_dir=tmp_path)
    machine_id = new_machine_id()
    prof = _build_ready_profile("vision", machine_id)
    store.save(prof)

    config = AgentConfig(
        server_url="http://localhost:5000",
        agent_id="agent-01",
        agent_key="key-01",
        calibrated=True,
    )
    automator = FakeAutomator()
    http_mock = MockHttpClient()
    agent = WindowsAgent(
        config=config,
        automator=automator,
        http_client=http_mock,
        current_patient_getter=lambda: "CASE-WIN-01",
        calibration_store=store,
        machine_id=machine_id,
    )
    assert agent._writeback_allowed() is True
    res = agent.execute_job(_make_sample_job())
    assert res["status"] == "success"
    assert len(automator.calls) == 1


def test_windows_agent_gate_task2_test4_ready_profile_but_config_uncalibrated_rejected(tmp_path):
    """Test 4: 校正檔 ready 但 config.calibrated=False 時仍拒絕（AND）"""
    store = CalibrationStore(base_dir=tmp_path)
    machine_id = new_machine_id()
    prof = _build_ready_profile("vision", machine_id)
    store.save(prof)

    config = AgentConfig(
        server_url="http://localhost:5000",
        agent_id="agent-01",
        agent_key="key-01",
        calibrated=False,
    )
    automator = FakeAutomator()
    http_mock = MockHttpClient()
    agent = WindowsAgent(
        config=config,
        automator=automator,
        http_client=http_mock,
        current_patient_getter=lambda: "CASE-WIN-01",
        calibration_store=store,
        machine_id=machine_id,
        allow_uncalibrated=True,
    )
    assert agent._writeback_allowed() is False
    res = agent.execute_job(_make_sample_job())
    assert res["status"] == "failed"
    assert res["reason"] == "uncalibrated_profile"
    assert len(automator.calls) == 0


def test_windows_agent_gate_task2_test5_allow_uncalibrated_only_affects_startup(tmp_path):
    """Test 5: allow_uncalibrated=True 只影響 validate_startup_calibration，execute_job 仍拒絕未 ready 的寫入"""
    store = CalibrationStore(base_dir=tmp_path)
    machine_id = new_machine_id()
    # Unready profile
    prof = _build_ready_profile("vision", machine_id)
    prof.readback_test_passed = False
    store.save(prof)

    config = AgentConfig(
        server_url="http://localhost:5000",
        agent_id="agent-01",
        agent_key="key-01",
        calibrated=True,
    )
    automator = FakeAutomator()
    http_mock = MockHttpClient()
    # Startup succeeds due to allow_uncalibrated=True
    agent = WindowsAgent(
        config=config,
        automator=automator,
        http_client=http_mock,
        current_patient_getter=lambda: "CASE-WIN-01",
        calibration_store=store,
        machine_id=machine_id,
        allow_uncalibrated=True,
    )
    # But execute_job still rejects uncalibrated profile
    res = agent.execute_job(_make_sample_job())
    assert res["status"] == "failed"
    assert res["reason"] == "uncalibrated_profile"
    assert len(automator.calls) == 0


