# Phase 30 討論與持續測試報告（30-AGY-DISCUSSION.md）

**記錄時間：** 2026-11-10  
**執行者：** Antigravity (AGY)  
**討論主題：** Phase 30 核心測試驗證、WinBoat 待命現況與 30-09（真實 HIS 實機 UIA 探針寫入讀回）安全測試方案

---

## 一、Phase 30 相關自動化測試執行結果

依指令執行與 Phase 30（Windows Agent、校正精靈、SOAP 審查、STANDBY 待命模式）相關之全套測試：

### 1. 測試指令
```bash
ELC_ALLOW_NO_AUTH_FOR_TESTS=1 .venv/bin/pytest \
  tests/test_agent_default_paths.py \
  tests/test_agent_desktop_bridge.py \
  tests/test_agent_discovery.py \
  tests/test_agent_entrypoint.py \
  tests/test_agent_runner_windows.py \
  tests/test_windows_agent.py \
  tests/test_calibration_model.py \
  tests/test_calibration_store.py \
  tests/test_calibration_wizard.py \
  tests/test_his_matcher.py \
  tests/test_review_client.py \
  tests/test_window_topmost.py \
  tests/test_soap_recording_contract.py \
  tests/test_auto_accept_toggle.py \
  tests/test_soap_review_api.py \
  tests/test_phase29_soap_review_api.py \
  tests/test_soap_draft_states.py \
  tests/test_soap_comparison.py \
  tests/test_soap_workbench_ui.py \
  tests/test_soapvoice_ingest.py \
  --no-cov
```

### 2. 測試統計
- **總測試檔案數：** 20 個測試模組
- **測試收集總數：** 250 個測試案例
- **通過數量：** **250 passed**
- **失敗數量：** **0 failed**
- **執行耗時：** 2.24 秒
- **程式碼修改限制：** 本次測試執行與報告產出過程中，**未修改任何 `src/` 或 `deploy/` 檔案**。

### 3. 重點測試領域覆蓋驗證
1. **Windows Agent 啟動與 STANDBY 模式：** 驗證未校正時自動啟動校正精靈、關閉後平順進入 STANDBY 待命輪詢（`calibrated=False`、`his_status="STANDBY"`），且任何未校正的寫入任務立即回報 `uncalibrated_profile` 阻絕（Fail-closed）。
2. **校正模型與儲存（Calibration Store & Wizard）：** 驗證 JSON Schema 儲存、雜湊比對、`is_ready` 門檻（必填 6 項全部 confirmed 且 readback_test_passed=True）。
3. **模糊匹配（HIS Matcher）：** 驗證四大 HIS 廠商（展望、耀聖、佲格、志氏）欄位結構比對與非 S/O/A/P 欄位（ICD10、ORDER、MED）唯讀建議特性。
4. **SOAP 審查與自動接入（Auto-Accept Toggle & Review Queue）：** 驗證區網免金鑰錄音接收、開關切換審計日誌（無 PHI）、每案先審查狀態機轉換。

---

## 二、Phase 30 當前進度與實機驗收現況

1. **已交付項目（30-01 至 30-08、30-10）：**
   - 後端審查路由、佇列與私有 IP 錄音接收端點（30-01、30-04）。
   - Tkinter 審查懸浮視窗與客戶端（30-02）。
   - 自動接入審計開關與全域金鑰權限放寬（30-03）。
   - 校正資料模型、本機儲存與 Tkinter 校正精靈（30-05、30-06）。
   - 區網子網與廣播探索（30-07）。
   - Windows 可攜式解壓即用打包規範、SHA256 校驗與進入點（30-08）。
   - 跨倉 SoapVoice 錄音上傳端點與重試佇列（30-10）。
2. **WinBoat Windows 11 實機最新進展：**
   - WinBoat 容器（`dockur/windows:5.14`）於本機 KVM 加速順暢運行。
   - 修復 PyInstaller 凍結環境下的 `No module named 'config'` 匯入問題（於 `config/__init__.py` 補齊並在 `case_store/store.py` 加入安全降級保護）。
   - 新版打包 `ElcAgent.exe` 覆蓋至 `C:\ElcAgent` 實機測試，關閉校正精靈後**無任何崩潰**，平順進入「連線待命（STANDBY）」心跳輪詢迴圈。

---

## 三、30-09（真實 HIS 實機 UIA 探針寫入讀回）測試方案

依據 30-09-PLAN.md 與系統最高安全守則：**絕對不得對任何真實 HIS 視窗或真實病患病歷寫入**。為此，30-09 必須嚴格切分為「替身驗證」與「實機安全邊界」兩大維度執行。

### 1. 方案 A：可在本機／模擬環境以替身驗證的項目（完全隔離、零風險）

| 項目編號 | 驗證項目 | 替身實作方式 | 預期驗證效益 |
| :--- | :--- | :--- | :--- |
| **A-1** | **UIA 替身視窗 (Mock HIS)** | 在 WinBoat 或本機以 Python Tkinter/WinForms 撰寫極輕量 `MockHIS.py`（視窗標題設為 `VisionHIS.exe`，內含 `txtS`、`txtO`、`txtA`、`txtP`、`txtPid`、`btnSave` 等控制項）。 | 讓 `agent-desktop.exe snapshot` 能夠在 Windows 核心下抓到完整 UIA 元件樹，供校正精靈完成九大欄位自動比對。 |
| **A-2** | **探針寫入與讀回演算法** | 使用動態隨機 nonce 字串（例如 `PROBE-TEST-84A1`）寫入替身文字框，隨即透過 UIA `get_value` 讀回並計算 content hash 比對。 | 驗證 `write_and_read_fn` 邏輯能正確將探針寫入且比對一致，將 `readback_test_passed` 標記為 `True`。 |
| **A-3** | **校正檔產出與狀態轉移** | 替身完成校正後，檢驗 `%LOCALAPPDATA%\ElcAgent\calibration\vision_<machine_id>.json` 是否符合 Schema，且未夾帶病歷資料。 | 驗證 `ElcAgent.exe` 於下次啟動或重新整理時，自動從 `STANDBY` 切換為 `READY`（已校正模式）。 |
| **A-4** | **唯讀建議欄位保護** | 替身介面提供診斷碼、醫令、藥令欄位，校正精靈標示為「僅供參考」。 | 驗證精靈不提供確認寫入按鈕，且產出之設定檔中上述三項之 `kind` 必為 `advisory`。 |

### 2. 方案 B：必須在 Windows 實機（WinBoat 或診間 Windows）驗證的項目

| 項目編號 | 實機項目 | 為什麼無法在 Linux 完成 | 驗證方式 |
| :--- | :--- | :--- | :--- |
| **B-1** | **真實 UIAutomationClient.dll 運作** | Wine 缺少完整的 Windows UI Automation 核心支援，只有真正的 Windows 核心（WinBoat Windows 11 或實體機器）具備完整的 UIA 元件樹反射。 | 於 WinBoat Windows 11 CMD 執行 `_internal\bin\agent-desktop.exe snapshot`，確認回傳 JSON 包含所有 Windows 視窗節點。 |
| **B-2** | **視窗焦點與鍵盤輸入相容性** | 某些老舊 HIS（VB6 / Delphi / Win32）不支援 UIA `ValuePattern.SetValue`，需仰賴 SendKeys 或焦點設定。 | 透過實機驗證探針寫入是採用 ValuePattern 還是鍵盤模擬，確保文字框游標定位正確。 |
| **B-3** | **中文編碼與視窗顯示** | Tkinter 中文字型渲染、PowerShell 主控台 CP950/UTF-8 解碼、以及繁體中文輸入無亂碼。 | 實機肉眼觀察精靈視窗之「主觀陳述 (S)」、「客觀檢查 (O)」等標籤無方塊或亂碼。 |

---

## 四、安全風險與前置防護機制（Fail-Closed Boundaries）

針對「絕不寫入真實 HIS 與真實病歷」之最高指示，訂定下列四道剛性防線：

1. **防線一：環境隔離（禁止開啟生產環境 HIS）**
   - 30-09 測試階段**禁止在掛載正式診所資料庫的 HIS 環境下執行**。
   - 一律使用「替身視窗（Mock HIS）」或「無網路資料庫連線的單機測試展示版（Demo HIS）」。
2. **防線二：病歷號動態比對阻絕（Patient Match Verification）**
   - `WindowsAgent.execute_job()` 內建 `current_patient_getter` 檢查：若當前畫面病歷號與工作任務指定的 `case_id` 不符，立即拋出 `patient_check_unavailable` / `patient_mismatch` 並終止任務，絕不盲目寫入。
3. **防線三：校正探針永不觸碰儲存按鈕（No Save Triggering during Probe）**
   - 校正階段的「探針讀寫測試」**僅限於向文字輸入框寫入測試字串並立即讀回比對**，校正程式**嚴禁向 `save_button` 發送任何 Invoke/Click 訊號**。儲存按鈕僅記錄其 `automation_id`/`name` 定位識別碼。
4. **防線四：版本庫乾淨限制（No Commit, No Push）**
   - 本次討論與測試維持本地工作目錄，不建立新分支，不執行 `git commit`，不執行 `git push`。

---

## 五、下一步實施建議（Prerequisites & Next Steps）

1. **替身工具部署（可立即實施）：**
   - 在本機撰寫一個簡單的 `MockHIS.py`，包裝成符合展望或耀聖結構的視窗，放置於共用資料夾，由 WinBoat Windows 11 啟動。
2. **探針接線完善：**
   - 於 `deploy/windows_agent/calibration_wizard.py` 確認 `write_and_read_fn` 已正確對接 `agent-desktop` 的控制命令，進行安全探針寫入與讀回測試。
3. **保持待命狀態：**
   - 當前系統在 WinBoat 內處於健康且安全的 STANDBY 狀態，任何伺服器心跳回報正常，隨時可切入替身校正流程。
