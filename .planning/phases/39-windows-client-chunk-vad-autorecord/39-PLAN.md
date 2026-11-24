# Phase 39 計畫：Windows Client 分段音訊與語音偵測自動錄音（VAD Auto-Record）之 Server 端實作與 Windows 整合測試計畫

**狀態**：CONDITIONAL PASS（有條件通過，待補項目見下方「待補項目」）  
**審查紀錄**：agy 複審（plan 模式）判定不符 APPROVED，建議 CONDITIONAL PASS；已確認 T2.4 M6 測試缺口（已修正為 422）。  
**建立日期**：2026-11-24  
**修正日期**：2026-11-24  
**負責角色**：
- 規劃架構 (Coordinator)：Antigravity
- 審查確認 (Planchecker)：Herdr `claude` (pane `w7:pD`)
- 測試驗證 (Tester)：Herdr `hermes` (pane `w7:pE`)

---

## 〇、第一輪審查修正紀錄

| 編號 | 等級 | 審查發現 | 本次修正 |
|---|---|---|---|
| H1 | HIGH | `trigger_mode` / `preroll_sec` 掛在 `cycle_chunks`，但觸發方式是循環（cycle）層級屬性 | 改掛 `recording_cycles`；建立循環端點為 `POST /api/cycles`（`cycles/store.py:create_cycle`），資料表與 migration 納管於 `case_store/db.py:init_schema` |
| H2 | HIGH | `vad_listening` 實際需改 `cycles/presence.py`，計畫未列 | Task 1 檔案清單加入 `cycles/presence.py`；補 bool 驗證（排除 Python `bool` 為 `int` 子類別的問題） |
| H3 | HIGH | 測試使用「真實門診錄音」與 PHI 規則衝突 | 改用 `SoapVoice/static/*.wav` 示範檔或合成音；寫明去識別理由 |
| M4 | MEDIUM | `validate_wav_chunk` 不剥離 header，且未檢查 data 大小與 `len(data)` 一致性 | 改為驗證既有串接行為，並新增一致性檢查 |
| M5 | MEDIUM | 「消除接縫爆音」不可量測 | 改為 frame 數、位元組奇偶、sha256 三項可量測條件 |
| M6 | MEDIUM | `seq >= total_chunks` 的分段被靜默忽略 | 新增拒絕規則與測試 |
| M7 | MEDIUM | `raw_pcm` 記憶體無上限 | 新增總分段數上限（預設 120 段，約 2 小時）與總大小上限（預設 250 MiB） |
| M8 | MEDIUM | VAD 與 pre-roll 無法由伺服器驗證 | 明寫伺服器測試範圍僅限「前綴音訊串接」 |
| L9 | LOW | ASR 測試缺環境保護 | 加 `skipif`，標記非 CI 必跑 |
| L10 | LOW | 驗收 3、4 依賴外部 Herdr pane | 改為人工簽核項目，與自動化測試分開 |

**既有行為（回歸即可，不列為新工作）**：
- 去重與冪等：相同 sha256 回 `duplicate=true`；不同雜湊拋 `ChunkConflictError`；由 `BEGIN IMMEDIATE` 交易保證並發安全（`test_store_chunk_duplicate_idempotent`、`test_store_chunk_concurrency` 已覆蓋）。
- finalize 重送等冪：同 `total_chunks` 且同 `audio_sha256` 時直接回傳成功（`chunks.py` finalize 前段）。
- 缺段預檢：`MissingChunksError`。
- 亂序抵達：finalize 以 `ORDER BY seq` 串接，缺段才報錯。

---

## 一、目標與範疇 (Goals & Scope)

針對「Windows Client 端模型的分段錄音是否可行」與「錄音機開啟時，以語音偵測自動觸發錄音（減少忘記按鍵）」兩項結論：

1. **Server 端實作與防護加固 (Server-side Implementation)**：
   - **分段 WAV 驗證與 PCM 串接一致性**：確認既有的 PCM 串接（`finalize` 以 `wave.readframes` 逐段讀取）會剥離各段 RIFF header，並補上「宣告 data 大小與實際位元組不一致」的拒絕規則，避免截斷分段被靜默接受。
   - **VAD 觸發中繼欄位（Cycle-level Trigger Metadata）**：在 `recording_cycles` 記錄 `trigger_mode`（`manual` | `vad_auto`）與 `preroll_sec`；在心跳 `/api/clients/heartbeat` 接受 `vad_listening: bool`，寫入 presence 紀錄。
   - **分段容錯與邊界防護**：拒絕 `seq >= total_chunks` 的分段；對總分段數與總大小設上限，控制 finalize 時的記憶體用量。既有的去重、等冪、缺段行為列為回歸測試。
2. **端到端模擬整合測試 (Integration Tests on Server)**：
   - 建立 `tests/test_windows_client_chunk_e2e.py`。
   - **素材**：使用 `SoapVoice/static/*.wav` 示範檔（8 檔之一）或以合成音生成，**不使用真實病患錄音**。理由：AGENTs.md 規定 PHI 不得進入日誌、審計與 git；測試素材若含真實病患語音，會違反此規定。
   - 切分成 5–10 段，每段帶獨立 RIFF 標頭，模擬 Windows Client（`SoapVoice`）上傳。
   - 模擬網路斷線重送與亂序抵達。
   - 呼叫 `POST /api/cycles/<cycle_id>/finalize`，驗證產出 `full.wav`。
   - **ASR 測試**（T2.1 的轉錄部分）以 `pytest.mark.skipif` 保護：sherpa-onnx 模型不存在時跳過，**標記為非 CI 必跑**，由開發機手動執行。

3. **Windows Client 端測試計畫與規格交付 (Windows Client Test Plan)**：
   - 制定專門供 Windows 端（`~/Desktop/SoapVoice` 及 `deploy/windows_agent/`）執行的實測步驟與驗收清單。
   - 本階段**不修改** Windows 端程式碼，只交付規格與測試表。
   - 涵蓋：`PyAudio` 16kHz mono、`onnxruntime` + `silero_vad.onnx`、3 秒 pre-roll ring buffer、靜音 30 秒自動結案或黃燈提醒、快捷列紅黃綠燈連動。

**範圍邊界（明確聲明）**：VAD 與 3 秒 pre-roll 環形緩衝區都在**客戶端**。伺服器測試只能驗證「伺服器收到的前綴音訊被正確串接與轉錄」，**不能驗證 VAD 判斷本身或 ring buffer 的正確性**。這兩項由 Windows 實測（第三節的人工簽核）負責。

---

## 二、工作拆解 (Task Breakdown)

### Task 1: Server 端 WAV 驗證強化、循環層級 trigger 欄位與 heartbeat 擴充

- **檔案**：
  - `src/elc_audit_engine/cycles/chunks.py`
  - `src/elc_audit_engine/api/routes/cycle_chunks.py`
  - `src/elc_audit_engine/api/routes/clients.py`
  - `src/elc_audit_engine/cycles/presence.py`（新增列入，H2）
  - `src/elc_audit_engine/case_store/db.py`（新增 migration，H1）
  - `src/elc_audit_engine/cycles/store.py` 與 `src/elc_audit_engine/api/routes/cycles.py`（循環建立端點支援 trigger 欄位，H1）
- **實作內容**：
  1. **WAV 一致性檢查（M4）**：在 `validate_wav_chunk` 中，讀取 RIFF header 宣告的 data 區塊大小，並與 `len(data)` 扣除標頭後的實際位元組比對；不一致則拋 `ChunkFormatError`。既有的 `wave` 模組格式檢查保留。
  2. **PCM 串接回歸（M4）**：確認 finalize 以 `wave.readframes` 剥離標頭的行為維持不變，並新增測試：多段串接後的總 frame 數等於各段 frame 數之和。
  3. **seq 上界拒絕（M6）**：`store_chunk` 若收到 `seq >= total_chunks`（需由循環宣告的總數判斷；若循環尚未宣告總數，則於 finalize 時檢查 `cycle_chunks` 中是否存在超出範圍的 seq，存在則拒絕 finalize）。兩種路徑均需測試。
  4. **大小上限（M7）**：設定單循環分段總數上限（預設 `MAX_CHUNKS_PER_CYCLE = 120`，約 2 小時）與 finalize 的總 PCM 大小上限（預設 `MAX_CYCLE_PCM_BYTES = 250 * 1024 * 1024` 即 250 MiB，可由環境變數調整）。超過上限時拒絕，不進入串接。
  5. **循環層級 trigger 欄位（H1）**：在 `recording_cycles` 新增 `trigger_mode TEXT NOT NULL DEFAULT 'manual'`（允許值 `manual` | `vad_auto`）與 `preroll_sec REAL NOT NULL DEFAULT 0`。`case_store/db.py:init_schema` 納管 migration（具冪等性）；`cycles/store.py:create_cycle` 與 `POST /api/cycles` 接受這兩個欄位並驗證允許值；`audit_log` 同步紀錄。
  6. **heartbeat `vad_listening`（H2）**：`/api/clients/heartbeat` 接受選填欄位 `vad_listening`，驗證為嚴格的 `bool`（`isinstance(x, bool)`，排除 `int`）；寫入 `cycles/presence.py` 的 presence 紀錄。欄位缺省時視為 `false`，不影響舊版客戶端。

### Task 2: Server 端端到端 Windows Client 模擬整合測試

- **檔案**：
  - `tests/test_windows_client_chunk_e2e.py`（新增）
- **測試素材**：`SoapVoice/static/*.wav`（示範檔）或合成音；**禁止使用真實病患錄音**（H3）。
- **測試情境**：
  - **T2.1（正常分段串接）**：切為 5 段，每段帶獨立 RIFF 標頭，依序上傳後 finalize，驗證產出 `full.wav`，且 frame 數與 sha256 符合（M5）。
  - **T2.1-ASR（選用）**：以 `skipif` 保護，finalize 後觸發 sherpa-onnx 轉錄；模型不存在時跳過，非 CI 必跑（L9）。
  - **T2.2（弱網重送與亂序）**：第 2 段逾時重送（驗證 `duplicate=true`）；第 4 段先到、第 3 段後到；finalize 結果依 `seq` 正確串接。
  - **T2.3（前綴音訊串接）**：模擬 Client 在觸發點前附上 3 秒 pre-roll 的音訊段，驗證伺服器正確串接並轉錄首句（範圍僅限伺服器，見第一節「範圍邊界」）。
  - **T2.4（邊界拒絕，M6）**：上傳 `seq >= total_chunks` 的分段，驗證被拒絕或 finalize 失敗，且不會靜默丟棄。
  - **T2.5（截斷分段，M4）**：上傳宣告大小與實際位元組不符的分段，驗證被 `ChunkFormatError` 拒絕。
  - **T2.6（上限，M7）**：超過總分段數或總大小上限時，驗證拒絕且不寫入 `full.wav`。
  - **T2.7（回歸）**：既有去重、等冪、缺段、亂序行為，以既有測試覆蓋，本檔不重複實作。

### Task 3: Windows Client 端的實作與測試操作手冊

- **檔案**：
  - `docs/plans/windows_client_vad_test_plan.md`（`docs/plans/` 已存在）
- **內容**：
  - 交付 Windows 端 `SoapVoice` 修改指引（`audio_recorder.py` 整合 Silero VAD 與 3 秒 ring buffer）。**本階段不修改 Windows 端程式碼**。
  - 客戶端重試規範：指數退避、保留 `seq` 不變、相同內容重送必須使用相同 sha256（以伺服器等冪為前提）。
  - 實體驗測表格：
    - 硬體麥克風測試
    - 診間背景敲擊鍵盤的防誤觸測試
    - 醫師開口即時觸發紅燈測試
    - 看診結束靜音 30 秒自動送審測試
    - 弱網斷線後重送測試

---

## 三、驗收條件 (Acceptance Criteria)

**自動化（可由倉庫驗證）**

1. `tests/test_windows_client_chunk_e2e.py` 與既有 `tests/test_cycle_chunks.py` 全數通過（ASR 測試若模型不存在則 skip，不計為失敗）。
2. 串接量測：T2.1 中，串接後總 frame 數等於各段 frame 數之和；每段位元組數為偶數；`full.wav` 的 sha256 與客戶端宣告值一致（M5）。
3. 截斷分段、`seq >= total_chunks`、超上限的情境皆被拒絕，且不產生 `full.wav`（M4、M6、M7）。
4. `recording_cycles` 的 `trigger_mode` 與 `preroll_sec` 有預設值，migration 可重複執行，且既有資料不受影響（H1）。
5. heartbeat 的 `vad_listening` 僅接受 `bool`；傳入 `1` 或 `"true"` 時回 422（H2）。
6. `uv run ruff check .` 零警告零錯誤。
7. 測試素材來源可追溯，且不含真實病患錄音（H3）。

**人工簽核（無法由倉庫驗證）**

8. 由 Herdr `claude`（Planchecker）複審本計畫，確認第一輪 HIGH 項目已解決。
9. 由 Herdr `hermes`（Tester）獨立執行整合測試並回報結果。
10. Windows 端實體驗測表格全數完成，並由人工簽核（VAD 判斷、ring buffer、快捷列連動皆屬此項）。

---

## 待補項目（CONDITIONAL PASS 的條件）

- [x] T2.4 M6 測試補強：已拆為 T2.4a（上傳 422）、T2.4b（finalize 422 且無 full.wav）、T2.4c（413 上限）。
- [ ] `docs/plans/windows_client_vad_test_plan.md` 心跳範例欄位 `client_version` 改為 `app_version`（與 `api/routes/clients.py` 一致）。
- [ ] 無關內容還原：`compare.md` 的 LLM 評測段落已由獨立 commit 還原，內容保留於 commit `76134b6`，如需另行保存請另開文件。
- [ ] 建立循環的端點 migration 路徑補列於 Task 1 檔案清單（目前已由 `cycles.py` 與 `case_store/db.py` 實作，計畫清單需同步）。
- [ ] Planchecker（Herdr `claude`）複審通過後，才可升級為 APPROVED。
- [ ] 第 3 節第 8–10 項人工簽核（Herdr 複審、Tester 獨立測試、Windows 實體驗測）。
