"""病歷彙整器：Provider 介面 + 本地檔案 Provider + 半年病史時間軸（Phase 4）。

純資料彙整層：無 LLM 呼叫、無規則庫查詢。單一入口：
- build_timeline(provider, patient_id, months=6, end_date=None) -> AggregationResult

Provider 抽象化雲端（Phase 9 doctor-toolbox）與本地（Phase 4）資料來源；
病歷缺席時降級（C5），infra 故障時拋 RecordProviderError（P0-2 教訓）。
"""

from .models import (
    AggregationResult,
    ExamRecord,
    ImagingRecord,
    LabRecord,
    PatientTimeline,
    Record,
    VisitRecord,
)
from .providers import (
    LocalFileProvider,
    PatientRecordsNotFound,
    RecordProvider,
    RecordProviderError,
)
from .aggregator import build_timeline

__all__ = [
    "AggregationResult",
    "ExamRecord",
    "ImagingRecord",
    "LabRecord",
    "LocalFileProvider",
    "PatientRecordsNotFound",
    "PatientTimeline",
    "Record",
    "RecordProvider",
    "RecordProviderError",
    "VisitRecord",
    "build_timeline",
]
