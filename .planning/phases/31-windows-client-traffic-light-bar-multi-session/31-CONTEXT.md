# Phase 31: Windows 客戶端紅綠黃燈快捷列與多連線監控 - Context

**Gathered:** 2026-11-12
**Status:** Ready for planning
**Source:** 使用者於 `/gsd-plan-phase` 的需求描述、三題確認（錄音位置、phase 位置）、再三題確認（診間、存檔範圍、暫存清理）

<domain>
## Phase Boundary

本 phase 依賴 Phase 30（Windows 執行檔、SOAP 審核 API、HIS 回寫），交付三件事：

1. **Windows 客戶端快捷列（紅綠黃燈）**
   - 安裝後自動啟動，常駐右下角，浮在所有程式最上層，收合時約一個小型 bar。
   - 收合只有三個按鈕：
     - 紅燈：開始一個循環（SoapVoice 開始錄音，擷取病人資訊）。
     - 綠燈：結束錄音（SoapVoice 停止錄音，分段上傳至本機 server，server 產生草稿）。
     - 黃燈：醫師確認後按下，封存本循環（server 與 HIS 都寫入成功才算完成）。
   - 功能刻意保持簡單，不做展開的完整介面。

2. **server 端 SOAP 確認視窗**
   - 草稿完成時主動推送至對應客戶端，自動跳出確認視窗，內容與使用者提供的截圖一致（S／O／A／P、過去病史、中文對話摘要、建議項）。
   - 醫師按「存檔」後，草稿必須同時存在 server 與 HIS。

3. **多連線監控**
   - server 端介面同時顯示同一台 server 上所有客戶端，依診間分組，顯示每台的狀態。
   - 同一診所有多個診間，不同醫師可在不同診間同時看不同病人。院內網路內不需額外驗證診間。

</domain>

<decisions>
## Implementation Decisions

### 錄音位置（使用者已確認）
- **D-31-01** 錄音功能維持在 `~/Desktop/SoapVoice`，遵循 Phase 30 的 D-30-01。快捷列只負責發送「開始／結束」指令並顯示狀態，**不自行錄音**。
- **D-31-02** 「截取病人資訊」指 SoapVoice 在循環開始時擷取的病人識別資訊（由 SoapVoice 負責）；快捷列只顯示循環是否已綁定病人。
- **D-31-03** 快捷列與 SoapVoice 之間的指令介面（本機 IPC 方式、訊息格式、狀態回報）必須在計畫中明列，並於兩倉同步定義。

### Phase 位置（使用者已確認）
- **D-31-04** 本 phase 為新開的 Phase 31，不併入 Phase 30。Phase 30 的 30-11 維持原計畫。

### 循環與存檔（使用者已確認 2026-11-12）
- **D-31-05** 一個「循環」＝ 紅（開始）→ 綠（結束錄音）→ server 產生草稿 → 醫師確認 → 黃（封存）。
- **D-31-06** 黃燈「封存」的完成條件：(a) 醫師確認版草稿已存入 server，且 (b) 已成功寫入 HIS（HIS_PUSH 狀態為 `pushed`）。兩者皆成功才回到待命。
- **D-31-07** 任一步驟失敗時不得回到待命；快捷列顯示錯誤、保留循環狀態，可重試。已成功的步驟不重做（冪等）。
- **D-31-08** 醫師未確認前黃燈停用；綠燈後草稿尚未產生前黃燈停用。
- **D-31-25** server 存檔內容為醫師確認版的**完整草稿**（與確認視窗一致，含中文對話摘要、過去病史、建議項），**不只是英文 SOAP**。
- **D-31-26** HIS 只寫入 S／O／A／P（沿用 D-30-05）；診斷碼、醫令、藥令不寫入 HIS，只存於 server 的草稿紀錄。

### 預覽、HIS 寫入格式與客戶端保留期限（使用者已確認 2026-11-12）
- **D-31-40** 醫師預覽畫面須同時顯示 **SOAP（英文）與譯文**（譯文為中文對照，供醫師確認）。
- **D-31-41** 寫入 HIS 時，只寫入 SOAP 的 S／O／A／P 欄位；或將純 SOAP 產生為文字檔，供醫師複製貼上至 HIS。**原始譯文不寫入 HIS**（使用者說明：太長）。
- **D-31-42** 「原始譯文」指逐字稿的完整譯文，不列入 HIS 寫入與複製內容。server 草稿紀錄是否保留原始譯文，依 D-31-27 與 Q9 處理。
- **D-31-43** **客戶端（工作站）**的音檔與逐字稿保留上限為 **3 個月**，超過即刪除。仍須符合 D-31-30 至 D-31-33（已被 server 確認收到才可刪；未確認或循環未封存者不刪）。
- **D-31-44** 3 個月上限**只適用於客戶端**，不適用於 server。server 端的保存期限仍待 Q9 確認，server 不因此自動刪除。

### 音檔與逐字稿保存（使用者已確認 2026-11-12）
- **D-31-27** 音檔與音譯（逐字稿）保存於 **server**。它們不寫入 HIS，也不在黃燈時強制顯示。
- **D-31-28** 音檔與逐字稿只在法院或審查需要時，由 server 調出；本 phase 不實作調閱介面，只確保資料存在且可依 `cycle_id` 找到。
- **D-31-29** 音檔與逐字稿的保存期限未定（Q9 仍待確認）。本 phase 不得自行決定刪除時點，server 端一律不自動刪除，直到使用者確認保存規則。

### 客戶端暫存清理（使用者已確認 2026-11-12）
- **D-31-30** 客戶端（工作站）暫存檔不需長期保存。只有在 **server 已確認收到**（回應包含該檔 `sha256` 相符）後，才可刪除本機暫存。
- **D-31-31** 本機暫存超過設定的大小上限時，才刪除最舊的「已確認 server 收到」的檔案。上限為設定值，預設值由 planner 決定並寫入設定檔。
- **D-31-32** 未被 server 確認的檔案絕不刪除，無論大小。
- **D-31-33** 循環未封存（黃燈未完成）時，該循環的暫存檔一律保留。

### 錄音切段與串流上傳（使用者已確認 2026-11-12）
- **D-31-19** 錄音期間分段上傳，不等錄音結束才整段送出。分段長度預設 20 秒，由 planner 在 15–30 秒範圍內確定。
- **D-31-20** 每段帶 `cycle_id`、`seq`（從 0 起算的連續序號）、`sha256`。server 以 `(cycle_id, seq)` 去重，重送必須冪等。
- **D-31-21** 本機必須先落地：每段在上傳前先寫入本機磁碟，不得只存於記憶體。
- **D-31-22** 網路中斷或 server 故障時，未送出的分段留在本機佇列，恢復後補傳；錄音本身不中斷。
- **D-31-23** 綠燈後草稿以完整逐字稿生成，不以分段草稿拼接。綠燈時若仍有未傳分段，狀態列顯示「上傳中」，草稿等待補傳完成。
- **D-31-24** 分段切段與上傳屬於 SoapVoice 的職責（沿用 D-31-01）；快捷列只顯示上傳進度。

### 診間與連線（使用者已確認 2026-11-12）
- **D-31-18** 診所（clinic）由 server 依來源 IP 推斷。每間診所有自己的硬體 local server，診所層級即 server 本身。
- **D-31-18a** IP 只用於決定歸屬，不作身分驗證；身分仍以 API key 認證（D-30-09）。客戶端 IP 會變，歸屬以網段（/24）比對，不以單一 IP 比對。
- **D-31-18b** **診間（room）**：同一診所可有多個診間，不同醫師在不同診間同時看不同病人。每台工作站的設定檔填寫 `room_id`，首次啟動時設定。**院內網路內不需驗證 room_id**（使用者已確認），server 只做顯示分組，不做權限判斷。
- **D-31-18c** 診間不得以 IP 推斷。
- **D-31-16** 同一診間多個客戶端同時連線為正常情形；每個循環綁定單一客戶端與單一 session，不可混用草稿。

### 櫃台客戶端（使用者提出，尚未設計）
- **D-31-34** 櫃台也可安裝本快捷列。櫃台的主要情境是同一病人讀取**健保雲端病歷**，需求是在讀取雲端病歷時，同步記錄讀取的內容。
- **D-31-35** 擷取雲端病歷的方法尚未確定。本 phase 不得以猜測方式實作；須先由 researcher 做可行性調查（見下方 Claude's Discretion），結果確認後再排入實作 wave。
- **D-31-36** 櫃台功能不得阻塞診間主流程（D-31-19 至 D-31-24）。

### 快捷列行為
- **D-31-09** 置頂、無工作列按鈕、可拖曳，位置記憶於本機設定。
- **D-31-10** 收合為紅綠黃三鈕；展開僅顯示目前狀態文字與 server 連線狀態。
- **D-31-11** 按鈕狀態機嚴格限制：紅只在待命時可按，綠只在錄音中可按，黃只在醫師已確認且 server 已存檔後可按（見 D-31-06）。非法操作一律忽略並顯示提示。

### Server 端確認視窗
- **D-31-12** 草稿推送採用 server 主動通知客戶端（沿用 D-30-09 的認證）。客戶端不得在未認證時接收任何病歷內容。
- **D-31-13** 確認視窗顯示 S／O／A／P 四欄，以及過去病史、中文對話摘要、建議項（診斷碼、醫令、藥令以建議形式呈現，沿用 D-30-12）。
- **D-31-14** 確認動作寫入 HIS 沿用 Phase 29 的 HIS_PUSH 與 Phase 30 的校正 profile；未完成校正的機器不得真實回寫（沿用 D-30-11）。

### 多連線監控
- **D-31-15** server 端介面依診間分組列出所有客戶端：機器名稱、`room_id`、狀態（待命／錄音中／待確認／已封存／離線）、最後心跳時間。
- **D-31-17** 多連線列表僅顯示狀態，不顯示病歷內容；點入某連線後才顯示其待確認草稿，且須通過既有權限檢查。

### 現況查核（2026-11-12，依 SoapVoice 與本倉程式碼）
- `client/audio_recorder.py`：錄音期間以 `audio_frames` 串列存於記憶體，`stop()` 才寫成單一 WAV。不支援切段，且與 D-31-21 衝突，必須修改。
- `client/main.py` `_on_record_toggle`：停止後整段上傳 `upload_consultation`。`client/lan_client.py` 已有失敗佇列與補傳（`_queue_for_retry`、`retry_pending_uploads`），可沿用。
- `src/api/websocket.py` 與 `src/asr/stream_transcriber.py` 已有伺服器端串流辨識，但客戶端未使用，只可參考切塊作法。
- `/api/soap/recordings` 目前只接受整段 WAV，分段上傳需新增 chunk 端點或擴充既有端點。
- `src/elc_audit_engine/api/routes/bridge.py` `list_pending_jobs` 只依 `sTypeCode` 過濾，**未依 agent 或 `machine_id` 過濾**。多台已校正的 agent 可能領走他人的 HIS_PUSH 任務。本 phase 必須修正（見 D-31-37）。

### 必須修正的既有風險（納入本 phase）
- **D-31-37** HIS_PUSH 任務須綁定 `machine_id`（或 `room_id`），`list_pending_jobs` 必須過濾，避免跨機領取。
- **D-31-38** `_approve_draft_record` 的 (a) 更新為 approved、(b) enqueue_job、(c) 更新為 queued 三步須在同一交易中完成，或能從崩潰中恢復。否則黃燈重試會卡住。（研究報告推論，planner 需先以程式碼確認。）
- **D-31-39** `/api/soap/drafts/pending-review` 回傳全部草稿，不得作為循環確認的來源；循環確認必須以 `cycle_id → draft_id` 直接開啟（D-31-16）。

### Claude's Discretion
- 快捷列 GUI 技術：研究建議 Tkinter（沿用 repo 與 SoapVoice 既有使用），不新增套件。planner 決定。
- 快捷列與 SoapVoice 的 IPC：研究建議本機 HTTP，沿用 SoapVoice 既有 `/api/v1/consultation/start|end|stats`，但需綁定 `127.0.0.1` 並加本機 token，`start` 錄音中改回 409。planner 決定。
- 多連線推送方式：研究建議輪詢搭便車於 heartbeat，不採 SSE。planner 決定。
- 櫃台雲端病歷擷取（D-31-35）：researcher 需先做可行性調查，列出可選方法與風險，不得直接實作。
- 本機暫存上限的預設值（D-31-31）由 planner 決定，須寫入設定檔並可調整。

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 本 phase 研究
- `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-RESEARCH.md` — 子代理研究報告（含 Pitfall 與 Validation Architecture）。其中程式碼事實需以實際程式碼再確認。

### Phase 30（直接前置）
- `.planning/phases/30-windows-exe-soap-review-calibration/30-CONTEXT.md` — D-30-01 至 D-30-12
- `.planning/phases/30-windows-exe-soap-review-calibration/30-09-PROBE-RESULT.md` — 探針實機 PASS 與 agent-desktop 用法
- `deploy/windows_agent/mock_his/probe_readback_check.py` — 目前的視窗鎖定與寫入讀回流程

### Phase 29（SOAP 審核與 HIS 回寫）
- `.planning/phases/29-soap-review-his-writeback/29-DESIGN.md` — 草稿狀態機、審核 API、HIS_PUSH 規則
- `deploy/windows_agent/agent.py` — 既有 Windows agent（pull 模式、心跳）

### 認證與佇列
- `src/elc_audit_engine/auth.py` — `caller:key` 與 constant-time 比對
- `src/elc_audit_engine/bridge_queue.py` — CAS 任務佇列
- `src/elc_audit_engine/api/routes/bridge.py` — `list_pending_jobs`（D-31-37）
- `src/elc_audit_engine/api/routes/soap_review.py` — `_approve_draft_record`（D-31-38）

### 錄音（外部倉 `~/Desktop/SoapVoice`）
- `client/audio_recorder.py` — 目前整段錄音於記憶體，需改為分段落地
- `client/main.py` — `_on_record_toggle`、`upload_consultation`
- `client/lan_client.py` — 失敗佇列與補傳
- `src/asr/stream_transcriber.py`、`src/api/websocket.py` — 伺服器端串流辨識（僅參考）

</canonical_refs>

<specifics>
## Specific Ideas

- 確認視窗內容以使用者提供的截圖為準：S／O／A／P 四欄、過去病史、對話摘要（中文）、「原始對話內容」可展開、底部「清空 SOAP」與「複製 SOAP 到 HIS 剪貼簿」按鈕。確認視窗的「存檔」即觸發 D-31-06。
- 快捷列收合時約三顆圓鈕，貼右下角工作列上方。
- 黃燈在未確認時灰色停用，確認後亮起；綠燈在草稿產生前灰色。
- 多連線列表依診間分組，每張卡片一個客戶端，顏色對應三燈狀態。

</specifics>

<deferred>
## Deferred Ideas

- 快捷列展開後的完整設定介面。
- 跨診間的統計報表與排班。
- 語音自動接入模式的快捷列開關（沿用 D-30-04，本 phase 不新增）。
- 音檔與逐字稿的調閱介面（法院或審查用，D-31-28）。
- 音檔與逐字稿的保存期限與刪除規則（D-31-29，待確認 Q9）。

</deferred>

---

*Phase: 31-windows-client-traffic-light-bar-multi-session*
*Context gathered: 2026-11-12 via /gsd-plan-phase request; updated after clinic, storage, and temp-cleanup answers*
