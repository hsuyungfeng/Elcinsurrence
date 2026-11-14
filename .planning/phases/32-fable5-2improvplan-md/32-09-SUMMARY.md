# Phase 32 Plan 09: 客戶端時間＋容量雙軌清理規則 Summary

> **日期**：2026-11-14  
> **狀態**：✅ COMPLETE  
> **需求**：D6、D-32-04、D-32-20、OPEN-32-05  

---

## 執行成果

1. **雙軌清理實作 (`SoapVoice/client/temp_cleanup.py`)**：
   - 實作 `enforce_retention(store, max_bytes, retention_days=90, now=None) -> dict`。
   - 嚴格落實 D-32-20 調和規則：
     - **時間規則**：已封存且已 acked、且封存時間早於 `now - retention_days` 者刪除，標記 `reason="age"`。
     - **容量規則**：若時間清理後目錄大小仍超過 `max_bytes`（預設 2GB），按封存時間由舊到新清理已 acked 檔案，標記 `reason="cap"`。
     - **零資料遺失防線**：未 acked 檔案無論多舊永不刪除；未封存循環永不刪除；`manifest.json` 永不刪除。
     - **未上傳統計**：回傳 `unuploaded_bytes`，統計本機未 acked 檔案與衍生檔大小，供警示監控。
   - 保留既有 `enforce_cap(store, max_bytes)` 向後相容包裝函式。

2. **設定與呼叫端接線**：
   - `SoapVoice/client/lan_config.py`：新增 `temp_retention_days: int`（預設 90），支援環境變數 `SOAPVOICE_TEMP_RETENTION_DAYS` 覆寫。
   - `SoapVoice/client/main.py`：`cleanup_fn` 改呼叫 `enforce_retention`，當 `unuploaded_bytes` 超過上限 80% 時記錄警示日誌。

3. **測試驗證 (`SoapVoice/tests/test_temp_cleanup.py`)**：
   - 新增 4 項專屬測試：
     - `test_retention_deletes_expired_acked_cycles`：逾期已 acked 循環依 age 規則刪除。
     - `test_retention_preserves_expired_unacked_chunks`：逾期未 acked 循環絕對保留。
     - `test_retention_unarchived_never_deleted`：未封存循環即使過期永不刪除。
     - `test_retention_cap_fallback`：時間清理後若仍超量，依 cap 規則接續清理。
   - 執行 `test_temp_cleanup.py`、`test_segment_store.py`、`test_cycle_session.py` 共 21 項測試全部通過（21 passed in 0.37s）。
