"""Tests for Agent-Desktop HIS Push automation and ClinicClientInstaller."""

import pytest
from elc_audit_engine.agent_desktop_bridge import (
    DEFAULT_HIS_PROFILES,
    AgentDesktopRunner,
    HISPushAutomator,
    StaleRefError,
    UIElementRef,
    process_his_push_job,
)
from installer.build_clinic_installer import (
    INSTALLER_CONFIG,
    export_installer_bundle,
    generate_inno_setup_script,
    generate_launcher_bat,
)


@pytest.fixture
def mock_elements():
    return [
        UIElementRef(ref_id="@s1:e1", role="Edit", automation_id="txtSubjective", name="主訴"),
        UIElementRef(ref_id="@s1:e2", role="Edit", automation_id="txtObjective", name="客觀檢查"),
        UIElementRef(ref_id="@s1:e3", role="Edit", automation_id="txtAssessment", name="臨床評估"),
        UIElementRef(ref_id="@s1:e4", role="Edit", automation_id="txtPlan", name="治療計畫"),
        UIElementRef(ref_id="@s1:e5", role="Edit", automation_id="txtICD10", name="主診斷碼"),
    ]


def test_his_profiles_structure():
    assert "vision" in DEFAULT_HIS_PROFILES
    assert "yaosheng" in DEFAULT_HIS_PROFILES
    assert "minger" in DEFAULT_HIS_PROFILES
    assert "chihshi" in DEFAULT_HIS_PROFILES
    assert "soap_s" in DEFAULT_HIS_PROFILES["vision"]["fields"]


def test_field_matching(mock_elements):
    runner = AgentDesktopRunner()
    automator = HISPushAutomator(runner=runner)

    matched = automator.match_fields_to_refs("vision", mock_elements)
    assert matched["soap_s"].ref_id == "@s1:e1"
    assert matched["soap_o"].ref_id == "@s1:e2"
    assert matched["icd10"].ref_id == "@s1:e5"


def test_observe_act_verify_tier1(mock_elements):
    runner = AgentDesktopRunner()
    written_data = {}

    def mock_driver(action, **kwargs):
        if action == "snapshot":
            return mock_elements
        elif action == "set_value":
            written_data[kwargs["ref_id"]] = kwargs["value"]
        elif action == "get_value":
            return written_data.get(kwargs["ref_id"], "")

    runner.set_mock_driver(mock_driver)
    automator = HISPushAutomator(runner=runner)

    case = {
        "soap_s": "頭痛發燒",
        "soap_o": "耳溫 38.5C",
        "soap_a": "急性上呼吸道感染",
        "soap_p": "退燒藥開立三天",
        "icd10": "J06.9",
    }

    summary = automator.push_case_to_his("vision", "VisionHIS.exe", case)
    assert summary["status"] == "success"
    assert summary["results"]["soap_s"]["verified"] is True
    assert summary["results"]["soap_s"]["tier_used"] == "tier1_value_pattern"
    assert written_data["@s1:e1"] == "頭痛發燒"
    assert written_data["@s1:e5"] == "J06.9"


def test_stale_ref_handling(mock_elements):
    runner = AgentDesktopRunner()
    attempts = {"@s1:e1": 0}
    written_data = {}

    def mock_driver(action, **kwargs):
        if action == "snapshot":
            return mock_elements
        elif action == "set_value":
            ref = kwargs["ref_id"]
            if ref == "@s1:e1" and attempts[ref] == 0:
                attempts[ref] += 1
                raise StaleRefError("Generation stale")
            written_data[ref] = kwargs["value"]
        elif action == "get_value":
            return written_data.get(kwargs["ref_id"], "")

    runner.set_mock_driver(mock_driver)
    automator = HISPushAutomator(runner=runner)

    case = {"soap_s": "腹痛嘔吐"}
    summary = automator.push_case_to_his("vision", "VisionHIS.exe", case)
    assert summary["status"] == "success"
    assert summary["results"]["soap_s"]["retries"] == 1
    assert summary["results"]["soap_s"]["verified"] is True


def test_tier2_clipboard_fallback(mock_elements):
    runner = AgentDesktopRunner()
    pasted_data = {}

    def mock_driver(action, **kwargs):
        if action == "snapshot":
            return mock_elements
        elif action == "set_value":
            raise RuntimeError("UIA ValuePattern unsupported on legacy control")
        elif action == "paste":
            pasted_data[kwargs["ref_id"]] = kwargs["value"]
        elif action == "get_value":
            return pasted_data.get(kwargs["ref_id"], "")

    runner.set_mock_driver(mock_driver)
    automator = HISPushAutomator(runner=runner)

    case = {"soap_s": "膝關節僵硬"}
    summary = automator.push_case_to_his("vision", "VisionHIS.exe", case)
    assert summary["status"] == "success"
    assert summary["results"]["soap_s"]["tier_used"] == "tier2_clipboard"
    assert summary["results"]["soap_s"]["verified"] is True


def test_tier3_copy_card_fallback():
    runner = AgentDesktopRunner()
    runner.set_mock_driver(lambda action, **kwargs: [])  # empty snapshot
    automator = HISPushAutomator(runner=runner)

    case = {"soap_s": "無法抓取欄位之主訴"}
    summary = automator.push_case_to_his("vision", "VisionHIS.exe", case)
    assert summary["status"] == "partial"
    assert summary["results"]["soap_s"]["tier_used"] == "tier3_copy_card"
    assert "soap_s" in summary["fallback_copy_card"]


def test_process_his_push_job_cas(mock_elements, tmp_path, monkeypatch):
    from config import settings
    from elc_audit_engine.case_store.store import CaseStore
    from elc_audit_engine.bridge_queue import enqueue_job, get_job

    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))

    store = CaseStore()
    runner = AgentDesktopRunner()
    written_data = {}

    def mock_driver(action, **kwargs):
        if action == "snapshot":
            return mock_elements
        elif action == "set_value":
            written_data[kwargs["ref_id"]] = kwargs["value"]
        elif action == "get_value":
            return written_data.get(kwargs["ref_id"], "")

    runner.set_mock_driver(mock_driver)
    automator = HISPushAutomator(runner=runner)

    job_record = enqueue_job(
        store=store,
        s_type_code="HIS_PUSH",
        target_id="pat_123_case_01",
        extra_payload={
            "soap_s": "咳嗽有痰",
            "soap_o": "喉嚨發紅",
            "icd10": "J02.9",
        },
    )
    job_id = job_record["job_id"]

    job_before = get_job(store, job_id)
    assert job_before["status"] == "PENDING"

    summary = process_his_push_job(
        store=store,
        job_id=job_id,
        automator=automator,
        app_name="VisionHIS.exe",
        vendor_key="vision",
    )

    assert summary["status"] == "success"
    job_after = get_job(store, job_id)
    assert job_after["status"] == "SUCCESS"


def test_installer_generation(tmp_path):
    bundle = export_installer_bundle(base_dir=tmp_path)
    assert bundle["iss"].exists()
    assert bundle["bat"].exists()
    assert bundle["manifest"].exists()

    iss_text = bundle["iss"].read_text(encoding="utf-8")
    assert "AppName=Elcinsurrence Clinic Client Suite" in iss_text
    assert "LittleB.exe" in iss_text

    bat_text = bundle["bat"].read_text(encoding="utf-8")
    assert "@webbrain/mcp-server" in bat_text
    assert "LittleB.exe" in bat_text
