# Phase 32 Plan 19 Summary: Windows Agent 入口整合（首次向導、單實例、系統匣、SoapVoice 看管與自癒重連）

## 1. 任務概述
- **目標**: 將 B4（SoapVoice 看管）、B5（System Tray 系統匣）、B6（首次啟動向導）、C3（斷線自癒重連）與 Windows 具名 Mutex 單實例整合至 `deploy/windows_agent/main.py`。
- **首次向導觸發**: 當 `facility_code` 或 `room_id` 缺失時，自動喚起三步精靈，完成後將 `server_url`, `facility_code`, `room_id`, `vendor_key` 寫入 `config.json`；若醫師關閉精靈則乾淨以代碼 0 退出。
- **單實例防重**: Windows 下以 `kernel32.CreateMutexW` 建立 `ElcAgentSingleInstance`。若偵測到 `ERROR_ALREADY_EXISTS (183)`，彈出視窗提醒並乾淨退出。
- **子行程看管**: 啟動快捷列時由 `SoapVoiceSupervisor` 自動於背景拉起並持續看管 `SoapVoice.exe`，程式退出時以 `supervisor.stop()` 與 Job Object 雙重確保無孤兒殘留。
- **系統匣整合**: 啟動 `start_tray`，支援常駐系統匣圖示與右鍵選單。

## 2. 成果與驗證
- **修改檔案**:
  - `deploy/windows_agent/main.py` (新增 Mutex 守衛、首次向導檢查掛勾、Supervisor 與 Tray 整合)
  - `deploy/windows_agent/config.py` (新增 `soapvoice_exe_path` 設定欄位)
  - `tests/test_agent_entrypoint.py` (新增 `test_first_run_triggered_when_missing_config`, `test_first_run_cancelled_returns_none`, `test_single_instance_mutex_already_exists`, `test_launch_traffic_bar_wires_supervisor_and_tray`)
- **測試結果**:
  - `tests/test_agent_entrypoint.py` + `tests/test_agent_supervisor.py` + `tests/test_agent_tray.py` 共 36 passed，0 failed。

## 3. 威脅模型處置
- T-32-19-01 (Denial of Service): Windows 具名 Mutex 強制單一實例，杜絕多實例競搶控制項與音效裝置。
- T-32-19-02 (Denial of Service): Windows Job Object 自動隨父行程消亡 + `supervisor.stop()` 與 atexit 雙重保證，避免子行程殘留佔用麥克風與埠號。
