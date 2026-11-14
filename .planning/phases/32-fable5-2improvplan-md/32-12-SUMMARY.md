# Phase 32 Plan 12: SoapVoice 子行程監控與看管 Summary

> **日期**：2026-11-14  
> **狀態**：✅ COMPLETE  
> **需求**：B4、D-32-05、D-32-21  

---

## 執行成果

1. **子行程看管模組實作 (`deploy/windows_agent/supervisor.py`)**：
   - 實作 `SoapVoiceSupervisor`：
     - **外部執行偵測**：`health_fn()` 回傳 True 時不重複啟動，進入 `external` 狀態。
     - **退避重試與上限**：行程異常結束時以指數退避重啟（`backoff_base=1.0`，`backoff_max=60.0`），重試超過 `max_restarts`（預設 5 次）進入 `gave_up` 狀態，並通知快捷列。
     - **穩定運行重置**：子行程持續穩定運行超過 `stable_seconds`（預設 300 秒）後，重試計數自動歸零。
     - **無黑視窗與日誌導向**：Windows 環境下帶 `CREATE_NO_WINDOW (0x08000000)`，標準輸出/錯誤重導至 `%LOCALAPPDATA%\ElcAgent\logs\soapvoice.log`。
   - 實作 `default_soapvoice_exe_path`：支援依 D-32-21 安裝佈局取得 `{app}/SoapVoice/SoapVoice.exe` 或自訂設定。

2. **Windows Job Object 防孤兒行程與背景執行緒**：
   - 實作 `assign_kill_on_close_job`：在 Windows 下利用 `ctypes` 建立 Job Object 並配置 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)`，確保 ElcAgent 不論正常或異常退出時，SoapVoice 皆隨之結束；非 Windows 環境安全回傳 False。
   - 實作 `run_in_thread`：提供常駐 daemon 執行緒依設定間隔（預設 5 秒）持續輪詢看管，支援 `threading.Event` 乾淨停止。

3. **測試與驗證 (`tests/test_agent_supervisor.py`)**：
   - 移除 Wave 0 xfail 標記。
   - 包含完整生命週期與退避測試、外部執行偵測測試、穩定運行重置測試、重試上限放棄測試、Linux/macOS 與 Windows 模擬下的 Job Object 測試、背景執行緒停止測試、預設執行檔路徑測試。
   - 8 項測試全數通過（8 passed in 1.50s）。
