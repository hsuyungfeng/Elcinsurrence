# Phase 30-09: MockHIS 探針寫入與讀回驗證報告

## 1. 任務概述與安全原則

依據 `30-09-PLAN.md`、`30-AGY-DISCUSSION.md` 與使用者要求，本階段以 MockHIS 測試替身驗證「寫入 → 讀回 → 雜湊比對」探針流程。

安全標準：
1. **替身限制**：僅對測試替身 `MockHIS`（`deploy/windows_agent/mock_his/mock_his.py`）操作，使用假資料。
2. **零病歷原則**：嚴禁對真實 HIS 視窗、真實病歷或含 PHI 的欄位寫入。
3. **Fail-Closed**：找不到標題含 `MockHIS` 的視窗時立即中止，不做任何寫入。
4. **`--test-vendor` 例外**：預設關閉。僅限測試機與示範資料，才可額外指定標題關鍵字（例如 `志氏`）的視窗；其他視窗仍會被拒絕。

---

## 2. 目前結論

**Windows 端 WinBoat 實機探針已通過**（write/readback nonce 完全一致）。
依據提交紀錄 `7c03da5`（"Verified on WinBoat: probe PASS"）與 `5ab235d`。

| 項目 | 狀態 |
|---|---|
| Linux 端替身單元測試（`tests/test_phase30_probe_mock.py`） | 通過，4 項（2026-11-12 重新執行確認） |
| WinBoat（Windows 11）實機探針 | **PASS**（寫入 nonce 與讀回值一致） |
| 其他 HIS 廠商（Vision、Yaosheng、Minger、Chihshi）實機校正 | **未執行**，屬 Phase 30 後續項目，需現場廠商確認 |

---

## 3. 本機替身測試

- **測試檔案**：`tests/test_phase30_probe_mock.py`
- **執行指令**：
  ```bash
  ELC_ALLOW_NO_AUTH_FOR_TESTS=1 .venv/bin/pytest tests/test_phase30_probe_mock.py --no-cov
  ```
- **結果**：4 passed（0.08s）

測試涵蓋：
1. 寫入與讀回一致時，`readback_test_passed` 標記為 `True`，`finalize()` 可存檔。
2. 讀回不一致時，標記為 `False`，`finalize()` 拋出 `NotReadyError`。
3. 底層例外（UIA 錯誤、視窗關閉）時優雅回傳 `False`，不崩潰。
4. 探針字串只含安全前綴與英數字，多次產生的 nonce 互不相同。

---

## 4. Windows 探針工具（現況）

- **檔案**：`deploy/windows_agent/mock_his/probe_readback_check.py`
- **安全鎖定**：
  - 快照掃描只針對 `pythonw` / `python` / `MockHIS` 程序；不掃描 VisionHIS 等真實 HIS 程序。
  - 必須偵測到含 `MockHIS` 的 Win32 視窗標題，或快照中含 `MockHIS` / `測試替身` 字串，才會繼續。
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
- 新增 `pythonw` 程序候選。
- `mock_his.py` 由 Tkinter 改為原生 Win32 EDIT/STATIC 控制項；Tkinter 的子控制項對 UIA 不可見，快照只有標題列。

---

## 5. 交付物

- **交接壓縮檔**：`deploy/windows_agent/mock_his/handoff/MockHIS_Probe_Bundle_handoff.zip`（27.1 MB，SHA-256 `7de567fd1e657942cbbc8fe627336fd5889ef7a9147e9ca4f860f006d3725d10`）
- **操作說明**：`deploy/windows_agent/mock_his/handoff/MockHIS_探針操作說明.md`
- 壓縮檔內含 `run_probe.bat`，可一鍵開啟 MockHIS 並執行探針；首次執行若無 Python 3.12，會自動安裝給目前使用者。

---

## 6. 實機執行 SOP（供其他測試機重跑）

1. 核對壓縮檔 SHA-256 為 `7de567fd...`，不一致則不執行。
2. 解壓縮後雙擊 `run_probe.bat`，保持 MockHIS 視窗開啟。
3. 複製探針完整輸出，連同 Windows 版本回報。

預期成功輸出包含：
```text
[OK] 成功鎖定測試替身視窗 (app=...)，安全確認通過。
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
