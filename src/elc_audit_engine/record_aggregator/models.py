"""病歷彙整器的結構化資料型別（frozen dataclass，沿用 RuleResult 慣例）。

Phase 4 把病歷資料來源（雲端或本地）彙整成「近半年病史時間軸」，供
Phase 5 三方比對器消費。純資料彙整層：無 LLM 呼叫、無規則庫查詢
（04-CONTEXT.md domain）。

四類紀錄（D-02，依 D5／電子抽審.md「就診紀錄/檢驗/檢查/影像清單」）共用
`Record` 基底，讓時間軸排序/過濾共用 patient_id + date 鍵。
"""

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Record:
    """病歷紀錄基底：四類紀錄共用的欄位。

    Attributes:
        patient_id: 病患識別（Phase 3 的 d3 病歷號，D-07 對齊鍵）。
        date: 紀錄日期（ISO）。
        source_note: 來源備註（檔案路徑／Provider 名稱等），供追蹤。
    """

    patient_id: str
    date: date
    source_note: str = ""


@dataclass(frozen=True)
class VisitRecord(Record):
    """就診紀錄（電子抽審.md「門診病歷／SOAP」）。

    Attributes:
        clinic: 科別。
        soap_text: 當次 SOAP 原始文字 — Phase 5 需要分段時呼叫
            `parse_soap_text`（D-06：Phase 4 不依賴 Phase 3，只存原文）。
        diagnoses: 診斷清單（ICD-10 代碼或文字）。
    """

    clinic: str = ""
    soap_text: str = ""
    diagnoses: tuple[str, ...] = ()


@dataclass(frozen=True)
class LabRecord(Record):
    """檢驗紀錄。

    Attributes:
        test_name: 檢驗項目名稱（如 HbA1c、白血球）。
        result: 檢驗結果（原樣字串，保留單位語意）。
        unit: 單位。
        reference_range: 參考值區間（如 "4.0-5.6 %"）。
        abnormal: 異常旗標；None 表示來源未標記。
    """

    test_name: str = ""
    result: str = ""
    unit: str = ""
    reference_range: str = ""
    abnormal: bool | None = None


@dataclass(frozen=True)
class ExamRecord(Record):
    """檢查紀錄（非影像，如心電圖／肺功能）。

    Attributes:
        exam_name: 檢查項目名稱。
        finding: 檢查所見／結論（自由文字）。
    """

    exam_name: str = ""
    finding: str = ""


@dataclass(frozen=True)
class ImagingRecord(Record):
    """影像檢查清單（CT/MRI/X-ray/超音波等）。

    Attributes:
        modality: 影像模態（CT、MRI、X-ray、超音波…）。
        body_part: 檢查部位。
        impression: 影像所見／結論（自由文字）。
        image_refs: 影像檔名或路徑清單（電子抽審.md 的影像打包參考）。
    """

    modality: str = ""
    body_part: str = ""
    impression: str = ""
    image_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class PatientTimeline:
    """單一病患的近半年病史時間軸（D-03）。

    Attributes:
        patient_id: 病患識別。
        window_start: 時間窗起日（含，ISO）。
        window_end: 時間窗迄日（含，ISO）。
        visits: 就診紀錄（窗內，依日期排序）。
        labs: 檢驗紀錄（窗內，依日期排序）。
        exams: 檢查紀錄（窗內，依日期排序）。
        imaging: 影像清單（窗內，依日期排序）。
        source_provider: 資料來源 Provider 名稱。
        excluded_counts: 被時間窗排除的紀錄筆數，鍵為類別（visits/labs/
            exams/imaging）。不拋棄資料，供下游透明度。
    """

    patient_id: str
    window_start: date
    window_end: date
    visits: tuple[VisitRecord, ...] = ()
    labs: tuple[LabRecord, ...] = ()
    exams: tuple[ExamRecord, ...] = ()
    imaging: tuple[ImagingRecord, ...] = ()
    source_provider: str = ""
    excluded_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class AggregationResult:
    """彙整結果：時間軸＋降級旗標（C5）。

    Attributes:
        timeline: 時間軸；病歷缺席（降級）時為 None。
        degraded: 是否降級 — True 代表「病歷缺席」（未接雲端／無檔案），
            Phase 6 報告開頭須標「⚠本報告未含病史佐證」。
        reason: 降級原因（degraded=True 時有值）。
    """

    timeline: PatientTimeline | None = None
    degraded: bool = False
    reason: str = ""
