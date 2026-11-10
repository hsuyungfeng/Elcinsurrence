from __future__ import annotations

import pytest
from elc_audit_engine.his_calibration import (
    CalibrationItem,
    CalibrationProfile,
    build_items_from_detected,
    is_ready,
    new_machine_id,
    selector_for,
)


def test_advisory_only_selector_always_none():
    """Test 1: kind=advisory_only 的項目呼叫 selector_for 回傳 None，即使 confirmed 有值"""
    item = CalibrationItem(
        item_key="icd10.advisory",
        section="ICD10",
        kind="advisory_only",
        confirmed={"automation_id": "txtICD10"},
        status="confirmed",
    )
    assert selector_for(item) is None


def test_is_ready_false_when_writable_pending():
    """Test 2: 含一個 writable 項目 status=pending 時 is_ready 為 False"""
    items = [
        CalibrationItem(
            item_key="soap_s.input",
            section="S",
            kind="writable",
            confirmed=None,
            status="pending",
        ),
        CalibrationItem(
            item_key="save_button.action",
            section="SAVE_BUTTON",
            kind="save_action",
            confirmed={"name": "儲存"},
            status="confirmed",
        ),
        CalibrationItem(
            item_key="patient_id.check",
            section="PATIENT_ID",
            kind="identity_check",
            confirmed={"automation_id": "txtPatientId"},
            status="confirmed",
        ),
    ]
    prof = CalibrationProfile(
        vendor_key="vision",
        machine_id=new_machine_id(),
        items=items,
        readback_test_passed=True,
    )
    assert is_ready(prof) is False


def test_is_ready_false_when_readback_not_passed():
    """Test 3: 所有 writable/save_action/identity_check 皆 confirmed 但 readback_test_passed=False 時 is_ready 為 False"""
    items = [
        CalibrationItem(
            item_key="soap_s.input",
            section="S",
            kind="writable",
            confirmed={"automation_id": "txtS"},
            status="confirmed",
        ),
        CalibrationItem(
            item_key="save_button.action",
            section="SAVE_BUTTON",
            kind="save_action",
            confirmed={"name": "儲存"},
            status="confirmed",
        ),
        CalibrationItem(
            item_key="patient_id.check",
            section="PATIENT_ID",
            kind="identity_check",
            confirmed={"automation_id": "txtPatientId"},
            status="confirmed",
        ),
    ]
    prof = CalibrationProfile(
        vendor_key="vision",
        machine_id=new_machine_id(),
        items=items,
        readback_test_passed=False,
    )
    assert is_ready(prof) is False


def test_is_ready_true_and_advisory_pending_ignored():
    """Test 4: 全部條件滿足時 is_ready 為 True；advisory 項目為 pending 不影響 is_ready"""
    items = [
        CalibrationItem(
            item_key="soap_s.input",
            section="S",
            kind="writable",
            confirmed={"automation_id": "txtS"},
            status="confirmed",
        ),
        CalibrationItem(
            item_key="save_button.action",
            section="SAVE_BUTTON",
            kind="save_action",
            confirmed={"name": "儲存"},
            status="confirmed",
        ),
        CalibrationItem(
            item_key="patient_id.check",
            section="PATIENT_ID",
            kind="identity_check",
            confirmed={"automation_id": "txtPatientId"},
            status="corrected",
        ),
        # Advisory items in pending or skipped state
        CalibrationItem(
            item_key="icd10.advisory",
            section="ICD10",
            kind="advisory_only",
            status="pending",
        ),
        CalibrationItem(
            item_key="order.advisory",
            section="ORDER",
            kind="advisory_only",
            status="skipped",
        ),
    ]
    prof = CalibrationProfile(
        vendor_key="vision",
        machine_id=new_machine_id(),
        items=items,
        readback_test_passed=True,
    )
    assert is_ready(prof) is True


def test_build_items_strips_value_key():
    """Test 5: build_items_from_detected 不保留 value 鍵（輸入含 value 時輸出 detected 不含該鍵）"""
    detected_elements = [
        {
            "role": "Button",
            "name": "儲存病歷",
            "automation_id": "btnSave",
            "control_type": "Button",
            "window_title": "HIS Main",
            "value": "PATIENT_PHI_SHOULD_BE_DROPPED",
        }
    ]
    items = build_items_from_detected("vision", detected_elements)
    save_item = next(it for it in items if it.section == "SAVE_BUTTON")
    assert "value" not in save_item.detected
    assert save_item.detected.get("name") == "儲存病歷"
    assert save_item.suggested == {"automation_id": "btnSave"}


def test_unknown_status_or_kind_or_section_raises_value_error():
    """Test 6: 未知 status、kind 或 section 字串拋出 ValueError"""
    with pytest.raises(ValueError):
        CalibrationItem(
            item_key="test",
            section="UNKNOWN_SECTION",
            kind="writable",
            status="pending",
        )

    with pytest.raises(ValueError):
        CalibrationItem(
            item_key="test",
            section="S",
            kind="invalid_kind",
            status="pending",
        )

    with pytest.raises(ValueError):
        CalibrationItem(
            item_key="test",
            section="S",
            kind="writable",
            status="unknown_status",
        )


def test_build_items_icd10_order_med_are_advisory_only():
    """Test 7: build_items_from_detected 產生的 ICD10、ORDER、MED 項目 kind 皆為 advisory_only"""
    items = build_items_from_detected("vision", [])
    advisory_sections = {"ICD10", "ORDER", "MED"}
    advisory_items = [it for it in items if it.section in advisory_sections]
    assert len(advisory_items) == 3
    for it in advisory_items:
        assert it.kind == "advisory_only"
        assert selector_for(it) is None
