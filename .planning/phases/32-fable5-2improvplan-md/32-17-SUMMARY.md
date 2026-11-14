# Phase 32 Plan 17 Summary: B6 首次啟動三步精靈

## 1. 任務概述
- **目標**: 實作 Windows Agent 首次啟動三步精靈（B6），實現正常情況 3 次點擊完成設定（是 → 下一步 → 完成），醫師免打字、免輸入位址或金鑰。
- **純邏輯流程**: 在 `deploy/windows_agent/first_run_wizard.py` 實作 `FirstRunFlow` 狀態機，完全解耦 UI 與外部網路相依性，支援依賴注入。
- **客戶端方法**: 在 `deploy/windows_agent/traffic_bar/server_client.py` 擴充 `CycleServerClient.get_health()` 與 `get_rooms()`。
- **GUI 介面**: 實作 `run_first_run_wizard`（Tkinter 置頂 520x380，14pt 大字、按鈕高度 ≥ 40px），提供「再找一次」、「聯絡安裝人員」及「手動輸入位址」兜底路徑。
- **文字無技術詞彙**: 畫面全部文字抽取出為 `TEXTS` 常數，嚴格排除「JSON」、「金鑰」、「API」、「URL」等技術術語。

## 2. 成果與驗證
- **新增檔案**:
  - `deploy/windows_agent/first_run_wizard.py` (FirstRunFlow, FirstRunResult, run_first_run_wizard, TEXTS)
  - `tests/test_first_run_wizard.py` (10 個測試項目，包含 3 擊路徑、多候選嘗試、找不到重試、手動私有網段驗證、單一診間預選、空診間略過、TEXTS 無技術詞等)
- **修改檔案**:
  - `deploy/windows_agent/traffic_bar/server_client.py` (新增 `get_health`, `get_rooms`)
- **測試結果**:
  - `tests/test_first_run_wizard.py` + `tests/test_bar_controller.py` 共 21 passed，0 failed。
  - `python3 -c "import deploy.windows_agent.first_run_wizard as w; assert callable(w.run_first_run_wizard)"` PASS。

## 3. 威脅模型處置
- T-32-17-01 (Spoofing): 發現伺服器後顯示診所名稱由醫師按「是」確認；記住 `facility_code` 供 C3 心跳自動重探索交叉驗證；手動輸入僅接受 RFC 1918 私有網段 IP。
- T-32-17-02 (Information Disclosure): 精靈流程中僅存取公開之 `/api/health` 與 `/api/rooms`，確認診所前不發送任何病歷或心跳。
