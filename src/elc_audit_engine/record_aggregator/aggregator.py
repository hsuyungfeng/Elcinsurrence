"""病歷彙整器：Provider → 半年病史時間軸（D-03/D-05/D-08）。

`build_timeline()` 是 Phase 4 的單一入口：從 Provider 取得病患全部紀錄，
過濾出「近半年」時間窗（含邊界）內的紀錄、依日期排序，回傳
`AggregationResult`。病歷缺席（PatientRecordsNotFound）降級為
`degraded=True`（C5）；infra 故障（RecordProviderError）向外拋。
"""

from __future__ import annotations

import calendar
from datetime import date

from .models import (
    AggregationResult,
    ExamRecord,
    ImagingRecord,
    LabRecord,
    PatientTimeline,
    Record,
    VisitRecord,
)
from .providers import PatientRecordsNotFound, RecordProvider


def _months_before(end: date, months: int) -> date:
    """把 end 往回推 months 個月（D-08：不引入 dateutil）。

    以 `year*12+month` 位移，月底以 calendar.monthrange 夾日
    （如 3/31 − 6 個月 → 9/30）。
    """
    month_index = end.year * 12 + (end.month - 1) - months
    year, zero_based = divmod(month_index, 12)
    month = zero_based + 1
    day = min(end.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


_CATEGORY_ATTRS: tuple[tuple[str, str], ...] = (
    ("visits", "visits"),
    ("labs", "labs"),
    ("exams", "exams"),
    ("imaging", "imaging"),
)


def _split_by_window(
    records: list[Record], window_start: date, window_end: date
) -> tuple[dict[str, list[Record]], dict[str, int]]:
    """把紀錄分為窗內（含邊界）與窗外；窗外只統計筆數（D-03）。

    Returns:
        (窗內清單 per 類別, 窗外筆數 per 類別)。
    """
    in_window: dict[str, list[Record]] = {"visits": [], "labs": [], "exams": [], "imaging": []}
    excluded: dict[str, int] = {"visits": 0, "labs": 0, "exams": 0, "imaging": 0}

    for record in records:
        category = _category_of(record)
        if window_start <= record.date <= window_end:
            in_window[category].append(record)
        else:
            excluded[category] += 1
    return in_window, excluded


def _category_of(record: Record) -> str:
    if isinstance(record, VisitRecord):
        return "visits"
    if isinstance(record, LabRecord):
        return "labs"
    if isinstance(record, ExamRecord):
        return "exams"
    if isinstance(record, ImagingRecord):
        return "imaging"
    raise TypeError(f"未知紀錄型別: {type(record).__name__}")


def _sorted(records: list[Record]) -> list[Record]:
    """依日期排序（同日期維持原順序，穩定排序）。"""
    return sorted(records, key=lambda r: r.date)


def build_timeline(
    provider: RecordProvider,
    patient_id: str,
    *,
    months: int = 6,
    end_date: date | None = None,
) -> AggregationResult:
    """彙整單一病患的近半年病史時間軸（Phase 4 單一入口）。

    Args:
        provider: 病歷資料來源（雲端或本地，D-01）。
        patient_id: 病患識別（Phase 3 d3 病歷號，D-07）。
        months: 時間窗長度（預設 6 個月）。
        end_date: 時間窗迄日（預設今天）；窗起日 = end_date − months 個月。

    Returns:
        AggregationResult：
        - 正常：timeline 含窗內四類紀錄（依日期排序）＋excluded_counts；
          degraded=False。
        - 病歷缺席（PatientRecordsNotFound）：timeline=None、degraded=True、
          reason 說明（C5 降級，報告標「⚠本報告未含病史佐證」）。

    Raises:
        RecordProviderError: Provider infra 故障（JSON 損毀等），不降級。
    """
    try:
        records = provider.fetch_records(patient_id)
    except PatientRecordsNotFound as exc:
        return AggregationResult(
            timeline=None,
            degraded=True,
            reason=f"病歷缺席：{exc}",
        )

    window_end = end_date or date.today()
    window_start = _months_before(window_end, months)

    in_window, excluded = _split_by_window(records, window_start, window_end)

    timeline = PatientTimeline(
        patient_id=patient_id,
        window_start=window_start,
        window_end=window_end,
        visits=tuple(_sorted(in_window["visits"])),  # type: ignore[arg-type]
        labs=tuple(_sorted(in_window["labs"])),  # type: ignore[arg-type]
        exams=tuple(_sorted(in_window["exams"])),  # type: ignore[arg-type]
        imaging=tuple(_sorted(in_window["imaging"])),  # type: ignore[arg-type]
        source_provider=provider.name,
        excluded_counts=excluded,
    )
    return AggregationResult(timeline=timeline, degraded=False, reason="")
