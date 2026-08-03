# Phase 4 Plan 01 Summary — 病歷彙整器交付

**Plan:** [04-01-PLAN.md](04-01-PLAN.md)
**Status:** ✅ Complete — 110 passed / 5 skipped（前 96 passed / 5 skipped，新增 14 測試全綠）

## Deliverables

| 檔案 | 內容 |
|------|------|
| `src/elc_audit_engine/record_aggregator/models.py` | Record 基底（patient_id/date/source_note）＋VisitRecord（科別/SOAP 原文/診斷）＋LabRecord（項目/結果/單位/參考值/異常旗標）＋ExamRecord（項目/所見）＋ImagingRecord（模態/部位/影像所見/檔名清單）＋PatientTimeline（四類＋window＋excluded_counts）＋AggregationResult（timeline/degraded/reason） |
| `src/elc_audit_engine/record_aggregator/providers.py` | `RecordProvider` ABC（fetch_records＋name）＋`LocalFileProvider`（讀 `<root>/<patient_id>/records.json`，ISO/8 碼日期相容）＋`RecordProviderError`／`PatientRecordsNotFound` |
| `src/elc_audit_engine/record_aggregator/aggregator.py` | `build_timeline()`：時間窗過濾（含邊界）＋依日期排序＋窗外計入 excluded_counts；PatientRecordsNotFound → degraded 降級；RecordProviderError 向外拋 |
| `src/elc_audit_engine/record_aggregator/__init__.py` | 對外 API（型別＋Provider＋build_timeline） |
| `tests/fixtures/records/patient_A/records.json` | 四類紀錄 fixture（窗內/窗外混合，含 8 碼日期） |
| `tests/test_record_aggregator.py`（14 測試） | ABC 不可實例化、四類讀取、8 碼日期、缺病患→PatientRecordsNotFound、損毀 JSON→RecordProviderError、時間窗過濾＋排序、降級語意、空清單不降級、自訂窗、月底夾日、雲端/本地切換、infra 錯誤向外拋 |

## Real-Data Verification

```
[正常] degraded=False window=2026-02-01~2026-08-01 source=local:tests/fixtures/records
  visits=1 labs=1 exams=1 imaging=1 excluded={'visits': 1, 'labs': 1, 'exams': 0, 'imaging': 1}
  首筆就診: 2026-07-20 骨科 診斷=('S6300XA',)
  檢驗: [(2026-02-15, HbA1c, 7.2)]
[降級] degraded=True timeline=None reason=病歷缺席：病患 'no_such' 無病歷檔案...
```

## 決策落地

- **D-01**：Provider 只回傳全部紀錄，時間窗邏輯集中在 aggregator —— 雲端（FakeCloudProvider 測試）與本地可互換。
- **D-05（P0-2 教訓）**：病歷缺席（目錄不存在）→ `PatientRecordsNotFound` → `degraded=True`（C5 降級）；JSON 損毀 → `RecordProviderError` 向外拋，不吞成「無病歷」。
- **D-06**：`VisitRecord.soap_text` 存原始文字，Phase 4 不 import Phase 3（維持只依賴 Phase 1）。
- **D-08**：時間窗手動位移＋`calendar.monthrange` 夾日（3/31−6m→9/30 測試釘住）。
- 8 碼 `YYYYMMDD` 日期相容（fixture 的 `20241201` 檢驗），重用 Phase 2 `parse_flexible_date`。

## 對接說明（Phase 5）

- `build_timeline(provider, patient_id, months=6, end_date=None)`：`patient_id` = Phase 3 `SubmissionCase.record_no`（d3）。
- `VisitRecord.soap_text` → Phase 5 呼叫 `parse_soap_text` 分段。
- 降級時 `AggregationResult.degraded=True` → Phase 6 報告開頭標「⚠本報告未含病史佐證」。
