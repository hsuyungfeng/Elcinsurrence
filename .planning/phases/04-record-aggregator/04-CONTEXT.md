# Phase 4: 病歷彙整器 - Context

**Gathered:** 2026-08-03（由 Phase 3 交接 + ROADMAP/REQUIREMENTS/D5/C5 整理）
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 4 把病歷資料來源（雲端或本地）彙整成「近半年病史時間軸」，供 Phase 5
三方比對器消費。純資料彙整層：**無 LLM 呼叫、無規則庫查詢**（與 Phase 3
相同約束）。Provider 介面抽象化資料來源，本地檔案 Provider 在未接雲端時
頂替（D5）。

Phase 5 消費時間軸：就診紀錄（SOAP）→ 病歷佐證比對；檢驗/檢查/影像 →
支持度判定與候選補強線索。

</domain>

<decisions>
## Implementation Decisions

- **D-01（Provider 介面）:** `RecordProvider` ABC，單一方法
  `fetch_records(patient_id) -> list[Record]` ＋ `name` 屬性。
  雲端實作（Phase 9 doctor-toolbox）與本地實作（Phase 4）都實作此介面；
  時間窗過濾**不在 Provider 內**（Provider 只回傳該病患全部紀錄，窗邏輯
  集中在 aggregator，介面兩端都不需要重複實作）。

- **D-02（四類紀錄型別）:** 依 D5／電子抽審.md「就診紀錄/檢驗/檢查/影像
  清單」建模四種型別，共用 `Record` 基底（patient_id + date + source_note）
  ——時間軸排序/過濾共用一個鍵：
  1. `VisitRecord`：就診（科別、SOAP 原文、診斷清單）
  2. `LabRecord`：檢驗（檢驗項目、結果、單位、參考值、異常旗標）
  3. `ExamRecord`：檢查（非影像，如心電圖/肺功能；項目＋所見）
  4. `ImagingRecord`：影像清單（模態 CT/MRI/X-ray、部位、影像所見、影像檔名清單）

- **D-03（半年時間軸）:** `build_timeline(provider, patient_id, *, months=6,
  end_date=None)`：依 `end_date`（預設今天）往前推 months 個月為時間窗，
  過濾落在窗內（含邊界）的紀錄並依日期排序，回傳 `PatientTimeline`
  （四類清單＋window＋被排除筆數統計）。

- **D-04（本地檔案 Provider）:** `LocalFileProvider(root_dir)` 讀取
  `<root_dir>/<patient_id>/records.json`（單檔契約：`{"visits": [...],
  "labs": [...], "exams": [...], "imaging": [...]}`）。日期為 ISO
  `YYYY-MM-DD`；相容 8 碼 `YYYYMMDD`（重用 `parse_flexible_date`）。
  root_dir 可注入（測試用 tmp_path），預設 `data/samples/records`。

- **D-05（降級語意 — 區分「病歷可缺席」與「infra 故障」）:** 承 P0-2 教訓：
  - 病患目錄不存在（未接雲端／無檔案）→ 拋 `PatientRecordsNotFound`
    （RecordProviderError 子類），aggregator 捕獲後回傳
    `AggregationResult(degraded=True, reason=...)` —— C5 的正常降級，
    Phase 6 報告開頭標「⚠本報告未含病史佐證」。
  - 目錄存在但 JSON 損毀 → 拋 `RecordProviderError`（infra 故障，不吞掉，
    避免 Phase 5 把故障誤讀成「此病患無病歷」）。
  - 目錄存在但各清單為空 → 正常空時間軸（degraded=False，病患確實無紀錄）。

- **D-06（與 Phase 3 SOAP 對齊但不依賴）:** `VisitRecord.soap_text` 存
  **原始文字**；Phase 5 需要分段時呼叫 `parse_soap_text`。Phase 4 維持
  只依賴 Phase 1（ROADMAP Depends on: Phase 1），兩者可平行開發測試；
  型別欄位已預留 SOAP 原文，串接點明確。

- **D-07（patient_id 對齊）:** Phase 3 的 `SubmissionCase.record_no`（d3
  病歷號）是自然 join key；`build_timeline` 的 `patient_id` 即 d3 值。
  Phase 5 串接時以 d3 → timeline.patient_id 對應。

- **D-08（時間窗計算）:** 不引入 dateutil 依賴；手動 `year*12+month`
  位移並以 `calendar.monthrange` 夾日（如 3/31 − 6 個月 → 9/30）。
</decisions>

<deferred>
- 真實 HIS 匯出格式（CSV/TXT/PDF 病歷）轉換 → 本地 Provider 的 records.json
  只是契約介面；真實格式 adapter 留到 Phase 9（doctor-toolbox）或拿到
  真實樣本後再補，不阻擋 Phase 4。
- 雲端 Provider 實作 → Phase 9。
</deferred>

---

*Phase: 4-病歷彙整器*
*Context gathered: 2026-08-03*
