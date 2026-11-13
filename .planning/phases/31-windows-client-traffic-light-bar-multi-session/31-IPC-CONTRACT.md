# Phase 31 IPC 與 Server API 契約

**契約版本：`elc-p31-ipc/1`**
本文件為快捷列、SoapVoice 客戶端與 elc server 之間介面的唯一權威來源（D-31-03）。SoapVoice 倉以複本使用（不跨倉 import）；修改任何欄位、狀態或錯誤代碼，需兩倉同步修改並更新版本字串。
測試 fixture：`tests/fixtures/phase31_contract_v1.json`（範例值一律為假資料）。

---

## §1 本機指令通道（快捷列 → SoapVoice 客戶端程序）

- **位址**：`http://127.0.0.1:{control_port}`，`control_port` 預設 `18765`（SoapVoice `LANConfig.control_port`，可改）。只綁定 `127.0.0.1`；設定為非 loopback 位址時 SoapVoice 拒絕啟動控制服務。
- **認證**：標頭 `X-Local-Token`。token 檔位置：
  - Windows：`%LOCALAPPDATA%\ElcSoapVoice\control_token`
  - 其他平台：`~/.local/share/ElcSoapVoice/control_token`
  - SoapVoice 首次啟動時以 `secrets.token_urlsafe(32)` 產生；快捷列只讀不寫。比對使用 `hmac.compare_digest`。缺少或錯誤 → `401`。
- **Host 標頭**必須為 `127.0.0.1:{port}` 或 `localhost:{port}`，否則 `400`（防 DNS rebinding）。
- **錯誤格式**：`{"error": 代碼, "message": 中文說明}`。

### GET `/control/v1/status`
- 回應 `200`，欄位：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `contract` | string | 固定 `elc-p31-ipc/1` |
| `state` | string | `IDLE`｜`RECORDING`｜`UPLOADING`｜`GENERATING`｜`SUBMITTED`｜`ERROR` |
| `cycle_id` | string \| null | 32 位小寫 hex |
| `elapsed_seconds` | float | 錄音已進行秒數 |
| `patient_bound` | bool | SoapVoice 已擷取病人資訊。**不得回傳病人姓名或任何病歷內容**（D-31-02） |
| `chunks_total` | int | |
| `chunks_acked` | int | server 已確認收到的分段數 |
| `chunks_pending` | int | 尚未確認的分段數 |
| `draft_submitted` | bool | |
| `last_error` | string \| null | |

### POST `/control/v1/start`
- 請求：`{"command_id": 32 位小寫 hex, "cycle_id": 32 位小寫 hex}`
- `200`：回傳 status 物件（`state=RECORDING`）。
- 同一 `command_id` 重送 → `200`，回傳相同結果（冪等）。
- `state` 為 `RECORDING`、`UPLOADING`、`GENERATING` 時，以不同 `cycle_id` 呼叫 → `409 {"error":"busy"}`，**且絕不重設進行中錄音**（研究 Pitfall 5）。
- `state` 為 `IDLE` 或 `SUBMITTED` 才可開始新循環。
- 麥克風無法開啟 → `503 {"error":"recorder_unavailable"}`。
- 欄位格式錯誤 → `422`。

### POST `/control/v1/stop`
- 請求：`{"command_id", "cycle_id"}`
- `200`：回傳 status（`state=UPLOADING` 或 `GENERATING`）。
- `cycle_id` 與進行中不符 → `409 {"error":"cycle_mismatch"}`。
- 未錄音且非重送 → `409 {"error":"not_recording"}`。
- 同 `command_id` 重送 → `200`，相同結果。

### POST `/control/v1/archived`
- 請求：`{"cycle_id"}`
- SoapVoice 先以自身 API key 呼叫 server `GET /api/cycles/{cycle_id}`，確認 `state=ARCHIVED` 後，才在本機 manifest 標記為 archived（D-31-33）。
- `200`：`{"cycle_id", "cleanup_eligible": true}`。
- server 未確認 → `409 {"error":"not_archived_on_server"}`；無法連線 → `503`。本機**不標記**。

---

## §2 SoapVoice → elc server（皆需 `X-API-Key`）

認證使用 SoapVoice 的 operator 金鑰，**不適用** `/api/soap/recordings` 的私有 IP 免金鑰例外（D-30-09）。

### POST `/api/cycles/{cycle_id}/chunks`
- 請求：multipart，欄位：
  - `seq`：從 0 起算的整數
  - `sha256`：64 位小寫 hex，對**整個 WAV 檔位元組**計算
  - `audio`：`.wav` 檔，單段上限 4 MiB
- server 重新計算 sha256，不符 → `422`。
- 新段 → `201 {cycle_id, seq, sha256, duplicate: false}`。
- 同 `(cycle_id, seq)` 且 sha256 相同 → `200 {..., duplicate: true}`。
- 同 seq 但 sha256 不同 → `409`。
- 循環狀態不是 `RECORDING` 或 `AWAITING_DRAFT` → `409`。
- 客戶端只在回應的 sha256 與本機相符時，才將該段標記為 acked（D-31-30）。

### POST `/api/cycles/{cycle_id}/finalize`
- 請求：`{"total_chunks": ≥1 整數, "audio_sha256": 64 hex}`
- `audio_sha256` 定義：依 `seq` 順序，以 `wave` 模組 `readframes` 取出每段 PCM frames 後串接的位元組之 sha256（**不含 WAV 標頭**）。
- 缺段 → `409 {"error":"missing_chunks","missing":[seq...]}`。
- 串接雜湊不符 → `422`。
- 成功 → `200 {cycle_id, total_chunks, audio_sha256, upload_complete: true}`；server 產出 `DATA_DIR/cycles/{cycle_id}/full.wav`。
- 重送冪等。

### POST `/api/cycles/{cycle_id}/draft`
- 請求：

```json
{
  "session_id": "...",
  "case_id": "...",
  "patient_ref": "...",
  "visit_date": "...",
  "order_code": "（可省略）",
  "soap": {"s": "", "o": "", "a": "", "p": ""},
  "transcript": "...",
  "extras": {
    "summary_zh": "",
    "past_history": "",
    "suggestions": {"icd10": [], "orders": [], "meds": []}
  }
}
```

- 前提：`upload_complete` 為真，且循環狀態為 `AWAITING_DRAFT` 或 `DRAFT_UNUSABLE`，否則 `409`。
- 同 `session_id` 重送 → `200`，回傳同一 `draft_id`。
- 成功 → `201 {cycle, draft_id, draft_state}`。

---

## §3 快捷列 → elc server（皆需 `X-API-Key`，使用 `AgentSettings.operator_key`；Agent 金鑰一律 `403`）

### POST `/api/cycles`
- 請求：`{"command_id", "machine_id", "room_id"（可省略）}`
- `201 {cycle}`；同 `command_id` → `200` 同一 cycle。
- 該 `machine_id` 已有未終結循環 → `409 {"error":"active_cycle_exists","active_cycle_id"}`（D-31-16）。

### GET `/api/cycles/{cycle_id}`
- `200 {cycle}`。

### GET `/api/cycles?machine_id=…`
- `200 {cycle 或 null}`，回傳該機未終結循環，供重啟還原。

### POST `/api/cycles/{cycle_id}/stop`
- 請求：`{"command_id"}`。`RECORDING → AWAITING_DRAFT`。

### GET `/api/cycles/{cycle_id}/draft[?include_transcript=1]`
- `200`：

```json
{
  "cycle_id": "...",
  "draft": {"draft_id", "version", "content_hash", "state", "soap", "quality_issues"},
  "extras": {},
  "advisory": {"icd10_suggestions": [], "order_suggestions": [], "med_suggestions": [], "read_only": true},
  "transcript": "（僅 include_transcript=1 時）"
}
```

- 尚無草稿 → `404`。

### POST `/api/cycles/{cycle_id}/confirm`
- 請求：`{"content_hash", "soap"（可省略，醫師修改後的 s/o/a/p）, "reviewer_id"（可省略）}`
- `200 {cycle, draft_id, content_hash}`。

### POST `/api/cycles/{cycle_id}/archive`
- 請求：`{"command_id"}`
- `200 {"status": "archived" | "already_archived"}`
- `202 {"status": "his_pending" | "his_retry_queued"}`
- `409 {"status": "not_confirmed" | "his_failed", "reason"}`
- 黃燈完成條件：草稿已存 server，且 HIS 寫入成功（`pushed`）（D-31-06）。

### POST `/api/cycles/{cycle_id}/abandon`
- 請求：`{"reason_code"}`
- `200 {cycle}`。只允許 `RECORDING`、`AWAITING_DRAFT`、`AWAITING_CONFIRM`、`DRAFT_UNUSABLE`。**不刪除任何檔案**（D-31-29）。

### POST `/api/clients/heartbeat`
- 請求：`{"machine_id", "machine_name", "room_id", "bar_state", "soapvoice_state", "chunks_pending", "app_version"}`
- `200 {"status": "ok", "server_time", "notify": null 或 {"cycle_id", "state", "draft_id", "draft_version"}}`
- **回應不得含** `soap`、`transcript`、`extras`、`patient` 等鍵（D-31-12）。

### GET `/api/clients`
- `200 {"rooms": [{"room_id", "clients": [{"machine_id", "machine_name", "room_id", "display_state", "cycle_id", "cycle_state", "last_seen_at", "online", "client_subnet", "in_clinic_subnet"}]}]}`
- **不含病歷內容**（D-31-17）。

### GET `/clients`
- 多連線監控靜態頁（僅 HTML）。資料以 `X-API-Key` 經 `/api/clients` 取得。

### cycle 物件（無 PHI）
`cycle_id`, `machine_id`, `room_id`, `state`, `draft_id`, `draft_state`, `chunks_received`, `total_chunks`, `upload_complete`, `his_state`, `last_error`, `created_at`, `updated_at`。

---

## §4 server 循環狀態（D-31-05）

狀態：`RECORDING`、`AWAITING_DRAFT`、`AWAITING_CONFIRM`、`DRAFT_UNUSABLE`、`CONFIRMED`、`ARCHIVING`、`ARCHIVE_FAILED`、`ARCHIVED`（終態）、`ABANDONED`（終態）。

允許轉換：

- `RECORDING` → `AWAITING_DRAFT`、`ABANDONED`
- `AWAITING_DRAFT` → `AWAITING_CONFIRM`、`DRAFT_UNUSABLE`、`ABANDONED`
- `AWAITING_CONFIRM` → `CONFIRMED`、`DRAFT_UNUSABLE`、`ABANDONED`
- `DRAFT_UNUSABLE` → `AWAITING_CONFIRM`、`CONFIRMED`、`ABANDONED`
- `CONFIRMED` → `ARCHIVING`、`ARCHIVED`、`ARCHIVE_FAILED`
- `ARCHIVING` → `ARCHIVING`、`ARCHIVED`、`ARCHIVE_FAILED`
- `ARCHIVE_FAILED` → `ARCHIVING`、`ARCHIVED`

---

## §5 監控顯示狀態（D-31-15）

判定順序：

1. **離線**：`last_seen` 超過 `ELC_CLIENT_OFFLINE_SECONDS`（預設 15 秒，以 server 時鐘計）。
2. `RECORDING` → **錄音中**。
3. `AWAITING_DRAFT`／`AWAITING_CONFIRM`／`DRAFT_UNUSABLE`／`CONFIRMED`／`ARCHIVING`／`ARCHIVE_FAILED` → **待確認**。
4. 無未終結循環且最近一個循環為 `ARCHIVED` → **已封存**。
5. 其他 → **待命**。

---

## §6 識別字格式

- `cycle_id`、`command_id`：`^[0-9a-f]{32}$`。
- `machine_id`：UUID4 字串（`elc_audit_engine.his_calibration.new_machine_id` 回傳 `str(uuid.uuid4())`）。正規式：
  `^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`
- `room_id`：1–32 字元的 Unicode 字母、數字、底線或連字號；**拒絕而非清洗**。

---

## §7 分段參數

- 每段長度預設 **20 秒**（D-31-19），允許設定 15–30 秒，超出範圍夾回邊界。
- 格式：16 kHz、mono、16-bit PCM WAV。
