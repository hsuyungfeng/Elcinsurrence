# Phase 30-09: MockHIS 探針寫入與讀回驗證報告

## 1. 任務概述與安全原則

依據 `30-09-PLAN.md`、`30-AGY-DISCUSSION.md` 與使用者要求，本階段以 MockHIS 測試替身驗證「寫入 → 讀回 → 雜湊比對」探針流程。

安全標準：
1. **替身限制**：僅對測試替身 `MockHIS`（`deploy/windows_agent/mock_his/mock_his.py`）操作，使用假資料。
2. **零病歷原則**：嚴禁對真實 HIS 視窗、真實病歷或含 PHI 的欄位寫入。
3. **Fail-Closed**：找不到標題含 `MockHIS` 的視窗、或符合的視窗不唯一時立即中止，不做任何寫入。
4. **`--test-vendor` 例外**：預設關閉。僅限測試機與示範資料，才可額外指定標題關鍵字（例如 `志氏`）的視窗；其他視窗仍會被拒絕。

---

## 2. 目前結論

**探針已在兩台 Windows 環境通過實機驗證。**

| 項目 | 狀態 |
|---|---|
| WinBoat（Windows 11）實機探針 | **PASS**（提交 `7c03da5`、`5ab235d`） |
| Windows 11 Pro for Workstations 測試機實機探針 | **PASS**（完整紀錄見 `30-09-PROBE-VERIFICATION-RUN.md`） |
| Linux 端替身單元測試（`tests/test_phase30_probe_mock.py`、`tests/test_phase30_probe_detection.py`） | 通過，共 9 項（2026-11-12 重新執行） |
| 其他 HIS 廠商（Vision、Yaosheng、Minger、Chihshi）實機校正 | **未執行**，屬 Phase 30 後續項目，需現場廠商確認 |
| 修正後的探針（list-windows 版本）在 Windows 上的重跑 | **尚未執行**，見第 8 節 |

---

## 3. 本機替身測試

- **測試檔案**：`tests/test_phase30_probe_mock.py`、`tests/test_phase30_probe_detection.py`
- **執行指令**：
  ```bash
  ELC_ALLOW_NO_AUTH_FOR_TESTS=1 .venv/bin/pytest tests/test_phase30_probe_mock.py tests/test_phase30_probe_detection.py --no-cov
  ```
- **結果**：9 passed（0.10s）

測試涵蓋：
1. 寫入與讀回一致時，`readback_test_passed` 標記為 `True`，`finalize()` 可存檔。
2. 讀回不一致時，標記為 `False`，`finalize()` 拋出 `NotReadyError`。
3. 底層例外（UIA 錯誤、視窗關閉）時優雅回傳 `False`，不崩潰。
4. 探針字串只含安全前綴與英數字，多次產生的 nonce 互不相同。

---

## 4. Windows 探針工具（現況）

- **檔案**：`deploy/windows_agent/mock_his/probe_readback_check.py`
- **視窗鎖定**（2026-11-12 修正）：
  1. 執行 `agent-desktop list-windows`，遞迴解析 JSON，找出標題含 `MockHIS`（或 `--test-vendor` 指定關鍵字）的視窗 ID。
  2. 恰好一個符合 → 以 `agent-desktop snapshot --window-id <id> -i` 取得快照。
  3. 零個或多個符合 → Fail-Closed，中止。
  - 不再使用 `--app pythonw`：Win11 上 pythonw 會產生 IME 等無標題輔助視窗，觸發 `AMBIGUOUS_TARGET`。
- **欄位定位**：優先找「主訴」或 `soap_s` / `txtS`；找不到時退而求其次，取第一個 `Edit` / `Text` / `textfield` 控制項。
- **寫入與讀回**（agent-desktop 2.6 格式）：
  - 寫入：`agent-desktop set-value <REF> <nonce>`
  - 讀回：`agent-desktop get <REF> --property value`，值位於 `data.value`
  - 比對：字串完全相等，且 SHA-256 相等。
- **Nonce**：每次執行產生 `PROBE-<12 位十六進位>`。
- **執行檔搜尋順序**：指定路徑 → `deploy/windows_agent/bin/` → `dist/ElcAgent/_internal/bin/` → `C:\ElcAgent\_internal\bin\` → WinBoat 掛載路徑 → `PATH`。

### 與 2026-11-11 原規劃相比的修正
- 移除不支援的 `--json` 參數（agent-desktop 2.6 的輸出本身即為 JSON）。
- 接受角色 `textfield`（agent-desktop 2.6 將原生 EDIT 標為此角色）。
- 快照改為解析 `data.tree` 巢狀結構，參照欄位為 `ref_id`。
- 視窗鎖定改為 `list-windows` + `--window-id`，取代 `--app`（見第 4 節）。
- `mock_his.py` 由 Tkinter 改為原生 Win32 EDIT/STATIC 控制項；Tkinter 的子控制項對 UIA 不可見，快照只有標題列。

---

## 5. 交付物

- **執行腳本（repo 原始檔）**：`deploy/windows_agent/mock_his/run_probe.bat`（2026-11-12 新增；修正 `if` 區塊內 echo 括號造成的 CMD 語法錯誤，並改為純 ASCII 註解）
- **交接壓縮檔**：`deploy/windows_agent/mock_his/handoff/MockHIS_Probe_Bundle_handoff.zip`（27.1 MB，SHA-256 `7de567fd1e657942cbbc8fe627336fd5889ef7a9147e9ca4f860f006d3725d10`）
  - **注意：此 zip 仍是修正前的版本**（內含舊的 `run_probe.bat` 與舊的 `probe_readback_check.py`）。重新打包會改變 SHA-256，需由使用者確認後再發出。
- **操作說明**：`deploy/windows_agent/mock_his/handoff/MockHIS_探針操作說明.md`

---

## 6. 實機執行 SOP（供其他測試機重跑）

1. 核對壓縮檔 SHA-256 為 `7de567fd...`，不一致則不執行。
2. 解壓縮後雙擊 `run_probe.bat`，保持 MockHIS 視窗開啟。
3. 複製探針完整輸出，連同 Windows 版本回報。

預期成功輸出包含：
```text
[OK] 成功鎖定測試替身視窗 (app=MockHIS ... (id=...))，安全確認通過。
[WRITE] 正在將探針寫入欄位 ...
[READ] 讀回字串: PROBE-XXXXXXXXXXXX
【PASS】讀寫比對完全一致！
```

若視窗不存在，程式會印出 `[FAIL] 安全阻斷`，這是正常的保護機制，不是錯誤。

---

## 7. 規則與檔案變更查核

- [x] 只鎖定 `MockHIS` 測試替身；未對真實 HIS 或真實病歷寫入。
- [x] 探針 nonce 為隨機字串，不含 PHI。
- [x] 本報告更新僅修改文件；未執行 `git commit` / `git push`。
- [ ] **注意**：`deploy/windows_agent/mock_his/` 內的 `mock_his.py` 與 `probe_readback_check.py` 已在提交 `7c03da5` 中修改，不再是「未修改 deploy/ 既有檔案」。此為探針開發所需的變更，已於提交紀錄中說明。
- [ ] 其他 HIS 廠商的實機校正尚未執行。

---

## 8. 測試機實機紀錄與待確認事項

完整 console 輸出與環境資訊見 `30-09-PROBE-VERIFICATION-RUN.md`。摘要：

- 環境：Windows 11 Pro for Workstations（NT 10.0.26200.0）、Python 3.12.10、`agent-desktop.exe` v1.2.0 / Protocol 2.6。
- 結果：寫入 `PROBE-715069B3B663`，讀回值與 SHA-256 完全一致，**PASS**。
- 該次執行使用的是 `list-windows` 修正版，但**修正版的 `list-windows` 解析邏輯是依 `agent-desktop.exe` 內的旗標名稱（`list-windows`、`--window-id`）重建的，JSON 輸出結構未以實機輸出驗證**。
  - 建議：在 Windows 上以修正後的 `probe_readback_check.py` 重跑一次，確認視窗 ID 解析正確。
- 內網伺服器健檢（`/api/health`）回 200，位址已在報告中遮罩。
