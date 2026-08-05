"""P1-3 路徑穿越防線測試（safe_filename 與三處呼叫點）。"""

from __future__ import annotations

import json
import os

import pytest

from elc_audit_engine.comparator.models import CaseComparisonResult
from elc_audit_engine.generators.appeal import write_appeal
from elc_audit_engine.generators.reinforcement_report import write_report
from elc_audit_engine.record_aggregator.providers import LocalFileProvider
from elc_audit_engine.safe_paths import UnsafeIdentifierError, safe_filename

# --- safe_filename 單元 -------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "12345",
        "64140C",
        "A1_B2-C3",
        "病歷A1",  # 中文須通過（2026-08-05 裁示：健保檔案可能含中文）
        "案件_001",
    ],
)
def test_safe_filename_accepts_legit_identifiers(value):
    assert safe_filename(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "../etc/passwd",
        "../../root/.ssh/id_rsa",
        "rec/../x",
        "a/b",
        "a\\b",  # Windows 分隔符也要擋
        "..",
        ".",
        "",
        "   ",
        "a b",  # 空白不在白名單
        "a.json",  # 點號不在白名單（避免副檔名混淆）
        "case\x00null",
        "\n",
    ],
)
def test_safe_filename_rejects_traversal_and_bad_chars(value):
    with pytest.raises(UnsafeIdentifierError):
        safe_filename(value, "test_field")


def test_safe_filename_rejects_none():
    with pytest.raises(UnsafeIdentifierError):
        safe_filename(None, "patient_id")


def test_safe_filename_error_names_the_field():
    """錯誤訊息須指出欄位來源，否則穿越來自哪個欄位無從定位。"""
    with pytest.raises(UnsafeIdentifierError, match="patient_id"):
        safe_filename("../x", "patient_id")


def test_safe_filename_does_not_silently_rewrite():
    """關鍵：拒絕而非清洗——A/1 與 A_1 不得收斂成同一檔名（PHI 覆寫風險）。"""
    assert safe_filename("A_1") == "A_1"
    with pytest.raises(UnsafeIdentifierError):
        safe_filename("A/1")


# --- 呼叫點：讀取型（providers） ----------------------------------------


def test_local_provider_rejects_traversal_patient_id(tmp_path):
    provider = LocalFileProvider(tmp_path)
    with pytest.raises(UnsafeIdentifierError):
        provider.fetch_records("../../etc")


def test_local_provider_still_reads_legit_patient(tmp_path):
    """防線不得誤傷正常路徑。"""
    patient_dir = tmp_path / "P123"
    patient_dir.mkdir()
    (patient_dir / "records.json").write_text(
        json.dumps({"diagnoses": [], "orders": [], "labs": [], "imaging": []}),
        encoding="utf-8",
    )
    # 不拋例外即為通過（空病歷回空 list）
    assert LocalFileProvider(tmp_path).fetch_records("P123") == []


# --- 呼叫點：寫入型（report / appeal） ----------------------------------


def _empty_comparison() -> CaseComparisonResult:
    return CaseComparisonResult(case_record_no="X1")


def test_write_report_rejects_traversal_case_record_no(tmp_path):
    with pytest.raises(UnsafeIdentifierError):
        write_report(tmp_path, "../../evil", _empty_comparison())


def test_write_report_does_not_escape_output_dir(tmp_path):
    """回歸：即使拋錯前也不得已在 output_dir 外留下檔案。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    target = tmp_path / "out"
    target.mkdir()
    with pytest.raises(UnsafeIdentifierError):
        write_report(target, "../outside/leaked", _empty_comparison())
    assert list(outside.iterdir()) == []


def test_write_report_accepts_chinese_record_no(tmp_path):
    report_path, tracking_path = write_report(
        tmp_path, "病歷001", _empty_comparison()
    )
    assert os.path.isfile(report_path)
    assert os.path.isfile(tracking_path)
