# Plan 31-11 Summary: 多連線監控、工作站心跳與通知搭便車 (Task 1 & Task 2)

## 成果摘要
- **模組交付**：
  1. `src/elc_audit_engine/cycles/presence.py`：
     - `upsert_presence`：以 SQLite `ON CONFLICT(machine_id) DO UPDATE` 儲存/更新工作站狀態，記錄來源 IP 網段與伺服端 UTC 時間戳；回傳 `is_first_seen`。
     - `subnet_of`：解析 IPv4 (/24) 或 IPv6 (/64) 網段。
     - `in_clinic_subnet`：以 `ELC_CLINIC_SUBNETS` 或 RFC 1918 / loopback 判定診所網段歸屬（僅供顯示，不作授權）。
     - `notification_for_machine`：查詢工作站當前未終結循環，回傳 `{cycle_id, state, draft_id, draft_version}`，嚴格零 PHI。
     - `list_presence_grouped`：依 `room_id` 分組（未指定診間置後），以伺服端時鐘計算 15 秒在線判定並產生顯示狀態（錄音中、待確認、已封存、待命、離線）。
     - 驗證函式：`validate_machine_id` (UUID4)、`validate_room_id` (1-32 Unicode 字母數字破折號)、`validate_presence_field` (<= 64 字元且無控制字元)。
  2. `src/elc_audit_engine/api/routes/clients.py`：
     - `POST /api/clients/heartbeat`（端點 `client_heartbeat`）：心跳回報與通知搭便車，首次出現的工作站記錄審計日誌。
     - `GET /api/clients`（端點 `list_clients`）：回傳診間分組之工作站列表，零 PHI。
     - `GET /clients`（端點 `monitor_page`）：回傳多連線監控靜態頁面 `static/clients.html`。
  3. `src/elc_audit_engine/api/security.py`：
     - `clients.monitor_page` 列入 `AUTH_EXEMPT_ENDPOINTS` 與 `AUDIT_EXEMPT_ENDPOINTS`。
     - `clients.client_heartbeat` 列入 `AUDIT_EXEMPT_ENDPOINTS`（避免心跳日誌淹沒），但**不在** `AUTH_EXEMPT_ENDPOINTS`（強制 API 金鑰認證；Agent 金鑰 403 阻絕）。
     - `clients.list_clients` 兩者皆不在（需 API 金鑰並記錄存取審計）。
  4. `static/clients.html`：
     - 單檔純前端（符合既有 CSP，無外部依賴），完全禁止 `innerHTML` / `outerHTML` / `insertAdjacentHTML` / `eval`，一律使用 `textContent` 與 DOM API 寫入以防止 XSS。
     - 支援 `localStorage` 讀取與設定 `elc_api_key`；每 5 秒透過 `setInterval` 輪詢 `/api/clients`。
     - 依診間分組卡片顯示工作站狀態（色彩區分狀態：待命灰、錄音中紅、待確認黃、已封存綠、離線深灰）。
     - 展開卡片可檢視循環狀態，提供「顯示待確認草稿」按鈕唯讀調閱 S/O/A/P 與建議項；對非進行中或草稿不可用之循環提供「放棄此循環」二階段確認按鈕（保留伺服端音檔與逐字稿）。
  5. 測試套件：
     - `tests/test_client_notify_auth.py`：驗證通知搭便車、嚴格無 PHI、無 key 401、Agent key 403、機器間通知隔離、無活躍循環回傳 null。
     - `tests/test_clients_monitor.py`：驗證診間分組、15 秒離線判定、顯示狀態映射、網段歸屬、欄位驗證、靜態頁免認證、security 豁免設定、DOM 模式安全。
- **測試結果**：
  - `tests/test_clients_monitor.py` + `tests/test_client_notify_auth.py`：15 passed。
  - `tests/test_cycles_api.py` 及跨端點安全驗證全部通過。
  - 全套件 1456 passed，零迴歸。

## 偏離與路徑對應
- 無偏離。本計畫全數於 `Elcinsurrence` 倉庫實作，無 git commit。
