# Plan 31-12 Summary: 快捷列通訊與流程控制器 (Task 1 & Task 2)

## 成果摘要
- **模組交付**：
  1. `deploy/windows_agent/config.py`：
     - 新增 `AgentSettings` 欄位：`room_id: str = ""`、`bar_x: Optional[int] = None`、`bar_y: Optional[int] = None`、`soapvoice_control_port: int = 18765`。
     - 具備完整向後相容性（無此欄位之舊設定檔能正確以預設值載入並持久化）。
     - `operator_key` 與 `agent_key` 維持 `repr=False` 防洩漏。
  2. `deploy/windows_agent/traffic_bar/soapvoice_client.py`：
     - `SoapVoiceControlClient`：實作 `status`、`start`、`stop`、`archived`。
     - 防 DNS rebinding（T-31-44）：限定連線目標為 `127.0.0.1` 或 `localhost`，其餘拋 `ValueError`。
     - 認證安全：請求自動攜帶 `Host` 與 `X-Local-Token`（讀取自 `%LOCALAPPDATA%\ElcSoapVoice\control_token` 或 Linux/macOS 平台路徑），日誌絕不包含 token。
     - 結構化例外：`IpcUnavailable`、`IpcRejected(status, error_code, message, body)`。
  3. `deploy/windows_agent/traffic_bar/server_client.py`：
     - `CycleServerClient`：實作 `create_cycle`、`get_active`、`get_cycle`、`stop`、`get_draft`、`confirm`、`archive`、`abandon`、`heartbeat`。
     - 攜帶 `operator_key` 於 `X-API-Key` 標頭；202 與 409 回應狀態碼與本文完整保留供 controller 判定。
  4. `deploy/windows_agent/traffic_bar/controller.py`：
     - `BarController`：純流程邏輯，完全無 tkinter 依賴。
     - 紅燈流程（D-31-05）：先建立 server 循環，再啟動 SoapVoice 錄音；若 SoapVoice 啟動失敗自動 abandon 伺服器循環並重回待命。
     - 綠燈流程（D-31-07）：先停止 SoapVoice 錄音，再通知 server stop；server 連線中斷時排入 `pending_server_stop` 於心跳自動補送。
     - 黃燈流程（D-31-06）：呼叫 archive，202 進入 ARCHIVING 並由心跳自動重試；409 his_failed 進入 ARCHIVE_FAILED 並提示原因，可重複點擊重試；200 成功後通知 SoapVoice archived（若失敗排入 `pending_archived_ack` 重試）。
     - 確認視窗防抖（D-31-12）：依 `(cycle_id, draft_id, draft_version)` 三元組去重，通知只觸發 `open_confirm_window` 一次。
     - 重啟還原（Pitfall 8）：`recover_on_startup` 正確識別兩端進行中錄音以接續循環，對半途中斷之循環判定自動放棄或轉為 INTERRUPTED 供醫師介入。
  5. 測試套件：
     - `tests/test_soapvoice_ipc_contract.py`：以假 HTTP server 驗證 IPC 與 Server 客戶端協定欄位、向後相容、日誌防洩漏等 6 項測試。
     - `tests/test_bar_controller.py`：完整測試 happy path、失敗自癒、離線補送、心跳零 PHI、重啟還原、無 GUI 依賴等 11 項行為。
- **測試結果**：
  - `tests/test_soapvoice_ipc_contract.py` + `tests/test_bar_controller.py`：17 passed。
  - Windows Agent 與快捷列相關既有測試全數通過（50 passed）。

## 偏離與路徑對應
- 無偏離。本計畫全數於 `Elcinsurrence` 倉庫實作，無 git commit。
