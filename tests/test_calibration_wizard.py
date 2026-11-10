from __future__ import annotations

import pytest
from pathlib import Path
from typing import Any, Dict, List

from deploy.windows_agent.calibration_wizard import (
    CalibrationWizard,
    NotReadyError,
    PROBE_TEXT,
)
from elc_audit_engine.his_calibration import CalibrationStore, is_ready, new_machine_id


def _make_fake_snapshot():
    return [
        {
            "role": "Edit",
            "name": "主訴",
            "automation_id": "txtSubjective",
            "control_type": "Edit",
            "value": "CONFIDENTIAL_PATIENT_PHI_1",
        },
        {
            "role": "Edit",
            "name": "客觀檢查",
            "automation_id": "txtObjective",
            "control_type": "Edit",
            "value": "CONFIDENTIAL_PATIENT_PHI_2",
        },
        {
            "role": "Edit",
            "name": "臨床評估",
            "automation_id": "txtAssessment",
            "control_type": "Edit",
            "value": "CONFIDENTIAL_PATIENT_PHI_3",
        },
        {
            "role": "Edit",
            "name": "治療計畫",
            "automation_id": "txtPlan",
            "control_type": "Edit",
            "value": "CONFIDENTIAL_PATIENT_PHI_4",
        },
        {
            "role": "Edit",
            "name": "病歷號",
            "automation_id": "txtPatientId",
            "control_type": "Edit",
            "value": "P12345678",
        },
        {
            "role": "Button",
            "name": "儲存病歷",
            "automation_id": "btnSave",
            "control_type": "Button",
        },
        {
            "role": "Edit",
            "name": "主診斷碼",
            "automation_id": "txtICD10",
            "control_type": "Edit",
        },
    ]


def test_test1_wizard_start_items_sequence_and_single_current(tmp_path: Path):
    """Test 1: start() 以注入的 snapshot_fn 取得元素後，items 依序為 S、O、A、P、PATIENT_ID、SAVE_BUTTON、ICD10、ORDER、MED，current() 一次只回傳一項"""
    store = CalibrationStore(base_dir=tmp_path)
    wizard = CalibrationWizard(
        vendor_key="vision",
        app_name="VisionHIS.exe",
        runner_snapshot_fn=lambda _app: _make_fake_snapshot(),
        store=store,
        machine_id=new_machine_id(),
        actor_id="dr_lin",
    )
    wizard.start()

    expected_sequence = [
        "S",
        "O",
        "A",
        "P",
        "PATIENT_ID",
        "SAVE_BUTTON",
        "ICD10",
        "ORDER",
        "MED",
    ]
    actual_sequence = [it.section for it in wizard.items]
    assert actual_sequence == expected_sequence

    first_item = wizard.current()
    assert first_item is not None
    assert first_item.section == "S"
    assert first_item.item_key == "soap_s.input"


def test_test2_current_detected_strips_value_and_contains_keys(tmp_path: Path):
    """Test 2: current() 回傳的 detected 不含 value 鍵，且含 role、automation_id、name、control_type"""
    store = CalibrationStore(base_dir=tmp_path)
    wizard = CalibrationWizard(
        vendor_key="vision",
        app_name="VisionHIS.exe",
        runner_snapshot_fn=lambda _app: _make_fake_snapshot(),
        store=store,
        machine_id=new_machine_id(),
        actor_id="dr_lin",
    )
    wizard.start()

    item = wizard.current()
    assert item is not None
    assert "value" not in item.detected
    assert item.detected.get("role") == "Edit"
    assert item.detected.get("automation_id") == "txtSubjective"
    assert item.detected.get("name") == "主訴"
    assert item.detected.get("control_type") == "Edit"


def test_test3_advisory_only_confirm_raises_value_error(tmp_path: Path):
    """Test 3: 對 advisory_only 項目呼叫 confirm() 拋出 ValueError"""
    store = CalibrationStore(base_dir=tmp_path)
    wizard = CalibrationWizard(
        vendor_key="vision",
        app_name="VisionHIS.exe",
        runner_snapshot_fn=lambda _app: _make_fake_snapshot(),
        store=store,
        machine_id=new_machine_id(),
        actor_id="dr_lin",
    )
    wizard.start()

    # Advance past S, O, A, P, PATIENT_ID, SAVE_BUTTON to reach ICD10
    for _ in range(6):
        wizard.confirm()

    advisory_item = wizard.current()
    assert advisory_item is not None
    assert advisory_item.section == "ICD10"
    assert advisory_item.kind == "advisory_only"

    with pytest.raises(ValueError, match="advisory_only"):
        wizard.confirm()


def test_test4_confirm_and_correct_status_and_confirmed_by(tmp_path: Path):
    """Test 4: confirm() 與 correct(new_selector) 後，status 分別為 confirmed 與 corrected，confirmed_by 與 confirmed_at 皆有值；confirmed_by 為空字串時拋錯"""
    store = CalibrationStore(base_dir=tmp_path)
    wizard = CalibrationWizard(
        vendor_key="vision",
        app_name="VisionHIS.exe",
        runner_snapshot_fn=lambda _app: _make_fake_snapshot(),
        store=store,
        machine_id=new_machine_id(),
        actor_id="dr_lin",
    )
    wizard.start()

    # 1. confirm() S
    s_item = wizard.confirm()
    assert s_item.status == "confirmed"
    assert s_item.confirmed == {"automation_id": "txtSubjective"}
    assert s_item.confirmed_by == "dr_lin"
    assert s_item.confirmed_at is not None

    # 2. correct() O with new selector
    o_item = wizard.correct({"automation_id": "txtCustomO"})
    assert o_item.status == "corrected"
    assert o_item.confirmed == {"automation_id": "txtCustomO"}
    assert o_item.confirmed_by == "dr_lin"
    assert o_item.confirmed_at is not None

    # 3. confirmed_by empty string raises error
    with pytest.raises(ValueError, match="actor_id"):
        wizard.confirm(actor_id="")

    with pytest.raises(ValueError, match="actor_id"):
        wizard.correct({"automation_id": "txtCustomA"}, actor_id="   ")


def test_test5_skip_writable_item_causes_finalize_to_raise(tmp_path: Path):
    """Test 5: skip() 對 writable 項目使 finalize() 拋出 NotReadyError"""
    store = CalibrationStore(base_dir=tmp_path)
    wizard = CalibrationWizard(
        vendor_key="vision",
        app_name="VisionHIS.exe",
        runner_snapshot_fn=lambda _app: _make_fake_snapshot(),
        store=store,
        machine_id=new_machine_id(),
        actor_id="dr_lin",
    )
    wizard.start()

    # Skip S (writable)
    s_item = wizard.skip()
    assert s_item.status == "skipped"

    # Confirm remaining
    for _ in range(5):
        wizard.confirm()

    # Pass readback
    wizard.readback_test(lambda txt: txt)

    with pytest.raises(NotReadyError):
        wizard.finalize()


def test_test6_readback_not_passed_causes_finalize_to_raise(tmp_path: Path):
    """Test 6: 未執行 readback（readback_test_passed=False）時 finalize() 拋出 NotReadyError，不存檔"""
    store = CalibrationStore(base_dir=tmp_path)
    machine_id = new_machine_id()
    wizard = CalibrationWizard(
        vendor_key="vision",
        app_name="VisionHIS.exe",
        runner_snapshot_fn=lambda _app: _make_fake_snapshot(),
        store=store,
        machine_id=machine_id,
        actor_id="dr_lin",
    )
    wizard.start()

    # Confirm all 6 required items
    for _ in range(6):
        wizard.confirm()

    # Without calling readback_test (readback_test_passed remains False)
    with pytest.raises(NotReadyError):
        wizard.finalize()

    # Ensure nothing was saved
    assert store.load("vision", machine_id) is None


def test_test7_all_conditions_met_finalize_saves_and_is_ready(tmp_path: Path):
    """Test 7: 全部條件滿足時 finalize() 呼叫 CalibrationStore.save，之後 is_ready 為 True"""
    store = CalibrationStore(base_dir=tmp_path)
    machine_id = new_machine_id()
    wizard = CalibrationWizard(
        vendor_key="vision",
        app_name="VisionHIS.exe",
        runner_snapshot_fn=lambda _app: _make_fake_snapshot(),
        store=store,
        machine_id=machine_id,
        actor_id="dr_lin",
    )
    wizard.start()

    # Confirm 6 critical items: S, O, A, P, PATIENT_ID, SAVE_BUTTON
    for _ in range(6):
        wizard.confirm()

    # Skip advisory items
    for _ in range(3):
        wizard.skip()

    # Pass readback test
    assert wizard.readback_test(lambda txt: txt) is True

    save_path = wizard.finalize()
    assert save_path.exists()

    loaded_profile = store.load("vision", machine_id)
    assert loaded_profile is not None
    assert is_ready(loaded_profile) is True
    assert loaded_profile.calibrated_by == "dr_lin"
    assert loaded_profile.calibrated_at is not None


def test_test8_readback_mismatch_fails_readback_passed(tmp_path: Path):
    """Test 8: readback 以注入的 write_and_read(text) 執行，寫入值與讀回值不一致時 readback_test_passed=False"""
    store = CalibrationStore(base_dir=tmp_path)
    wizard = CalibrationWizard(
        vendor_key="vision",
        app_name="VisionHIS.exe",
        runner_snapshot_fn=lambda _app: _make_fake_snapshot(),
        store=store,
        machine_id=new_machine_id(),
        actor_id="dr_lin",
    )
    wizard.start()

    # Injected write_and_read returns corrupted text
    passed = wizard.readback_test(lambda txt: "CORRUPTED_TEXT")
    assert passed is False
    assert wizard.profile.readback_test_passed is False
