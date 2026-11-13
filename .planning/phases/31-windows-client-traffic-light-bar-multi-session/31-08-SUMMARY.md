# Plan 31-08 Summary: SoapVoice 分段音訊帳本、暫存清理與不丟棄佇列修正 (Task 1 & Task 2)

## 成果摘要
- **模組交付**：
  1. `SoapVoice/client/segment_store.py`：
     - `CycleManifest` 與 `SegmentStore`：管理 `cycles/{cycle_id}/` 之 manifest.json。
     - **sha256 嚴格驗證（D-31-30）**：`mark_acked` 僅在 server_sha256 與本機計算值一致時標記 acked=True，不符則回傳 False 且不改狀態。
     - **線程安全與原子寫入**：以 `threading.RLock` 保護，`manifest.json.tmp` + `fsync` + `os.replace` 原子覆蓋。
     - 支援 `pending_chunks`（升冪）、`reset_ack`（補漏重置）、`set_context` / `get_context`（本機上下文）及循環生命週期標記。
  2. `SoapVoice/client/lan_config.py`：
     - 新增 `chunk_seconds`（預設 20，夾取於 15–30 秒，D-31-19）。
     - 新增 `temp_cache_max_mb`（預設 2048 MB，支援 `SOAPVOICE_TEMP_CACHE_MAX_MB` 環境變數覆寫，D-31-31）。
     - 新增 `control_port`（預設 18765）、`control_host`（固定 `127.0.0.1`）、`control_token_path`（預設路徑符合契約 §1）。
     - 新增 `cycles_dir` 屬性（`local_cache_dir / "cycles"`）。
  3. `SoapVoice/client/temp_cleanup.py`：
     - `enforce_cap(store, max_bytes)` 實作暫存保護四大原則：
       1. 僅在超過上限時清理（D-31-31）。
       2. 僅刪除已封存（`archived=True`）且已確認收到（`acked=True`）之分段（D-31-30, D-31-33）。
       3. 依 `archived_at` 由最舊循環開始清理，達標即停。
       4. 未 acked 分段一律保留（D-31-32）；未封存循環一律保留（D-31-33）；`manifest.json` 永不刪除。
  4. `SoapVoice/client/local_storage.py`：
     - 依 D-31-32 修正 `add_pending`：移除隊列滿時呼叫 `_remove_oldest` 自動丟棄行為，改為記錄 warning 並保留所有未上傳項目。
  5. 測試套件更新：
     - `tests/test_segment_store.py`：6 項驗證全數通過。
     - `tests/test_temp_cleanup.py`：6 項清理與隊列規則驗證全數通過。
     - `tests/test_client.py`：更新 `test_local_storage_queue_overflow` 與 `test_lan_client_pending_queue_cap` 斷言（依 D-31-32 改為驗證保留未上傳項目）。
- **測試結果**：
  - SoapVoice 累積測試 79 passed, 2 warnings (5.42s)。

## 偏離與路徑對應
- **路徑偏離**：依使用者指示，SoapVoice 修改全數實作於 `/home/hsu/Desktop/Elcinsurrence/SoapVoice`，禁止寫入 `~/Desktop/SoapVoice`。
- **測試更新說明**：依計畫指示與 D-31-32，更新 `tests/test_client.py` 中原本期望 drop 舊項目的 2 項既有測試，改為斷言不丟棄。
- **Git 狀態**：遵守指示，全數修改保持未 commit。
