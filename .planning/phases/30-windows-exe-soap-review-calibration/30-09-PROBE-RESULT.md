# Phase 30-09: MockHIS 探針寫入與讀回驗證報告

## 1. 任務概述與安全原則

依據 `30-09-PLAN.md`、`30-AGY-DISCUSSION.md` 以及使用者具體要求，本階段執行真實 HIS 實機探針的前置安全驗證。
核心安全標準如下：
1. **替身限制**：僅對測試替身 `MockHIS`（`deploy/windows_agent/mock_his/mock_his.py`）進行操作，以假資料（Dummy Data）測試。
2. **絕對零病歷原則**：嚴禁任何針對真實 HIS 視窗、真實病歷資料庫或包含真實 PHI 的欄位進行寫入。
3. **無副作用守則**：不執行 `git commit`、不執行 `git push`、不修改 `src/` 與 `deploy/` 中既有之任何檔案。

---

## 2. 本機替身探針測試結果（Automated Test Suite）

在 Linux 開發環境建立了完整的 MockHIS 驅動替身測試：
- **測試檔案**：`tests/test_phase30_probe_mock.py`
- **執行指令**：
  ```bash
  ELC_ALLOW_NO_AUTH_FOR_TESTS=1 .venv/bin/pytest tests/test_phase30_probe_mock.py --no-cov
  ```
- **測試結果**：**4 passed in 0.10s** (100% 通過)

### 測試案例清單與驗證項目：
1. `test_probe_write_and_readback_success_marks_passed_true`:
   - 模擬 MockHIS `soap_s` 欄位寫入隨機產生之 Nonce（`PROBE-<UUID>`）。
   - 讀回並計算 SHA-256 雜湊比對。
   - 驗證 `wizard.readback_test()` 回傳 `True` 且 `profile.readback_test_passed` 成功標記為 `True`。
   - 驗證在所有項目確認且探針通過下，`wizard.finalize()` 可順利儲存 Profile。
2. `test_probe_readback_mismatch_marks_passed_false_and_blocks_finalize`:
   - 模擬欄位讀回值不一致（如游標跳位、字串被截斷或為空）。
   - 驗證 `wizard.readback_test()` 回傳 `False` 且 `profile.readback_test_passed` 保持為 `False`。
   - 驗證呼叫 `wizard.finalize()` 時會拋出 `NotReadyError`，嚴密阻絕未經驗證之設定檔生效。
3. `test_probe_readback_exception_handled_gracefully`:
   - 模擬底層 UIA 例外或目標視窗異常關閉。
   - 驗證捕捉例外後不崩潰，優雅回傳 `False`。
4. `test_probe_nonce_hash_uniqueness_and_no_phi`:
   - 驗證探針字串僅包含安全的前綴與英數字，絕不含有病患身分、診斷、處方等 PHI 資訊。
   - 驗證多次產生的 Nonce 與 SHA-256 具備高度唯一性。

---

## 3. Windows 端驗證工具設計與安全防護機制

已撰寫 Windows 端專用之驗證腳本：
- **檔案路徑**：`deploy/windows_agent/mock_his/probe_readback_check.py`

### 核心安全防護機制：
1. **嚴格標題關鍵字鎖定**：
   - 執行 `agent-desktop snapshot` 時，程式會逐一檢查視窗元素之名稱與標題。
   - 必須明確偵測到包含 `"MockHIS"` 或 `"測試替身"` 字樣方可繼續；若僅有真實 HIS 視窗或一般系統視窗，立即觸發 **Fail-Closed** 安全中斷，拒絕執行後續任何操作。
2. **隨機 Nonce 與雙重驗證**：
   - 每次執行動態產生 `PROBE-<12位隨機十六進位碼>`，並計算 SHA-256 雜湊。
   - 透過 `agent-desktop set-value` 寫入指定欄位。
   - 透過 `agent-desktop get-value` 讀回欄位值。
   - 雙重檢查：(1) 字串完全相等、(2) SHA-256 雜湊完全相等。
3. **無相依獨立執行**：
   - 支援自動搜尋 `C:\ElcAgent\_internal\bin\agent-desktop.exe` 或自訂路徑，具備完整的錯誤代碼回傳機制。

---

## 4. Windows 實機 / WinBoat 執行步驟指南

在 WinBoat (Windows 11) 或 Windows 測試實機上執行驗證之標準 SOP：

### 步驟 1：啟動 MockHIS 替身視窗
在 Windows PowerShell 視窗中執行：
```powershell
# 啟動 MockHIS 測試替身（保持視窗開啟於桌面上）
python deploy\windows_agent\mock_his\mock_his.py
```
> **注意**：視窗標題應為「MockHIS (測試替身 - 假資料專用)」，內部為測試用病患「TEST-P001 陳小明」。

### 步驟 2：執行探針寫入與讀回安全檢查
開啟另一個 PowerShell 視窗執行：
```powershell
# 自動搜尋 agent-desktop.exe 並執行探針測試
python deploy\windows_agent\mock_his\probe_readback_check.py

# 或手動指定 agent-desktop.exe 執行檔路徑：
python deploy\windows_agent\mock_his\probe_readback_check.py C:\ElcAgent\_internal\bin\agent-desktop.exe
```

### 步驟 3：預期輸出確認
若驗證成功，終端機將印出：
```text
============================================================
【Phase 30-09】MockHIS 替身探針寫入與讀回安全檢測
============================================================
[OK] 使用 agent-desktop: C:\ElcAgent\_internal\bin\agent-desktop.exe
[CHECK] 尋找標題含 'MockHIS' 的視窗快照...
[OK] 成功鎖定測試替身視窗 (app=VisionHIS)，安全確認通過。
[OK] 鎖定測試欄位: 主訴 (S) (ref=@ref/s)
[PROBE] 產生隨機探針 Nonce: PROBE-A1B2C3D4E5F6
[PROBE] 預期 SHA-256: 7d25...
[WRITE] 正在將探針寫入欄位 @ref/s...
[OK] 探針寫入成功。
[READ] 正在從欄位 @ref/s 讀回值...
[READ] 讀回字串: PROBE-A1B2C3D4E5F6
[READ] 讀回 SHA-256: 7d25...
------------------------------------------------------------
【PASS】讀寫比對完全一致！
  - 探針寫入值: PROBE-A1B2C3D4E5F6
  - 欄位讀回值: PROBE-A1B2C3D4E5F6
  - 雜湊一致性: 7d25... == 7d25...
  - 結論: readback_test_passed 驗證通過，符合 30-09 探針驗收標準。
------------------------------------------------------------
```

若未開啟 MockHIS 視窗，程式將自動阻斷並安全退出：
```text
[FAIL] 安全阻斷：未偵測到任何包含 'MockHIS' 的測試替身視窗！
  保護原則：為避免寫入真實病歷，本工具『嚴禁』對非 MockHIS 視窗進行任何探針操作。
```

---

## 5. 規則與檔案變更查核清單

- [x] 僅鎖定 `MockHIS` 測試替身，絕對未對任何真實 HIS 視窗或真實病歷進行寫入。
- [x] 未執行 `git commit`、未執行 `git push`。
- [x] 未修改 `src/` 與 `deploy/` 中既有之任何檔案（僅於 `deploy/windows_agent/mock_his/` 與 `tests/` 建立新檔案）。
- [x] 所有探針隨機 Nonce 均為安全隨機字串，無任何 PHI 資訊。
- [x] 相關單元測試 4 項全數通過，Phase 30 相關測試 165 項無回歸錯誤。
