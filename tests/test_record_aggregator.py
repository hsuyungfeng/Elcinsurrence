"""病歷彙整器測試（04-01-PLAN Task 1-3）。

涵蓋：D-01 Provider 介面（ABC＋切換）、D-02 四類紀錄型別、D-03 時間窗
過濾＋排序、D-04 本地 Provider 讀 records.json、D-05 降級語意（病歷缺席
→ degraded；JSON 損毀 → RecordProviderError）、D-08 時間窗位移。
"""

import json
import os
from datetime import date

import pytest

from elc_audit_engine.record_aggregator import (
    AggregationResult,
    LocalFileProvider,
    PatientRecordsNotFound,
    RecordProvider,
    RecordProviderError,
    VisitRecord,
    build_timeline,
)
from elc_audit_engine.record_aggregator.models import ExamRecord, ImagingRecord, LabRecord

FIXTURE_ROOT = os.path.join(os.path.dirname(__file__), "fixtures", "records")
PATIENT_A = os.path.join(FIXTURE_ROOT, "patient_A")


# ---------------------------------------------------------------- Provider 介面

def test_record_provider_is_abstract():
    """D-01：RecordProvider 為 ABC，不可直接實例化。"""
    with pytest.raises(TypeError):
        RecordProvider()  # type: ignore[abstract]


def test_local_provider_reads_all_categories():
    """D-02/D-04：本地 Provider 讀取四類紀錄，欄位正確。"""
    provider = LocalFileProvider(FIXTURE_ROOT)
    records = provider.fetch_records("patient_A")

    visits = [r for r in records if isinstance(r, VisitRecord)]
    labs = [r for r in records if isinstance(r, LabRecord)]
    exams = [r for r in records if isinstance(r, ExamRecord)]
    imaging = [r for r in records if isinstance(r, ImagingRecord)]

    assert len(visits) == 2
    assert len(labs) == 2
    assert len(exams) == 1
    assert len(imaging) == 2

    visit = visits[0]
    assert visit.clinic == "骨科"
    assert "手腕扭傷" in visit.soap_text
    assert visit.diagnoses == ("S6300XA",)

    lab = labs[0]
    assert lab.test_name == "HbA1c"
    assert lab.result == "7.2"
    assert lab.unit == "%"
    assert lab.abnormal is True

    imaging = imaging[0]
    assert imaging.modality == "CT"
    assert imaging.image_refs == ("ct_chest_001.dcm", "ct_chest_002.dcm")


def test_local_provider_parses_8digit_date():
    """D-04：8 碼 YYYYMMDD 日期相容（重用 parse_flexible_date）。"""
    provider = LocalFileProvider(FIXTURE_ROOT)
    records = provider.fetch_records("patient_A")
    labs = [r for r in records if isinstance(r, LabRecord)]
    old_lab = [r for r in labs if r.test_name == "白血球"][0]
    assert old_lab.date == date(2024, 12, 1)


def test_local_provider_missing_patient_raises_patient_not_found():
    """D-05：病患目錄不存在 → PatientRecordsNotFound（降級情境）。"""
    provider = LocalFileProvider(FIXTURE_ROOT)
    with pytest.raises(PatientRecordsNotFound):
        provider.fetch_records("no_such_patient")


def test_local_provider_corrupt_json_raises_provider_error(tmp_path):
    """D-05：JSON 損毀 → RecordProviderError（infra 故障，不降級）。"""
    patient_dir = tmp_path / "corrupt"
    patient_dir.mkdir()
    (patient_dir / "records.json").write_text("{not valid json", encoding="utf-8")
    provider = LocalFileProvider(str(tmp_path))
    with pytest.raises(RecordProviderError):
        provider.fetch_records("corrupt")


def test_local_provider_bad_date_raises_provider_error(tmp_path):
    """缺 date 或日期無法解析 → RecordProviderError。"""
    patient_dir = tmp_path / "bad_date"
    patient_dir.mkdir()
    (patient_dir / "records.json").write_text(
        json.dumps({"visits": [{"date": "not-a-date", "clinic": "內科"}]}),
        encoding="utf-8",
    )
    provider = LocalFileProvider(str(tmp_path))
    with pytest.raises(RecordProviderError):
        provider.fetch_records("bad_date")


# ---------------------------------------------------------------- 彙整器

def test_build_timeline_filters_by_window_and_sorts():
    """D-03：窗內（含邊界）紀錄保留、窗外計入 excluded；依日期排序。"""
    provider = LocalFileProvider(FIXTURE_ROOT)
    result = build_timeline(provider, "patient_A", end_date=date(2026, 8, 1))

    assert result.degraded is False
    timeline = result.timeline
    assert timeline is not None
    assert timeline.window_start == date(2026, 2, 1)
    assert timeline.window_end == date(2026, 8, 1)

    # visits：2026-07-20 在窗內、2025-05-01 窗外
    assert len(timeline.visits) == 1
    assert timeline.visits[0].date == date(2026, 7, 20)
    # labs：2026-02-15 在窗內（邊界）、20241201 窗外
    assert [r.date for r in timeline.labs] == [date(2026, 2, 15)]
    # exams：窗內
    assert len(timeline.exams) == 1
    # imaging：2026-06-01 窗內、2025-11-01 窗外
    assert [r.date for r in timeline.imaging] == [date(2026, 6, 1)]

    assert timeline.excluded_counts == {
        "visits": 1, "labs": 1, "exams": 0, "imaging": 1
    }
    assert timeline.source_provider == f"local:{FIXTURE_ROOT}"


def test_build_timeline_sorts_multiple_records_by_date():
    """D-03：窗內多筆依日期排序（升冪）。"""
    records = [
        VisitRecord(patient_id="P1", date=date(2026, 7, 1), clinic="A"),
        VisitRecord(patient_id="P1", date=date(2026, 3, 1), clinic="B"),
        VisitRecord(patient_id="P1", date=date(2026, 5, 1), clinic="C"),
    ]

    class DummyProvider(RecordProvider):
        name = "dummy"

        def fetch_records(self, patient_id):
            return list(records)

    result = build_timeline(DummyProvider(), "P1", end_date=date(2026, 8, 1))
    assert [r.clinic for r in result.timeline.visits] == ["B", "C", "A"]


def test_build_timeline_degrades_when_patient_not_found():
    """D-05/C5：病歷缺席 → degraded=True、timeline=None、reason 說明。"""
    provider = LocalFileProvider(FIXTURE_ROOT)
    result = build_timeline(provider, "no_such_patient", end_date=date(2026, 8, 1))
    assert result.degraded is True
    assert result.timeline is None
    assert "no_such_patient" in result.reason


def test_build_timeline_empty_records_not_degraded(tmp_path):
    """D-05：病患存在但無紀錄 → 正常空時間軸（degraded=False）。"""
    patient_dir = tmp_path / "empty"
    patient_dir.mkdir()
    (patient_dir / "records.json").write_text("{}", encoding="utf-8")
    provider = LocalFileProvider(str(tmp_path))
    result = build_timeline(provider, "empty", end_date=date(2026, 8, 1))
    assert result.degraded is False
    assert result.timeline is not None
    assert result.timeline.visits == ()
    assert result.timeline.labs == ()


def test_build_timeline_custom_window_and_end_date(tmp_path):
    """D-03：自訂 end_date 與 months 生效。"""
    patient_dir = tmp_path / "p"
    patient_dir.mkdir()
    (patient_dir / "records.json").write_text(
        json.dumps({
            "visits": [
                {"date": "2026-06-01", "clinic": "內科"},
                {"date": "2026-04-01", "clinic": "內科"},
            ]
        }),
        encoding="utf-8",
    )
    provider = LocalFileProvider(str(tmp_path))
    # months=3, end=2026-07-01 → window [2026-04-01, 2026-07-01]
    result = build_timeline(provider, "p", months=3, end_date=date(2026, 7, 1))
    assert result.timeline.window_start == date(2026, 4, 1)
    assert len(result.timeline.visits) == 2
    # months=1 → window [2026-06-01, 2026-07-01]，只留 6/1
    result2 = build_timeline(provider, "p", months=1, end_date=date(2026, 7, 1))
    assert [v.date for v in result2.timeline.visits] == [date(2026, 6, 1)]


def test_months_before_clamps_month_end():
    """D-08：月底夾日（3/31 − 6 個月 → 9/30），跨年正確。"""
    from elc_audit_engine.record_aggregator.aggregator import _months_before

    assert _months_before(date(2026, 3, 31), 6) == date(2025, 9, 30)
    assert _months_before(date(2026, 1, 15), 6) == date(2025, 7, 15)
    assert _months_before(date(2026, 8, 1), 6) == date(2026, 2, 1)


def test_provider_switching_cloud_and_local():
    """D-01：雲端與本地實作可互換（同一 build_timeline 消費）。"""

    class FakeCloudProvider(RecordProvider):
        name = "fake-cloud"

        def fetch_records(self, patient_id):
            if patient_id == "cloud-P1":
                return [
                    LabRecord(
                        patient_id=patient_id,
                        date=date(2026, 5, 1),
                        test_name="HbA1c",
                        result="6.8",
                    )
                ]
            raise PatientRecordsNotFound(f"病患 {patient_id} 不在雲端")

    cloud = FakeCloudProvider()
    local = LocalFileProvider(FIXTURE_ROOT)

    cloud_result = build_timeline(cloud, "cloud-P1", end_date=date(2026, 8, 1))
    assert cloud_result.degraded is False
    assert cloud_result.timeline.source_provider == "fake-cloud"
    assert cloud_result.timeline.labs[0].result == "6.8"

    cloud_missing = build_timeline(cloud, "other", end_date=date(2026, 8, 1))
    assert cloud_missing.degraded is True

    local_result = build_timeline(local, "patient_A", end_date=date(2026, 8, 1))
    assert local_result.degraded is False
    assert local_result.timeline.source_provider.startswith("local:")


def test_infra_error_propagates_not_degraded(tmp_path):
    """D-05：infra 故障（損毀 JSON）向外拋，不被降級吞掉。"""
    patient_dir = tmp_path / "broken"
    patient_dir.mkdir()
    (patient_dir / "records.json").write_text("{bad", encoding="utf-8")
    provider = LocalFileProvider(str(tmp_path))
    with pytest.raises(RecordProviderError):
        build_timeline(provider, "broken", end_date=date(2026, 8, 1))
