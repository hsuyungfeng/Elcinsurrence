# 09-03-SUMMARY.md — server.py 端點接 CaseStore＋uploads 遷移

## 執行成果摘要

Phase 9 Plan 03 成功完成 `server.py` 端點接線與既有落盤資料的啟動期遷移：

1. **匯入端點建案與衝突回報**：
   - `/api/sampling/import` 與 `/api/appeal/import` 成功解析後，將每筆案件逐筆持久化至 `CaseStore` (state=`imported`)。
   - 重複匯入相同的 `case_id` 時，衝突案件列於 `case_store_conflicts` 回報呼叫端並拒絕建案，不靜默覆寫既有案件。

2. **GET 端點改讀 CaseStore**：
   - `/api/sampling/cases` 與 `/api/appeal/cases` 改以 `CaseStore.list_all()` 為單一真實來源。
   - 當 CaseStore 內尚無資料時，優雅 fallback 回既有示範資料（`demo: true`）。

3. **啟動期一次性冪等遷移**：
   - `server.py` 啟動時自動掃描 `data/uploads/*.json` 並一次性將舊案件遷移至 `CaseStore`。
   - 遷移過程具備冪等性（已存在的案件自動忽略，不報錯不重複建案），並於啟動 log 紀錄遷移筆數（無 PHI）。

4. **選填 `case_id` 與非阻斷狀態轉換**：
   - `/api/sampling/audit` 與 `/api/appeal/generate` 新增選填 `case_id` 參數。
   - 提供 `case_id` 時分別嘗試觸發狀態變更（`sampling` 推進至 `reviewed`，`appeal` 推進至 `appealed`）。
   - 狀態轉換例外（如案件不存在或非法轉換）僅紀錄 Warning log，不阻斷既有業務判定結果的回覆。

5. **自動化測試與文件**：
   - 新增 `tests/test_server_case_store_integration.py`（9 項測試全綠）。
   - README.md 更新 API 規格說明與 Phase 9-03 接線紀錄。

## 變更檔案清單

- `server.py`: 引入 CaseStore 單例、`_persist_cases`、`_migrate_legacy_uploads`、GET 端點與 audit/generate 端點重構。
- `tests/test_server_case_store_integration.py`: 匯入建案、衝突處理、GET 查詢、遷移冪等性、狀態轉換與日誌警告測試。
- `README.md`: API 規格說明更新。

## 檢驗

- `./.venv/bin/python -m pytest tests/test_server_case_store_integration.py -q`: 9 passed
- 全測試套件通過（363 passed / 2 skipped）。
