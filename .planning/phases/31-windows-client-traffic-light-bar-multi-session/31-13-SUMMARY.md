# Plan 31-13 Summary: SoapVoice 分段上傳器與綠燈後循環 Pipeline (Task 1 & Task 2)

## 成果摘要
- **模組交付**：
  1. `/home/hsu/Desktop/Elcinsurrence/SoapVoice/client/chunk_uploader.py`：
     - `ChunkUploader`：支援背景執行緒自動輪詢未 acked 分段並依 `seq` 順序上傳。
     - 傳輸雜湊校驗（D-31-30）：嚴格比對 server 回應之 `sha256`，相同才標記 `acked=True`。
     - 容錯與退避機制（D-31-22）：遇連線中斷或 5xx 回應採指數退避（1s, 2s, 4s... 上限 30s），未完成分段安全留存本機佇列；遇 409/422 記錄錯誤並中止該循環上傳，絕不刪除音檔。
     - 執行緒隔離（D-31-24）：錄音切檔與上傳在不同執行緒運作，網路延遲絕不阻塞錄音進行。
  2. `/home/hsu/Desktop/Elcinsurrence/SoapVoice/client/cycle_pipeline.py`：
     - `CyclePipeline`：綠燈後生命週期推進狀態機（`advance` 方法每次至多推進一步）：
       - 步驟 1 (Finalize)：確認所有分段已 acked 且總段數已定，計算全部段落 PCM frames 串接之雜湊發送至 `/api/cycles/{id}/finalize`；遇 409 missing 自動將缺少 seq 標記為未 acked 交還上傳器補傳。
       - 步驟 2 (SOAP 生成)：以本機分段串接之完整音檔 `full.wav` 與截圖呼叫 `generate_fn`，產出結果保存至循環目錄之 `lan_result.json`，重啟後不重複呼叫。
       - 步驟 3 (草稿送出)：經 `map_lan_result_to_draft` 映射欄位後 POST `/api/cycles/{id}/draft`，成功記錄 `draft_id` 進入 `SUBMITTED` 狀態。
     - `map_lan_result_to_draft`：將 LAN 處理結果轉換為契約 §2 規範格式，支援 `extras_missing` 缺失欄位追蹤。
  3. 測試套件與 Fixture：
     - 複製契約 fixture 至 `/home/hsu/Desktop/Elcinsurrence/SoapVoice/tests/fixtures/phase31_contract_v1.json`。
     - `tests/test_chunk_uploader.py`：6 項上傳、sha256 校驗、指數退避、409 停傳、並行切檔測試全數通過。
     - `tests/test_cycle_pipeline.py`：7 項 finalize、串接音訊 PCM 校驗、缺少分段重置、完整音檔生成、草稿送出與例外容錯測試全數通過。

## 欄位對應表 (A-31-13b 查證結果)

依據查證 `src/api/lan_process_api.py`（`LANProcessResponse`）與 `src/api/extended_api.py`（`ExtendedProcessResponse`）：

| 循環草稿欄位 (Contract §2) | 來源鍵名 (LANProcessResponse / Extended) | 備註 / 缺失處理 |
|---|---|---|
| `soap.s`, `soap.o`, `soap.a`, `soap.p` | `soap["s"]`, `soap["o"]`, `soap["a"]`, `soap["p"]` | 直接映射 |
| `transcript` | `transcript` | 直接映射 |
| `extras.summary_zh` | `summary_zh` (選填) | 若 LAN 結果無此欄位，填 `""` 並記錄於 `extras_missing`（絕不自英文翻譯捏造） |
| `extras.past_history` | `past_history` 或 `history` | 若無則填 `""` 並記錄於 `extras_missing` |
| `extras.suggestions.icd10` | `icd10_codes` 或 `icd10` (取出 `code` 欄位) | 若無則為空串列，記錄於 `extras_missing` |
| `extras.suggestions.orders` | `medical_orders` 或 `orders` | 若無則為空串列，記錄於 `extras_missing` |
| `extras.suggestions.meds` | `drug_recommendations` 或 `drugs` 或 `meds` | 若無則為空串列，記錄於 `extras_missing` |

## 偏離與路徑對應
- **SoapVoice 寫入路徑重導向**：
  依使用者規則，所有修改嚴格寫入 `/home/hsu/Desktop/Elcinsurrence/SoapVoice`，禁止寫入 `~/Desktop/SoapVoice`。
- 無 git commit，無 git push。
