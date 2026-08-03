"""病歷資料來源 Provider（D-01/D-04/D-05）。

`RecordProvider` 抽象化雲端（Phase 9 doctor-toolbox）與本地（Phase 4）
兩種資料來源；`LocalFileProvider` 讀取 `records.json` 契約檔。

降級語意（D-05，承 P0-2 教訓，區分「病歷可缺席」與「infra 故障」）：
- 病患目錄不存在 → `PatientRecordsNotFound`（RecordProviderError 子類），
  aggregator 捕獲後降級（C5：報告標「⚠本報告未含病史佐證」）。
- 目錄存在但 JSON 損毀 → `RecordProviderError`（infra 故障，不吞掉，
  避免 Phase 5 把故障誤讀成「此病患無病歷」）。
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from datetime import date
from typing import Any

from elc_audit_engine.rule_repository.loaders.dates import parse_flexible_date

from .models import ExamRecord, ImagingRecord, LabRecord, Record, VisitRecord


class RecordProviderError(Exception):
    """病歷資料來源故障（infra 故障語意，不降級、向外拋）。

    與 Phase 2 的 RuleRepositoryError 同層級：呼叫端應區分「資料故障」
    （本例外）與「病歷缺席」（PatientRecordsNotFound 的正常降級）。
    """


class PatientRecordsNotFound(RecordProviderError):
    """病患沒有任何病歷檔案（未接雲端／本地無此病患）。

    這是 C5 的正常降級情境，不是故障：aggregator 捕獲後回傳
    `AggregationResult(degraded=True)`。
    """


class RecordProvider(ABC):
    """病歷資料來源介面（D-01）。

    雲端實作（Phase 9）與本地實作（Phase 4）都實作此介面；時間窗過濾
    不在 Provider 內，`fetch_records` 只回傳該病患全部可用紀錄。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 名稱（寫入 PatientTimeline.source_provider）。"""

    @abstractmethod
    def fetch_records(self, patient_id: str) -> list[Record]:
        """回傳指定病患的全部病歷紀錄。

        Args:
            patient_id: 病患識別（Phase 3 d3 病歷號，D-07）。

        Returns:
            該病患的全部紀錄（四類混合，未過濾時間窗）。

        Raises:
            PatientRecordsNotFound: 病患無任何病歷檔案（正常降級情境）。
            RecordProviderError: 資料來源故障（infra 錯誤）。
        """


def _parse_date(value: str | None) -> date | None:
    """解析紀錄日期：ISO `YYYY-MM-DD` 或 8 碼 `YYYYMMDD`。

    8 碼格式重用 Phase 2 的 parse_flexible_date（西元分支）。
    """
    if not value:
        return None
    stripped = value.strip()
    try:
        return date.fromisoformat(stripped)
    except ValueError:
        pass
    # 8 碼 YYYYMMDD 相容（重用 Phase 2 的西元分支）；其餘格式不猜
    if len(stripped) == 8 and stripped.isdigit():
        iso = parse_flexible_date(stripped)
        if iso:
            return date.fromisoformat(iso)
    return None


def _get_str(obj: dict[str, Any], key: str) -> str:
    value = obj.get(key)
    return str(value) if value is not None else ""


def _get_tuple(obj: dict[str, Any], key: str) -> tuple[str, ...]:
    value = obj.get(key)
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    return ()


def _get_bool_or_none(obj: dict[str, Any], key: str) -> bool | None:
    value = obj.get(key)
    if value is None:
        return None
    return bool(value)


class LocalFileProvider(RecordProvider):
    """本地檔案 Provider：讀取 `<root_dir>/<patient_id>/records.json`（D-04）。

    契約檔格式（單檔，鍵皆可選，缺省視為空清單）：
    ```json
    {
      "visits":  [{"date": "2026-01-15", "clinic": "內科", "soap_text": "...", "diagnoses": ["S90221A"]}],
      "labs":    [{"date": "2026-02-01", "test_name": "HbA1c", "result": "7.2", "unit": "%", "reference_range": "4.0-5.6", "abnormal": true}],
      "exams":   [{"date": "2026-03-10", "exam_name": "心電圖", "finding": "竇性心律"}],
      "imaging": [{"date": "2026-04-05", "modality": "CT", "body_part": "胸部", "impression": "無異常", "image_refs": ["ct_001.dcm"]}]
    }
    ```
    日期為 ISO `YYYY-MM-DD`（相容 8 碼 `YYYYMMDD`）。

    Args:
        root_dir: 病歷檔根目錄（可注入，測試用 tmp_path）；預設由呼叫端
            傳 config.settings 的 `DATA_DIR/samples/records`。
    """

    def __init__(self, root_dir: str | os.PathLike[str]):
        self._root_dir = os.fspath(root_dir)

    @property
    def name(self) -> str:
        return f"local:{self._root_dir}"

    def _records_path(self, patient_id: str) -> str:
        return os.path.join(self._root_dir, patient_id, "records.json")

    def fetch_records(self, patient_id: str) -> list[Record]:
        path = self._records_path(patient_id)
        if not os.path.isfile(path):
            raise PatientRecordsNotFound(
                f"病患 {patient_id!r} 無病歷檔案（預期路徑：{path}）"
            )
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise RecordProviderError(
                f"病歷檔讀取失敗（{path}）: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise RecordProviderError(
                f"病歷檔格式錯誤（{path}）：應為 JSON 物件"
            )

        records: list[Record] = []
        for item in _as_list(data.get("visits")):
            records.append(_parse_visit(patient_id, item, path))
        for item in _as_list(data.get("labs")):
            records.append(_parse_lab(patient_id, item, path))
        for item in _as_list(data.get("exams")):
            records.append(_parse_exam(patient_id, item, path))
        for item in _as_list(data.get("imaging")):
            records.append(_parse_imaging(patient_id, item, path))
        return records


def _as_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, dict)]


def _require_date(item: dict[str, Any], path: str, patient_id: str) -> date:
    parsed = _parse_date(_get_str(item, "date"))
    if parsed is None:
        raise RecordProviderError(
            f"病歷檔記錄缺 date 或日期無法解析（{path}，病患 {patient_id!r}）"
        )
    return parsed


def _parse_visit(patient_id: str, item: dict[str, Any], path: str) -> VisitRecord:
    return VisitRecord(
        patient_id=patient_id,
        date=_require_date(item, path, patient_id),
        source_note=path,
        clinic=_get_str(item, "clinic"),
        soap_text=_get_str(item, "soap_text"),
        diagnoses=_get_tuple(item, "diagnoses"),
    )


def _parse_lab(patient_id: str, item: dict[str, Any], path: str) -> LabRecord:
    return LabRecord(
        patient_id=patient_id,
        date=_require_date(item, path, patient_id),
        source_note=path,
        test_name=_get_str(item, "test_name"),
        result=_get_str(item, "result"),
        unit=_get_str(item, "unit"),
        reference_range=_get_str(item, "reference_range"),
        abnormal=_get_bool_or_none(item, "abnormal"),
    )


def _parse_exam(patient_id: str, item: dict[str, Any], path: str) -> ExamRecord:
    return ExamRecord(
        patient_id=patient_id,
        date=_require_date(item, path, patient_id),
        source_note=path,
        exam_name=_get_str(item, "exam_name"),
        finding=_get_str(item, "finding"),
    )


def _parse_imaging(patient_id: str, item: dict[str, Any], path: str) -> ImagingRecord:
    return ImagingRecord(
        patient_id=patient_id,
        date=_require_date(item, path, patient_id),
        source_note=path,
        modality=_get_str(item, "modality"),
        body_part=_get_str(item, "body_part"),
        impression=_get_str(item, "impression"),
        image_refs=_get_tuple(item, "image_refs"),
    )
