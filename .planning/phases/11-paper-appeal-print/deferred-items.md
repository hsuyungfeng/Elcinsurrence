# Phase 11-paper-appeal-print — Deferred Items

## 11-03（紙本申復清單列印 CLI）

### 沙箱環境限制：data/ 對 shell 進程唯讀（非本 plan 回歸）

- **發現於**：Task 1 既有套件回歸驗證（`tests/ -k "not appeal_print"`）
- **現象**：`tests/test_server_case_store_integration.py` 中 2 個測試失敗：
  - `test_import_sampling_cases_persists_to_casestore`
  - `test_duplicate_import_reports_conflicts`
- **根因**：執行沙箱對 `data/`（含 `data/uploads/raw/`、`data/audit/`）為**唯讀文件系統**
  （`OSError: [Errno 30] Read-only file system`）；`server._save_upload` 固定寫
  `data/uploads/raw/*.csv`（模組常數 `_UPLOAD_DIR = os.path.join("data", "uploads")`，
  無 env 覆寫）。`.pytest_cache` 亦無法寫入（同因）。
- **判定**：屬環境限制，非 11-03 程式碼回歸。`config/settings.py` 的
  `FACILITY_CONFIG_PATH`／`load_facility_config()` 不影響 server 上傳邏輯。
  基線數字佐證：非 appeal_print 套件於本沙箱為 372 passed + 2 skipped +
  2 failed（環境性）；orchestrator 正常環境基線 374 passed + 2 skipped，
  與之吻合（374 = 372 + 2 個失敗測試）。
- **處置**：不修（超出 11-03 範圍）。orchestrator 於可寫環境執行全套件回歸時
  應為 396 passed + 2 skipped（含 11-03 新增 config/cli 測試）。
