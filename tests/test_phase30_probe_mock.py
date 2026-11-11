"""Phase 30-09: 替身視窗 MockHIS 探針寫入與讀回測試。

安全約束：
- 僅對 MockHIS 替身視窗模擬操作，絕不接觸任何真實 HIS 或病歷資料。
- 驗證隨機 nonce 探針的「寫入 → 讀回 → 比對」完整邏輯。
- 驗證比對一致時 readback_test_passed 為 True；不一致或異常時嚴格為 False（Fail-Closed）。
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from deploy.windows_agent.calibration_wizard import (
    CalibrationWizard,
    NotReadyError,
    PROBE_TEXT,
)
from elc_audit_engine.agent_desktop_bridge import (
    AgentDesktopRunner,
    UIElementRef,
)
from elc_audit_engine.his_calibration import (
    CalibrationItem,
    CalibrationProfile,
    CalibrationStore,
    is_ready,
)


class MockHISTextDriver:
    """模擬 MockHIS 視窗的記憶體 Text 欄位驅動器。"""

    def __init__(self, window_title: str = "VisionHIS - MockHIS（測試替身，非真實 HIS）"):
        self.window_title = window_title
        self.fields: Dict[str, str] = {
            "soap_s": "",
            "soap_o": "",
            "soap_a": "",
            "soap_p": "",
        }
        self.window_open = True
        self.written_history: List[str] = []

    def snapshot(self, app_name: str) -> List[UIElementRef]:
        if not self.window_open or "MockHIS" not in self.window_title:
            return []
        return [
            UIElementRef(ref_id="@ref/s", role="Edit", name="主訴 (S)", automation_id="txtS", value=self.fields["soap_s"]),
            UIElementRef(ref_id="@ref/o", role="Edit", name="客觀檢查 (O)", automation_id="txtO", value=self.fields["soap_o"]),
            UIElementRef(ref_id="@ref/a", role="Edit", name="評估 (A)", automation_id="txtA", value=self.fields["soap_a"]),
            UIElementRef(ref_id="@ref/p", role="Edit", name="處置 (P)", automation_id="txtP", value=self.fields["soap_p"]),
            UIElementRef(ref_id="@ref/pid", role="Edit", name="病患代號", automation_id="txtPid", value="TEST-000000"),
            UIElementRef(ref_id="@ref/save", role="Button", name="儲存", automation_id="btnSave", value=""),
        ]

    def set_value(self, ref_id: str, value: str) -> None:
        if not self.window_open:
            raise RuntimeError("MockHIS window is not available")
        self.written_history.append(value)
        if ref_id in ("@ref/s", "txtS", "soap_s"):
            self.fields["soap_s"] = value
        elif ref_id in ("@ref/o", "txtO", "soap_o"):
            self.fields["soap_o"] = value
        elif ref_id in ("@ref/a", "txtA", "soap_a"):
            self.fields["soap_a"] = value
        elif ref_id in ("@ref/p", "txtP", "soap_p"):
            self.fields["soap_p"] = value

    def get_value(self, ref_id: str) -> str:
        if not self.window_open:
            raise RuntimeError("MockHIS window is not available")
        if ref_id in ("@ref/s", "txtS", "soap_s"):
            return self.fields["soap_s"]
        elif ref_id in ("@ref/o", "txtO", "soap_o"):
            return self.fields["soap_o"]
        elif ref_id in ("@ref/a", "txtA", "soap_a"):
            return self.fields["soap_a"]
        elif ref_id in ("@ref/p", "txtP", "soap_p"):
            return self.fields["soap_p"]
        return ""


def _build_mock_wizard(store: CalibrationStore, driver: MockHISTextDriver) -> CalibrationWizard:
    """建立指向 MockHIS 替身驅動器的 CalibrationWizard 實體。"""
    wizard = CalibrationWizard(
        vendor_key="vision",
        app_name="MockHIS.exe",
        runner_snapshot_fn=lambda app: driver.snapshot(app),
        store=store,
        machine_id="test-mock-machine-01",
        actor_id="test-tester",
    )
    wizard.start()
    # 填入並確認必要的 6 項校正項目
    for item in wizard.items:
        if item.kind in ("writable", "identity_check", "save_action"):
            item.status = "confirmed"
            item.confirmed = {"name": (item.detected or {}).get("name", ""), "automation_id": (item.detected or {}).get("automation_id", "")}
    return wizard


def test_probe_write_and_readback_success_marks_passed_true(tmp_path: Path):
    """測試 1: 寫入隨機 nonce 探針到 MockHIS，讀回並比對 hash，驗證 readback_test_passed 正確標記為 True"""
    store = CalibrationStore(base_dir=tmp_path)
    driver = MockHISTextDriver()
    wizard = _build_mock_wizard(store, driver)

    # 產生隨機 nonce（例如 PROBE-<uuid>）
    nonce = f"PROBE-{uuid.uuid4().hex[:12].upper()}"
    nonce_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()

    def mock_write_and_read(probe: str) -> str:
        # 寫入 MockHIS soap_s 欄位並讀回
        driver.set_value("soap_s", probe)
        return driver.get_value("soap_s")

    # 執行探針寫入與讀回
    passed = wizard.readback_test(mock_write_and_read)

    assert passed is True
    assert wizard.profile is not None
    assert wizard.profile.readback_test_passed is True
    assert driver.fields["soap_s"] == PROBE_TEXT

    # 驗證自訂 nonce 讀回計算雜湊一致性
    readback_val = mock_write_and_read(nonce)
    readback_hash = hashlib.sha256(readback_val.encode("utf-8")).hexdigest()
    assert readback_hash == nonce_hash

    # 當全項確認且探針通過時，finalize 應能順利存檔
    saved_path = wizard.finalize()
    assert saved_path.exists()

    loaded = store.load("vision", "test-mock-machine-01")
    assert loaded is not None
    assert loaded.readback_test_passed is True
    assert is_ready(loaded) is True


def test_probe_readback_mismatch_marks_passed_false_and_blocks_finalize(tmp_path: Path):
    """測試 2: 當讀回值不一致（模擬欄位焦點跑掉或文字被截斷），readback_test_passed 必須為 False，且阻絕 finalize"""
    store = CalibrationStore(base_dir=tmp_path)
    driver = MockHISTextDriver()
    wizard = _build_mock_wizard(store, driver)

    # 模擬讀回值不一致的情境（回傳被截斷或空值）
    def corrupted_write_and_read(probe: str) -> str:
        driver.set_value("soap_s", probe)
        return "CORRUPTED-VALUE"

    passed = wizard.readback_test(corrupted_write_and_read)

    assert passed is False
    assert wizard.profile is not None
    assert wizard.profile.readback_test_passed is False

    # 驗證 fail-closed：未通過讀寫測試時，finalize 必須拋出 NotReadyError
    with pytest.raises(NotReadyError, match="readback test passed"):
        wizard.finalize()


def test_probe_readback_exception_handled_gracefully(tmp_path: Path):
    """測試 3: 當底層 UIA 出錯或視窗意外關閉拋出例外時，readback_test_passed 保持 False，不崩潰"""
    store = CalibrationStore(base_dir=tmp_path)
    driver = MockHISTextDriver()
    driver.window_open = False  # 模擬視窗不存在
    wizard = _build_mock_wizard(store, driver)

    def failing_write_and_read(probe: str) -> str:
        driver.set_value("soap_s", probe)
        return driver.get_value("soap_s")

    passed = wizard.readback_test(failing_write_and_read)

    assert passed is False
    assert wizard.profile is not None
    assert wizard.profile.readback_test_passed is False


def test_probe_nonce_hash_uniqueness_and_no_phi():
    """測試 4: 探針隨機 nonce 具備唯一性，且格式嚴格遵循 PROBE- 前綴，不含任何病歷資料"""
    nonces = [f"PROBE-{uuid.uuid4().hex[:12].upper()}" for _ in range(50)]
    # 確認無重複
    assert len(set(nonces)) == 50
    # 確認格式安全無病歷敏感字眼
    for n in nonces:
        assert n.startswith("PROBE-")
        assert len(n) == 18
        assert all(c.isalnum() or c == "-" for c in n)
