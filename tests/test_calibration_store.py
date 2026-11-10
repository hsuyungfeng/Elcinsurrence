from __future__ import annotations

import json
import pytest
from pathlib import Path
from elc_audit_engine.his_calibration import (
    CalibrationItem,
    CalibrationProfile,
    CalibrationStore,
    is_ready,
    new_machine_id,
)


def _sample_profile(machine_id: str | None = None) -> CalibrationProfile:
    mid = machine_id or new_machine_id()
    items = [
        CalibrationItem(
            item_key="soap_s.input",
            section="S",
            kind="writable",
            detected={"role": "Edit", "automation_id": "txtS"},
            suggested={"automation_id": "txtS"},
            confirmed={"automation_id": "txtS"},
            status="confirmed",
            confirmed_by="DR_01",
            confirmed_at="2026-11-09T18:00:00Z",
        ),
        CalibrationItem(
            item_key="save_button.action",
            section="SAVE_BUTTON",
            kind="save_action",
            detected={"role": "Button", "name": "儲存"},
            suggested={"name": "儲存"},
            confirmed={"name": "儲存"},
            status="confirmed",
            confirmed_by="DR_01",
            confirmed_at="2026-11-09T18:00:00Z",
        ),
        CalibrationItem(
            item_key="patient_id.check",
            section="PATIENT_ID",
            kind="identity_check",
            detected={"role": "Text", "automation_id": "lblPat"},
            suggested={"automation_id": "lblPat"},
            confirmed={"automation_id": "lblPat"},
            status="confirmed",
            confirmed_by="DR_01",
            confirmed_at="2026-11-09T18:00:00Z",
        ),
        CalibrationItem(
            item_key="icd10.advisory",
            section="ICD10",
            kind="advisory_only",
            status="pending",
        ),
    ]
    return CalibrationProfile(
        vendor_key="vision",
        machine_id=mid,
        vendor_version="2.1.0",
        schema_version=1,
        items=items,
        readback_test_passed=True,
        calibrated_at="2026-11-09T18:01:00Z",
        calibrated_by="DR_01",
    )


def test_calibration_store_roundtrip(tmp_path: Path):
    """Test 1: save 後 load 得到等值 profile（往返）"""
    store = CalibrationStore(base_dir=tmp_path)
    prof = _sample_profile()
    saved_path = store.save(prof)
    assert saved_path.exists()

    loaded = store.load(prof.vendor_key, prof.machine_id)
    assert loaded is not None
    assert loaded.vendor_key == prof.vendor_key
    assert loaded.machine_id == prof.machine_id
    assert loaded.readback_test_passed is True
    assert len(loaded.items) == len(prof.items)
    assert loaded.items[0].item_key == "soap_s.input"
    assert loaded.items[0].confirmed == {"automation_id": "txtS"}
    assert is_ready(loaded) is True


def test_calibration_store_partial_confirmation(tmp_path: Path):
    """Test 2: 只確認一半項目後 save/load，status 與 confirmed 保持，is_ready 為 False"""
    store = CalibrationStore(base_dir=tmp_path)
    prof = _sample_profile()
    # Mark save_button as pending
    prof.items[1].status = "pending"
    prof.items[1].confirmed = None
    store.save(prof)

    loaded = store.load(prof.vendor_key, prof.machine_id)
    assert loaded is not None
    assert loaded.items[1].status == "pending"
    assert loaded.items[1].confirmed is None
    assert is_ready(loaded) is False


def test_calibration_store_atomic_write_preserves_on_failure(tmp_path: Path, monkeypatch):
    """Test 3: 寫入使用暫存檔加 os.replace；寫入中途失敗時既有檔案不被截斷"""
    store = CalibrationStore(base_dir=tmp_path)
    prof = _sample_profile()
    original_path = store.save(prof)
    original_content = original_path.read_text(encoding="utf-8")

    def broken_replace(src, dst):
        raise OSError("Disk failure during replace")

    monkeypatch.setattr("os.replace", broken_replace)

    # Attempt second write which will fail
    prof2 = _sample_profile(machine_id=prof.machine_id)
    prof2.vendor_version = "9.9.9"

    with pytest.raises(OSError):
        store.save(prof2)

    # Original file must remain untouched and uncorrupted
    assert original_path.read_text(encoding="utf-8") == original_content


def test_calibration_store_load_nonexistent_returns_none(tmp_path: Path):
    """Test 4: 檔案不存在時 load 回傳 None"""
    store = CalibrationStore(base_dir=tmp_path)
    assert store.load("vision", "non-existent-uuid") is None


def test_calibration_store_unsupported_schema_version(tmp_path: Path):
    """Test 5: schema_version 不是 1 時 load 拋出 ValueError"""
    store = CalibrationStore(base_dir=tmp_path)
    file_path = store.path_for("vision", "mach1")
    file_path.write_text(json.dumps({"schema_version": 2, "vendor_key": "vision", "machine_id": "mach1"}), encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        store.load("vision", "mach1")
    assert "Unsupported schema_version" in str(exc.value)


def test_calibration_store_serialized_json_contains_no_value_key(tmp_path: Path):
    """Test 6: 序列化後的 JSON 字串不含任何名為 'value' 的鍵"""
    store = CalibrationStore(base_dir=tmp_path)
    prof = _sample_profile()
    saved_path = store.save(prof)
    raw_json = saved_path.read_text(encoding="utf-8")

    parsed = json.loads(raw_json)

    def _assert_no_value_key(node):
        if isinstance(node, dict):
            assert "value" not in node, f"Found prohibited 'value' key in {node}"
            for v in node.values():
                _assert_no_value_key(v)
        elif isinstance(node, list):
            for it in node:
                _assert_no_value_key(it)

    _assert_no_value_key(parsed)


def test_calibration_store_path_traversal_rejected(tmp_path: Path):
    """Test 7: 檔名為 <vendor_key>-<machine_id>.json，vendor_key 或 machine_id 含路徑分隔字元時拋出 ValueError"""
    store = CalibrationStore(base_dir=tmp_path)

    with pytest.raises(ValueError):
        store.path_for("../evil_vendor", "mach1")

    with pytest.raises(ValueError):
        store.path_for("vision", "../../etc/passwd")

    with pytest.raises(ValueError):
        store.path_for("vision/sub", "mach1")
