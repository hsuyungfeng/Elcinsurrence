# Phase 31 測試執行報告 (31-TEST-REPORT.md)

本報告記錄 Phase 31（Windows 客戶端紅綠黃快捷列、分段錄音上傳、多診間連線隔離與循環生命週期管理）全套件與專案子集之自動化測試執行結果、需求（D-31-01 至 D-31-44）覆蓋對照表、失敗項目分析以及 Windows 實機人工驗證待辦清單。

---

## 1. 測試執行摘要與指令

### 1.1 Elcinsurrence 根目錄全套件測試
- **執行指令**：
  ```bash
  ELC_ALLOW_NO_AUTH_FOR_TESTS=1 .venv/bin/pytest -q --no-cov
  ```
- **測試結果（原文摘要）**：
  ```
  1502 passed, 2 skipped, 1 deselected, 10 warnings in 110.73s (0:01:50)
  ```
- **狀態**：100% 通過（0 失敗、0 錯誤）。所有後端審查引擎、API 路由、HIS Bridge、資料庫遷移與既有功能無任何回歸。

---

### 1.2 SoapVoice 客戶端全套件測試
- **執行指令**：
  ```bash
  cd /home/hsu/Desktop/Elcinsurrence/SoapVoice && uv run pytest tests/ -q --no-cov
  ```
- **測試結果（原文摘要）**：
  ```
  369 passed, 4 skipped, 3 xfailed, 22 warnings in 50.04s
  ```
- **狀態**：核心套件全數通過（0 失敗、0 錯誤、3 xfailed）。
- **包含 `scripts/` 目錄時之全目錄搜集說明**：
  若執行 `uv run pytest -q --no-cov`（未限定 `tests/`），pytest 會搜集 `scripts/` 下的 13 個手動模型壓測腳本（如 `test_all_models.py`、`test_llama_cpp.py`、`test_soap_pipeline.py`）。該等檔案為包含 CLI 參數之獨立腳本（函式簽章含 `audio_path: str` 等非 fixture 參數），在 pytest 批次執行時會回報 10 項 `fixture not found` Setup Error，此為腳本結構設計使然，非專案程式碼缺陷。

---

### 1.3 Phase 31 專屬功能子集測試

#### (A) Elcinsurrence 端 Phase 31 子集（17 個測試檔案）
- **執行指令**：
  ```bash
  ELC_ALLOW_NO_AUTH_FOR_TESTS=1 .venv/bin/pytest -q \
    tests/test_phase31_contract_fixture.py \
    tests/test_approve_crash_window.py \
    tests/test_bridge_agent_affinity.py \
    tests/test_cycle_state_machine.py \
    tests/test_bar_state.py \
    tests/test_bar_position.py \
    tests/test_traffic_bar_no_recording.py \
    tests/test_cycle_chunks.py \
    tests/test_cycle_drafts.py \
    tests/test_cycle_isolation.py \
    tests/test_client_notify_auth.py \
    tests/test_clients_monitor.py \
    tests/test_soapvoice_ipc_contract.py \
    tests/test_bar_controller.py \
    tests/test_cycle_confirm.py \
    tests/test_cycle_archive.py \
    tests/test_bar_window_logic.py \
    --no-cov
  ```
- **測試結果**：
  ```
  120 passed in 4.67s
  ```
- **涵蓋重點**：
  - 快捷列純邏輯狀態機、按鈕啟停、無錄音依賴、位置記憶與螢幕邊界夾取。
  - 後端循環狀態機（IDLE → RECORDING → GENERATING → READY_TO_CONFIRM → ARCHIVING → IDLE）。
  - 分段上傳驗證、雜湊比對、冪等重傳、草稿產生與循環隔離。
  - 醫師確認交易原子性、HIS_PUSH 崩潰重試與 Agent/Machine 親和性過濾。
  - 診間客戶端心跳監控、來源 IP /24 推斷與未認證遮蔽。

#### (B) SoapVoice 端 Phase 31 子集（7 個測試檔案）
- **執行指令**：
  ```bash
  cd /home/hsu/Desktop/Elcinsurrence/SoapVoice && uv run pytest -q \
    tests/test_segmented_recorder.py \
    tests/test_segment_store.py \
    tests/test_temp_cleanup.py \
    tests/test_chunk_uploader.py \
    tests/test_cycle_pipeline.py \
    tests/test_cycle_session.py \
    tests/test_consultation_ipc.py \
    --no-cov
  ```
- **測試結果**：
  ```
  41 passed in 4.29s
  ```
- **涵蓋重點**：
  - 20 秒音訊即時切段、磁碟先落地防崩潰、無記憶體洩漏。
  - 本機分段存儲、重傳佇列、伺服器 SHA256 回執確認。
  - 磁碟空間上限清理（最舊已確認檔案優先清理、未確認與未封存檔案絕對保留、3 個月過期規則）。
  - 本機 IPC 控制伺服器（Bearer Token 鑑權、循環啟停指令、狀態回報）。

---

## 2. 失敗項目與原因分析

### 2.1 `test_llm_db_cli.py` 既有項目（3 項 XFAIL）
- **測試路徑**：`SoapVoice/tests/test_llm_db_cli.py`
  - `test_icd10_query` → `XFAIL (medical.db (commit ...))`
  - `test_drug_query` → `XFAIL (medical.db (commit ...))`
  - `test_medical_orders` → `XFAIL (medical.db (commit ...))`
- **原因說明**：
  本三項測試依賴本機 `medical.db` 既有資料表內容與特定 commit 狀態，在測試碼中本即標註為 `pytest.mark.xfail`。此為**既有測試狀態**，由 Claude 負責追蹤處理，**非 Phase 31 修改造成**。

### 2.2 `scripts/` 手動腳本（10 項 Setup ERROR）
- **測試路徑**：`SoapVoice/scripts/test_all_models.py`, `scripts/test_llama_cpp.py`, `scripts/test_soap_pipeline.py`
- **原因說明**：
  檔案屬於開發者本地 CLI 手動驗證模型與管線之腳本，函式直接以 `def test_whisper_cpp(audio_path: str)` 宣告輸入參數，未提供 pytest fixture。當全目錄直接執行 `pytest` 時被自動收集而報 `fixture not found`。針對正規測試套件（`tests/`），全數 369 項測試通過，不受影響。

---

## 3. D-31-01 至 D-31-44 需求覆蓋對照表

| 需求代號 | 規格摘要 | 狀態 | 核心實作檔案 | 對應測試檔案 | 備註說明 |
| :--- | :--- | :---: | :--- | :--- | :--- |
| **D-31-01** | 錄音維持在 SoapVoice，快捷列不自行錄音 | ✓ | `deploy/windows_agent/traffic_bar/bar_controller.py` | `tests/test_traffic_bar_no_recording.py` | 快捷列僅以 IPC 傳送控制指令，靜態代碼掃描無音訊錄製依賴 |
| **D-31-02** | 病人資訊由 SoapVoice 擷取，快捷列僅顯示綁定狀態 | ✓ | `SoapVoice/client/lan_client.py`<br>`bar_state.py` | `tests/test_bar_state.py`<br>`tests/test_cycle_session.py` | 快捷列僅呈現 `is_bound` 布林旗標，不傳遞亦不顯示任何病歷 PHI |
| **D-31-03** | 快捷列與 SoapVoice 間 IPC 介面明列且兩倉同步 | ✓ | `31-IPC-CONTRACT.md`<br>`client/consultation_ipc.py` | `tests/test_soapvoice_ipc_contract.py`<br>`tests/test_consultation_ipc.py` | 本機 HTTP 控制通道，採 Bearer token 雙向認證，JSON-RPC 風格介面 |
| **D-31-04** | 本 phase 為獨立 Phase 31，不併入 Phase 30 | ✓ | `.planning/phases/31-*/` | - | 完整獨立 phase 規劃、wave 推進與驗收紀錄 |
| **D-31-05** | 一個循環＝紅(開始)→綠(結束)→草稿產生→確認→黃(封存) | ✓ | `src/elc_audit_engine/cycles/` | `tests/test_cycle_state_machine.py` | 嚴格 6 態有限狀態機，合法狀態躍遷驗證無誤 |
| **D-31-06** | 黃燈封存完成條件：(a) 完整草稿存入 server (b) HIS_PUSH 成功 | ✓ | `src/elc_audit_engine/cycles/archive.py`<br>`api/routes/cycles.py` | `tests/test_cycle_archive.py` | 雙條件皆達標方可轉入 `IDLE` 待命；缺一不可 |
| **D-31-07** | 任一步驟失敗不回待命，保留狀態可重試且冪等 | ✓ | `src/elc_audit_engine/cycles/archive.py` | `tests/test_cycle_archive.py` | 失敗保留原狀態並回傳錯誤訊息，支援原 cycle_id 再次重試封存 |
| **D-31-08** | 醫師未確認前/草稿未產生前黃燈停用 | ✓ | `traffic_bar/bar_state.py` | `tests/test_bar_state.py` | 黃燈僅在 `READY_TO_ARCHIVE` 啟用，其餘狀態點擊一律無效 |
| **D-31-09** | 快捷列置頂、無工作列圖示、可拖曳、位置記憶 | ✓ | `traffic_bar/bar_window.py`<br>`traffic_bar/bar_position.py` | `tests/test_bar_position.py`<br>`tests/test_bar_window_logic.py` | `-topmost`、`-toolwindow`、滑鼠拖曳與本機 JSON 位置持久化保存 |
| **D-31-10** | 收合為紅綠黃三鈕；展開僅顯示狀態文字與連線狀態 | ✓ | `traffic_bar/bar_window.py` | `tests/test_bar_window_logic.py` | 收合尺寸 160×44px，展開僅顯示系統連線與工作階段文字，不露 PHI |
| **D-31-11** | 按鈕狀態機嚴格限制：紅限待命、綠限錄音、黃限已確認 | ✓ | `traffic_bar/bar_state.py` | `tests/test_bar_state.py`<br>`tests/test_bar_window_logic.py` | 非法操作直接忽略並呈現友善狀態列提示 |
| **D-31-12** | 草稿推送採 server 主動通知客戶端，需經認證 | ✓ | `api/routes/client_notify.py` | `tests/test_client_notify_auth.py` | HTTP SSE / 長輪詢推播，未帶有效 API Key 或 Token 者拒絕連線 |
| **D-31-13** | 確認視窗顯示 S/O/A/P、病史、中文摘要與建議項 | ✓ | `src/elc_audit_engine/cycles/drafts.py` | `tests/test_cycle_drafts.py` | 完整結構化字典包含 S/O/A/P、病史與用藥診斷建議 |
| **D-31-14** | HIS_PUSH 沿用 Phase 29/30，未校正機器不得回寫 | ✓ | `src/elc_audit_engine/api/routes/bridge.py` | `tests/test_bridge_agent_affinity.py` | 未校正完成之機器請求 HIS_PUSH 時予以攔截防護 |
| **D-31-15** | Server 依診間分組列出所有客戶端與連線狀態 | ✓ | `src/elc_audit_engine/api/routes/clients.py` | `tests/test_clients_monitor.py` | 依 `room_id` 聚合成診間群組，包含心跳、狀態與離線判定 |
| **D-31-16** | 多客戶端同時連線，單一循環綁單一客戶端，不可混用 | ✓ | `src/elc_audit_engine/cycles/store.py` | `tests/test_cycle_isolation.py` | 以 `client_id` + `cycle_id` 雙重隔離草稿與資料存取 |
| **D-31-17** | 多連線列表僅顯示狀態不顯病歷，點入才顯示待確認草稿 | ✓ | `api/routes/clients.py` | `tests/test_clients_monitor.py` | 列表遮蔽草稿內文，僅返回狀態統計；單一查詢需帶授權 |
| **D-31-18** | 診所由來源 IP /24 推斷 | ✓ | `src/elc_audit_engine/api/utils/ip_infer.py` | `tests/test_clients_monitor.py` | 依 CIDR `/24` 網段比對診所本機伺服器歸屬 |
| **D-31-18a**| IP 僅作歸屬推斷，身分仍以 API Key 驗證 | ✓ | `src/elc_audit_engine/api/dependencies/auth.py` | `tests/test_client_notify_auth.py` | 身分憑證與網路拓撲推斷徹底解耦 |
| **D-31-18b**| 診間 `room_id` 首次設定，院內不需驗證 `room_id` | ✓ | `deploy/windows_agent/config.py` | `tests/test_clients_monitor.py` | 客戶端組態檔指定 `room_id`，後端僅作為分組聚合依據 |
| **D-31-18c**| 診間不得以 IP 推斷 | ✓ | `src/elc_audit_engine/api/utils/ip_infer.py` | `tests/test_clients_monitor.py` | 嚴格遵守規範，IP 僅能推斷 clinic，診間純粹依設定值決定 |
| **D-31-19** | 錄音期間 20 秒分段上傳，不等結束才整段送出 | ✓ | `SoapVoice/client/segmented_recorder.py` | `SoapVoice/tests/test_segmented_recorder.py` | 預設 20 秒定時切段，背景佇列即時異步上傳 |
| **D-31-20** | 每段帶 cycle_id, seq, sha256，server 去重冪等 | ✓ | `src/elc_audit_engine/cycles/chunks.py` | `tests/test_cycle_chunks.py` | 資料庫唯一鍵約束 `(cycle_id, seq)`，重複送出安全略過 |
| **D-31-21** | 本機音訊先落地磁碟，不得僅存於記憶體 | ✓ | `SoapVoice/client/segment_store.py` | `SoapVoice/tests/test_segment_store.py` | 先寫入臨時目錄 WAV 檔並計算雜湊後方送入上傳佇列 |
| **D-31-22** | 斷網或 server 故障時分段留佇列，恢復後補傳 | ✓ | `SoapVoice/client/chunk_uploader.py` | `SoapVoice/tests/test_chunk_uploader.py` | 指數退避重試機制，錄音音軌持續錄製不斷線 |
| **D-31-23** | 綠燈後草稿以完整逐字稿生成，未完顯示上傳中 | ✓ | `SoapVoice/client/cycle_pipeline.py` | `SoapVoice/tests/test_cycle_pipeline.py` | 待全數分段上傳並確認收悉後，方行觸發後端草稿合成 |
| **D-31-24** | 分段切段與上傳屬 SoapVoice 職責，快捷列顯進度 | ✓ | `deploy/windows_agent/traffic_bar/` | `tests/test_bar_state.py` | 快捷列僅依 IPC 事件顯示「上傳中 (2/5)」等進度字串 |
| **D-31-25** | Server 存檔為醫師確認版完整草稿，不只是英文 SOAP | ✓ | `src/elc_audit_engine/cycles/confirm.py` | `tests/test_cycle_confirm.py` | 存檔涵蓋完整繁中對話摘要、病史、建議項與醫師編修註記 |
| **D-31-26** | HIS 只寫入 S/O/A/P，診斷碼、醫令、藥令不寫入 HIS | ✓ | `src/elc_audit_engine/cycles/archive.py` | `tests/test_cycle_archive.py` | HIS 回寫欄位過濾器嚴格排除非 S/O/A/P 之診斷與處方資訊 |
| **D-31-27** | 音檔與逐字稿保存於 server，不寫入 HIS | ✓ | `src/elc_audit_engine/cycles/store.py` | `tests/test_cycle_chunks.py` | 音訊檔案留存於伺服端儲存體，與 HIS 寫入任務徹底隔離 |
| **D-31-28** | 音檔與逐字稿依 cycle_id 索引，供後續調閱 | ✓ | `src/elc_audit_engine/cycles/store.py` | `tests/test_cycle_chunks.py` | 以 `cycle_id` 為外鍵建立結構化分段與逐字稿關聯索引 |
| **D-31-29** | Server 端音檔逐字稿保存期限待 Q9 決定，目前不自動刪除 | ✓ | `src/elc_audit_engine/cycles/` | `tests/test_cycle_archive.py` | 符合規範：Server 端未加入自動清除定時任務，完整保留 |
| **D-31-30** | 客戶端暫存僅在 server 確認收到（sha256 相符）後可刪 | ✓ | `SoapVoice/client/temp_cleanup.py` | `SoapVoice/tests/test_temp_cleanup.py` | 清理引擎嚴格比對 `server_acked_sha256` 集合，未確認者拒絕刪除 |
| **D-31-31** | 本機暫存超過大小上限才刪最舊已確認檔案（預設 5GB） | ✓ | `SoapVoice/client/temp_cleanup.py` | `SoapVoice/tests/test_temp_cleanup.py` | LRU 佇列清理演算法，未達 5GB 上限時不執行磁碟清理 |
| **D-31-32** | 未被 server 確認的檔案絕不刪除，無論大小 | ✓ | `SoapVoice/client/temp_cleanup.py` | `SoapVoice/tests/test_temp_cleanup.py` | 極限容量測試下，未確認檔案具最高保護層級，絕不誤刪 |
| **D-31-33** | 循環未封存（黃燈未完成）時暫存檔一律保留 | ✓ | `SoapVoice/client/temp_cleanup.py` | `SoapVoice/tests/test_temp_cleanup.py` | 活躍或待確認循環保護旗標生效，確保醫師確認前音訊完整 |
| **D-31-34** | 櫃台快捷列讀取健保雲端病歷情境規劃 | ✓ | `31-COUNTER-CLOUD-FEASIBILITY.md` | - | 31-03 Spike 產出櫃台雲端病歷架構評估與同步規格 |
| **D-31-35** | 雲端病歷擷取方式可行性調查（不猜測實作） | ✓ | `31-COUNTER-CLOUD-FEASIBILITY.md` | - | 完整評估 Web API、VPN 虛擬通道、UIA 與剪貼簿攔截可行性與風險 |
| **D-31-36** | 櫃台功能不得阻塞診間主流程 | ✓ | `31-COUNTER-CLOUD-FEASIBILITY.md` | - | 規範櫃台連線採獨立非同步佇列與通道，不干擾診間音訊流 |
| **D-31-37** | HIS_PUSH 任務綁定 machine_id，避免跨機冒領 | ✓ | `src/elc_audit_engine/api/routes/bridge.py` | `tests/test_bridge_agent_affinity.py` | `list_pending_jobs` 強制驗證請求者之 `machine_id` 嚴格吻合 |
| **D-31-38** | approve_draft_record 交易一致性與崩潰恢復 | ✓ | `src/elc_audit_engine/cycles/confirm.py` | `tests/test_approve_crash_window.py` | 模擬中途崩潰情境，重啟後安全自癒重排佇列，無卡死風險 |
| **D-31-39** | 循環確認以 cycle_id -> draft_id 直接開啟，不抓全部 | ✓ | `src/elc_audit_engine/cycles/drafts.py` | `tests/test_cycle_drafts.py` | 專用端點 `GET /api/cycles/{cycle_id}/draft` 直接導向專屬草稿 |
| **D-31-40** | 醫師預覽畫面同時顯示 SOAP 英文與中文譯文 | ✓ | `src/elc_audit_engine/cycles/drafts.py` | `tests/test_cycle_drafts.py` | 草稿資料結構同時承載英文臨床專業 SOAP 與中文溝通摘要對照 |
| **D-31-41** | HIS 只寫入 S/O/A/P，原始譯文不寫入 HIS（避免過長） | ✓ | `src/elc_audit_engine/cycles/archive.py` | `tests/test_cycle_archive.py` | 回寫 HIS Payload 精準封裝 S/O/A/P，完全剝除原始對話譯文 |
| **D-31-42** | 原始譯文指逐字稿完整譯文，排除於 HIS 寫入清單 | ✓ | `src/elc_audit_engine/cycles/archive.py` | `tests/test_cycle_archive.py` | 語意定義與過濾邏輯精確對齊，確保符合健保申報病歷長度規範 |
| **D-31-43** | 客戶端音檔逐字稿保留上限 3 個月，超期且已確認方可刪 | ✓ | `SoapVoice/client/temp_cleanup.py` | `SoapVoice/tests/test_temp_cleanup.py` | 90 天老化判定條件：`age > 90d AND server_acked == True` |
| **D-31-44** | 3 個月上限只適用於客戶端，不適用於 server 端 | ✓ | `src/elc_audit_engine/cycles/` | `tests/test_cycle_archive.py` | Server 端依據醫療法規與 Q9 要求完整留存，不套用 90 天刪除條款 |

---

## 4. Windows 實機人工驗證項目仍待辦

本套件之單元測試、契約測試、狀態機模擬測試與靜態架構測試已 100% 通過。依據 `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-WINDOWS-MANUAL-VERIFY.md`，下列 8 個涉及實體 Windows 作業系統圖形子系統（GDI / DWM）、多螢幕熱插拔與真實診所 HIS 交互之項目，需在 Windows 10/11 實體工作站進行人工查驗：

1. **視窗置頂性與無標題列驗證 (D-31-09)**：
   - 驗證在最大化全螢幕應用程式或 HIS 視窗覆蓋下，快捷列依然置頂可見。
   - 驗證 Windows 系統工作列上無快捷列多餘按鈕。
2. **不搶奪鍵盤打字輸入焦點驗證 (D-31-09)**：
   - 驗證醫師在 HIS 病歷欄位連續打字時，滑鼠點擊快捷列展開或拖曳，文字游標不跳開、字元不遺失。
3. **滑鼠拖曳平滑度與重啟位置記憶驗證 (D-31-09)**：
   - 驗證拖曳手柄滑順無殘影，重新啟動快捷列後精準還原於上次釋放之螢幕坐標。
4. **多螢幕邊界夾取與拔線防脫逸驗證 (Pitfall 11)**：
   - 驗證於雙螢幕環境將快捷列置於副螢幕，斷開副螢幕後重啟，視窗自動回彈至主螢幕可見範圍。
5. **與診所 HIS 視窗 UI Automation (UIA) 互不干擾驗證**：
   - 驗證快捷列浮動於 HIS 輸入框旁時，背景 UIA 探針自動化定位與 Nonce 雜湊比對不受任何干擾。
6. **收合與展開動畫視覺驗證 (D-31-10)**：
   - 驗證三鈕收合 (160×44px) 與展開狀態切換平順，文字排版清晰且無任何 PHI 資訊外洩。
7. **斷線與非法操作防護提示驗證 (D-31-11)**：
   - 驗證 SoapVoice 離線或後端斷網時，按鈕鎖定提示與狀態文字準確反應連線中斷。
8. **實機端到端完整循環驗收 (E2E Loop, D-31-05 ~ D-31-08)**：
   - 配合診間麥克風真實錄製 30 秒對話，依序驗收：紅燈啟動 → 綠燈切段上傳完成 → 醫師確認視窗校閱 → 黃燈觸發封存與 HIS 填寫成功 → 順利回歸紅燈待命。

---

## 5. 結論

1. **測試全面達標**：
   - 後端審查引擎與路由套件：**1502 項測試全數通過**（0 失敗、0 回歸）。
   - 客戶端語音核心套件：**369 項測試全數通過**（3 項既有 XFAIL 標註，無新增失敗）。
   - Phase 31 專屬跨倉子集：**161 項測試 100% 通過**（Elcinsurrence 120 項 + SoapVoice 41 項）。
2. **規格契約完全覆蓋**：
   - D-31-01 至 D-31-44 共 44 項需求指標均已落實為具體模組或標準規範文件，覆蓋率 100%。
   - 關鍵架構（20 秒切段先落地、本機 IPC Bearer Token 鑑權、循環狀態機、HIS_PUSH 崩潰重試與 Machine 親和性、未確認音訊永久保留、伺服端完整存檔）均通過嚴格的單元與整合驗證。
3. **無任何代碼與資料庫副作用**：
   - 全程遵守規範，未變動根目錄 `boot31.py` 與 SoapVoice Chroma 向量資料庫，未進行任何未授權的 git commit 或 push。
   - 專案已就緒，可交付 Windows 實機測試人員依 `31-WINDOWS-MANUAL-VERIFY.md` 進行最終驗收。
