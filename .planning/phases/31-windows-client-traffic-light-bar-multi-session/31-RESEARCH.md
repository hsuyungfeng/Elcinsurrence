# Phase 31: Windows 客戶端紅綠黃燈快捷列與多連線監控 - Research

**Researched:** 2026-11-12
**Domain:** Windows 桌面常駐小工具（Tkinter）、本機 IPC（SoapVoice）、Flask/gunicorn 狀態推送與多連線監控
**Confidence:** MEDIUM（程式碼事實為 HIGH；Tk 視窗行為為 MEDIUM；瀏覽器與代理層行為標為 ASSUMED）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions（逐字摘自 31-CONTEXT.md）

- **D-31-01** 錄音功能維持在 `~/Desktop/SoapVoice`，遵循 Phase 30 的 D-30-01。快捷列只負責發送「開始／結束」指令並顯示狀態，**不自行錄音**。
- **D-31-02** 「截取病人資訊」指 SoapVoice 在錄音循環開始時擷取的病人識別資訊（由 SoapVoice 負責），快捷列只顯示循環是否已綁定病人。
- **D-31-03** 快捷列與 SoapVoice 之間的指令介面（本機 IPC 方式、訊息格式、狀態回報）必須在計畫中明列，並於兩倉同步定義。
- **D-31-04** 本 phase 為新開的 Phase 31，不併入 Phase 30。Phase 30 的 30-11 維持原計畫。
- **D-31-05** 一個「循環」＝ 紅（開始）→ 綠（結束錄音）→ server 產生草稿 → 醫師確認 → 黃（封存）。
- **D-31-06** 黃燈按下時，本循環全部資料（語音檔、草稿、醫師確認版、審計紀錄）須一併存檔；存檔成功後才回到待命狀態。
- **D-31-07** 存檔失敗時不得回到待命，快捷列須顯示錯誤並保留該循環狀態，可重試。
- **D-31-08** 醫師未確認前不可按黃燈；綠燈後若草稿尚未產生，黃燈保持停用。
- **D-31-09** 置頂、無工作列按鈕、可拖曳，位置記憶於本機設定。
- **D-31-10** 收合為紅綠黃三鈕；展開僅顯示目前狀態文字與 server 連線狀態，不做其他功能。
- **D-31-11** 按鈕狀態機嚴格限制：紅只在待命時可按，綠只在錄音中可按，黃只在醫師已確認後可按。非法操作一律忽略並顯示提示。
- **D-31-12** 草稿推送採用 server 主動通知客戶端（沿用 Phase 30 的 server 位址與 API key 認證，D-30-09）。客戶端不得在未認證時接收任何病歷內容。
- **D-31-13** 確認視窗顯示 S／O／A／P 四欄；診斷碼、醫令、藥令以建議形式呈現（沿用 D-30-05、D-30-12）。
- **D-31-14** 確認動作寫入 HIS 的流程沿用 Phase 29 的 HIS_PUSH 與 Phase 30 的校正 profile；未完成校正的機器不得真實回寫（沿用 D-30-11）。
- **D-31-15** server 端介面需列出所有目前連線的客戶端：機器名稱、所屬診間（若可得）、狀態（待命／錄音中／待確認／已封存／離線）、最後心跳時間。
- **D-31-16** 同一診間多個客戶端同時連線為正常情形，每個循環須綁定單一客戶端與單一 session，不可混用草稿。
- **D-31-17** 多連線列表僅顯示狀態，不顯示病歷內容；點入某一連線後才顯示其待確認草稿，且須通過既有權限檢查。

### Claude's Discretion（研究後建議，planner 決定）

- 快捷列 GUI 技術（Tkinter、PySide、或 WebView）由 researcher 比較後建議，planner 決定。
- 快捷列與 SoapVoice 的本機 IPC 方式（本機 HTTP、命名管道、檔案佇列）由 researcher 評估既有 `bridge_queue` 與 SoapVoice 現況後建議。
- 多連線狀態的推送方式（輪詢或 SSE）由 planner 依既有 Flask 架構決定。
- 「診間」的識別來源（設定檔、註冊時填寫、或由 server 依 IP 推斷）尚未確認，researcher 應列為待確認項並提出建議。

### Deferred Ideas（本 phase 不做）

- 快捷列展開後的完整設定介面（僅保留狀態顯示，其餘延後）。
- 跨診間的統計報表與排班。
- 語音自動接入模式的快捷列開關（沿用 D-30-04，本 phase 不新增）。

</user_constraints>

<phase_requirements>
## Phase Requirements

本 phase 未提供獨立 REQ-ID（僅有 D-31-01 至 D-31-17 決策），故以決策編號作為 planner 的對應單位。下表第 3 欄列出研究支撐的位置。

| ID | Description（摘要） | Research Support |
|----|---------------------|------------------|
| D-31-01～03 | 快捷列不錄音；IPC 明列於兩倉 | 「Standard Stack」與「IPC 評估」：建議以 SoapVoice 既有 `/api/v1/consultation/*` 為指令通道 |
| D-31-05～08 | 循環與黃燈前置條件 | 「Architecture Patterns」之循環狀態機；「Pitfalls」之 approve 崩潰窗口 |
| D-31-09～11 | 快捷列視窗行為與狀態機 | 「Standard Stack」之 Tkinter 視窗屬性；「Validation Architecture」 |
| D-31-12～14 | 認證後推送、確認視窗、回寫門檻 | 「Server→Client 推送」之 heartbeat 回應搭便車方案；「Security Domain」 |
| D-31-15～17 | 多連線監控與權限 | 「Monitor UI」之 static/index.html 模式；「Presence 模型」 |

</phase_requirements>

## Summary

本 phase 的核心工作有三條線：(1) 一個常駐、置頂、無工作列按鈕的 Tkinter 紅綠黃燈小視窗；(2) 快捷列與既有 SoapVoice FastAPI 之間的本機指令通道；(3) server 端的循環（cycle）狀態機、client presence 與多連線監控頁。研究結論是：**大部分基礎設施已存在，不需新增外部套件**。

- Windows 端既有 Tkinter 慣例（`deploy/windows_agent/review_window.py`、`window_utils.py`、SoapVoice `src/gui/desktop_app.py` 皆用 `-topmost`），PyInstaller 規格亦未排除 tkinter。建議用 **Tkinter（標準函式庫）**，不引入 PySide6 或 WebView。
- SoapVoice 已有 `POST /api/v1/consultation/start`、`/end`、`GET /stats`，狀態欄位（`state`、`session_id`、`elapsed_seconds`）足以作為指令與狀態回報通道。但它**沒有任何認證**，且預設 `HOST=0.0.0.0`，且 `start` 在錄音中會直接 `reset()`，兩倉都必須修。
- server 推送建議採 **輪詢（搭便車於 heartbeat 回應）**，不採 SSE。理由有三：gunicorn 為 1 worker × 8 threads，每條 SSE 長連線會佔用一條 thread；瀏覽器 `EventSource` 無法帶 `X-API-Key` 標頭；現有 UI 與 Windows agent 皆為輪詢模式。
- 現有 `agent_heartbeats` 表是「每 agent 一列、30 分鐘才判離線」，**無法滿足** D-31-15（需要循環狀態與秒級離線判定）。須新增 `client_presence` 與 `recording_cycles` 兩張表（CaseStore 同一 SQLite）。
- 研究發現數個會直接影響計畫的既有缺陷，列於「Common Pitfalls」：HIS_PUSH 工作未綁定 agent（任一台 agent 都可領走他台的寫入任務）、`approve` 在 `approved` 與 `enqueue_job` 之間無交易保護、`/api/soap/recordings` 的冪等檢查為非原子操作、`/api/soap/drafts/pending-review` 列出全部待確認草稿（與 D-31-16 衝突）。

**Primary recommendation:** Tkinter 獨立 windowed 程序（`ElcTrafficBar`）＋ SoapVoice 本機 HTTP 指令（127.0.0.1＋本機 token）＋ heartbeat 搭便車推送 ＋ 新增 `recording_cycles`／`client_presence` 表與 `/api/clients`、`/api/cycles/...` 端點；診間來源建議為工作站 `config.json` 的 `room_id`（列為待確認）。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 紅綠黃燈按鈕與狀態機（按鈕可用性） | Browser/Client（Windows 桌面程序） | API/Backend（權威狀態） | 按鈕啟用由本機顯示；但「黃燈是否可按」的權威判定在 server（D-31-08 依草稿狀態） |
| 錄音、病人資訊擷取（D-31-01/02） | Client（SoapVoice 程序） | — | 錄音只屬於 SoapVoice；快捷列不得錄音 |
| 循環（cycle）綁定與狀態機 | API/Backend（CaseStore） | — | 需跨 client、跨程序、可重啟後還原，必須持久化於 server |
| 草稿產生（SOAP、品質檢核、比對） | API/Backend | Client（SoapVoice 產生 SOAP 文字） | 既有 `/api/soap/recordings` 與 `_create_draft_record` |
| 醫師確認視窗（S/O/A/P） | Client（Tkinter review window） | API/Backend（權限檢查與內容來源） | 沿用 `deploy/windows_agent/review_window.py` 模式 |
| 確認後寫入 HIS | Client（Windows agent + agent-desktop） | API/Backend（HIS_PUSH 佇列） | Phase 29 既有設計；佇列須加 agent 綁定（見 Pitfalls） |
| 封存（存檔）語音、草稿、確認版、審計 | API/Backend | Client（觸發） | 存檔為持久化責任，需 server 端 CAS 與冪等 |
| 客戶端 presence／心跳 | API/Backend（presence 表） | Client（送心跳） | 離線判定需 server 時鐘為準 |
| 多連線監控頁 | Browser（server 提供的 static 頁） | API/Backend（僅狀態欄位，無病歷內容） | D-31-15/17：列表不得含 SOAP |
| 視窗位置記憶 | Client（本機 config.json） | — | D-31-09，本機設定 |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| tkinter（標準函式庫） | 隨 Python 3.12 | 紅綠黃燈視窗 | 已用於 `deploy/windows_agent/review_window.py`、`calibration_view.py`、`window_utils.py`；`ElcAgent.spec` 未排除 tkinter；零新依賴 |
| urllib.request（標準函式庫） | 隨 Python | 客戶端 HTTP | `deploy/windows_agent/agent.py` 的 `DefaultHttpClient` 已使用；避免引入 requests/httpx |
| Flask | 既有（`pyproject.toml`） | 新增 `clients`、`cycles` blueprint | 既有 `api/routes/*.py` + `ALL_BLUEPRINTS` 模式 |
| SQLite（CaseStore） | 既有 | `recording_cycles`、`client_presence` 表 | 既有 `case_store/db.py` 建表模式（`CREATE TABLE IF NOT EXISTS`） |
| FastAPI（SoapVoice，既有） | 既有（SoapVoice `pyproject.toml` `fastapi>=0.115.0`） | 指令通道 `/api/v1/consultation/*` | 已存在，無需新端點即可用 start/end/stats |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| deploy.windows_agent.config | 既有 | `AgentSettings`、`default_settings_path()`、`save_settings()` | 位置記憶、`room_id`、`machine_id` |
| deploy.windows_agent.discovery | 既有 | `discover_server()`、`validate_manual_server_url()` | 找 server（D-30-08 流程重用，不得重寫） |
| elc_audit_engine.auth | 既有 | `caller:key`、`resolve_caller`、`resolve_agent_caller` | 認證與角色判定 |
| elc_audit_engine.audit_log | 既有 | `record_access()` | 循環審計；`detail` 有 PHI 鍵禁令（見 Security） |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Tkinter | PySide6 | 視覺較好、可做圓角與陰影；但**repo 內無任何 PySide 使用**，需新增依賴與 PyInstaller hook，且需 slopcheck 把關。展開面板目前僅為狀態文字（D-31-10），不需要此能力 |
| Tkinter | pywebview／WebView2 | 可複用 HTML；但需 WebView2 執行環境，repo 內無使用。不建議 |
| HTTP 指令通道 | 命名管道（named pipe） | 無認證、需 pywin32 或 ctypes 自行實作；repo 內無使用。不建議 |
| HTTP 指令通道 | 檔案佇列 | 需自行處理檔案鎖與輪詢；`bridge_queue` 是 server 端 DB 佇列，**不可**拿來做本機 IPC（它綁定 server 與 CAS 語意） |
| heartbeat 搭便車推送 | SSE（`text/event-stream`） | 見 Architecture Patterns「推送方式評估」 |

**Installation:** 本 phase 不需新增任何 pip 套件（`pip install` 清單為空）。

**Version verification:** 既有版本以 `pyproject.toml`（gunicorn `>=26.2.0`）為準，本研究未重新查詢 registry，因未新增套件。

## Package Legitimacy Audit

本 phase 建議**不新增外部套件**（Tkinter、urllib、Flask、SQLite 皆為既有或標準函式庫）。

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| （無新增外部套件） | — | — | — | — | — | — |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

若 planner 改採 PySide6 或 pywebview，**必須**先重新執行 Package Legitimacy Gate（slopcheck＋`pip index versions`），並在計畫中加入 `checkpoint:human-verify`。本研究未對 PySide6 做 registry 驗證，任何版本數字皆不採用。

## Architecture Patterns

### System Architecture Diagram

```
[醫師按下 紅／綠／黃]
        │
        ▼
[ElcTrafficBar.exe]  Tkinter windowed 程序（topmost、toolwindow、可拖曳）
   │  ① 紅/綠：HTTP 127.0.0.1 + 本機 token（指令 + command_id 冪等）
   │  ⑥ 黃：HTTP 到 elc server（cycle_id，CAS 封存）
   │  ↻ 每 5 秒心跳：回應內含「targeted 通知」（cycle_id、draft_id、state；無 SOAP）
   ▼
[SoapVoice 程序, FastAPI]  錄音、擷取病人（start 帶 patient_context）
   │  ② /api/v1/consultation/start   （紅）
   │  ③ /api/v1/consultation/stats   （狀態回報，bar 輪詢）
   │  ④ /api/v1/consultation/end + /soap/generate（綠）
   │  ⑤ POST /api/soap/recordings（X-API-Key；session_id 冪等）
   ▼
[elc-audit-engine server]  gunicorn 1 worker × 8 threads, 127.0.0.1 + 反向代理
   ├─ recording_cycles（cycle_id, machine_id, session_id, draft_id, state）
   ├─ soap_drafts（validated → approved → queued → pushed，既有狀態機）
   ├─ client_presence（machine_id, room_id, cycle_state, last_seen_at）
   └─ bridge HIS_PUSH 佇列 → Windows agent（ElcAgent，需加 agent 綁定）
        ▲
        │ 監控頁輪詢 /api/clients（僅狀態，無內容）
[static/index.html 新分頁「多連線監控」]  卡片：機器名、診間、狀態燈、最後心跳
        │ 點入卡片 → 權限檢查後才取 /api/cycles/<cycle_id>/draft
```

圖中 ②～⑥ 對應 D-31-05 循環：紅（②）→ 綠（④⑤）→ server 產草稿 → 醫師確認（review window，approve）→ 黃（⑥，封存）。

### Recommended Project Structure（新增檔案，僅列建議位置）
```
deploy/windows_agent/
├── traffic_bar/             # 新：ElcTrafficBar 程序（Tkinter）
│   ├── __init__.py
│   ├── bar_state.py         # 純函式狀態機（可在 Linux 測試，不 import tkinter）
│   ├── bar_window.py        # Tk 視窗（延遲 import tkinter，同 review_window.py 慣例）
│   ├── soapvoice_client.py  # 本機 HTTP 指令（127.0.0.1）
│   └── server_client.py     # 心跳與封存（重用 DefaultHttpClient）
└── ElcTrafficBar.spec       # 新：windowed（console=False）
src/elc_audit_engine/
├── cycles/                  # 新：循環狀態機純函式 + 存檔
├── client_presence/         # 新：presence 表存取（或併入 case_store）
└── api/routes/
    ├── clients.py           # 新：GET /api/clients（監控）、POST /api/clients/heartbeat
    └── cycles.py            # 新：POST /api/cycles、POST /api/cycles/<id>/archive、GET /api/cycles/<id>/draft
```

### Pattern 1: 循環狀態機（單一真相在 server，bar 只投影）

**What:** 循環狀態由 server 的 `recording_cycles.state` 決定；bar 的按鈕可用性是 server 狀態的投影，並在本機額外做一道防呆（D-31-11）。
**When to use:** 所有按鈕操作。
**Example:**
```python
# 純函式，可在 Linux 測試（不 import tkinter）— 建議放 traffic_bar/bar_state.py
ENABLED = {
    "IDLE":             {"red"},            # 待命：只能開始
    "RECORDING":        {"green"},          # 錄音中：只能結束錄音
    "AWAITING_DRAFT":   set(),              # 等 server 產草稿：黃燈停用（D-31-08）
    "AWAITING_CONFIRM": set(),              # 草稿待醫師確認：黃燈仍停用
    "CONFIRMED":        {"yellow"},         # 醫師已確認（approved/queued/pushed 之一）
    "ARCHIVING":        set(),              # 存檔中：全部停用，防重複送出
    "ARCHIVE_FAILED":   {"yellow"},         # D-31-07：保留狀態，可重試封存
}

def on_press(state: str, button: str) -> tuple[str, str | None]:
    """回傳 (new_state_or_same, toast_message_or_None)。非法操作忽略並提示。"""
    if button in ENABLED.get(state, set()):
        return state, None  # 實際轉移由 server 回應決定，本機不先行轉移
    return state, "目前狀態不允許此操作"
```

### Pattern 2: 推送方式評估 — heartbeat 搭便車（建議）

**What:** bar 每 5 秒送 `POST /api/clients/heartbeat`（沿用既有 agent 心跳的 upsert 模式），回應中帶本機的 targeted 通知，**只含 ID 與狀態，不含 SOAP**。

**Response 範例（建議格式，尚未實作）：**
```json
{
  "status": "ok",
  "server_time": "2026-11-12T03:00:00+00:00",
  "notify": {
    "cycle_id": "cyc_8f3a…",
    "state": "AWAITING_CONFIRM",
    "draft_id": "drf_…",
    "draft_version": 3
  }
}
```
bar 收到 `AWAITING_CONFIRM` 後，才以 operator 身分呼叫 `GET /api/cycles/<cycle_id>/draft` 取內容並自動開啟確認視窗（D-31-12、D-31-13）。

**推送方式比較（採用輪詢）：**

| 面向 | 輪詢（heartbeat 搭便車） | SSE（text/event-stream） |
|------|--------------------------|--------------------------|
| gunicorn gthread 8 threads | 每次請求短暫佔用，無長駐 | **每條連線長駐佔用 1 條 thread**；8 條即耗盡，監控頁開多分頁或多診間即會阻塞業務請求 [VERIFIED: deploy/gunicorn.conf.py `threads` 預設 8] |
| 認證 | 既有 `X-API-Key` 標頭 | 瀏覽器 `EventSource` 無法設定自訂標頭，需改用 query string 或 cookie；query string 會進入 access.log（[ASSUMED]，WHATWG 規格，本次未查證） |
| 反向代理（Caddy/Nginx） | 無特殊設定 | 需關閉緩衝（如 Nginx `X-Accel-Buffering: no`）；AGENTs.md §6 規定前面須有 TLS 代理 [CITED: AGENTs.md §6] |
| 既有模式 | 符合：`static/index.html` 使用 `setInterval` 輪詢 [VERIFIED]；Windows agent 的 `AgentConfig.poll_interval` 預設 5.0 秒 [VERIFIED: agent.py]（實際主迴圈節奏未驗證） | repo 內無 SSE 端點；`sse-starlette` 僅存在於 SoapVoice 依賴，不在本倉 |
| 延遲 | 約 5 秒（可調） | 即時 |
| 實作成本 | 低，重用既有 upsert 與 authFetch | 高，需新 generator、gthread 行為驗證、代理設定 |

**結論：** 採輪詢。若 planner 仍要 SSE，須先在實機以 `gthread` 8 threads 驗證並加上連線上限，列為風險。

### Pattern 3: 指令通道（bar → SoapVoice）

**建議：** 本機 HTTP，沿用 SoapVoice 既有 `/api/v1/consultation/*`，但加上以下三項硬化（兩倉同步定義，D-31-03）：

| 端點（SoapVoice 既有） | 用途 | 目前行為（已驗證） | 需要的變更 |
|-----------------------|------|--------------------|-----------|
| `POST /api/v1/consultation/start` | 紅燈 | 若 `RECORDING`/`PAUSED` 會直接 `flow.reset()`（**會丟棄進行中錄音**）；接受 `patient_context` | 改為：錄音中回 409，不 reset；接受 client 提供的 `command_id` 冪等 |
| `POST /api/v1/consultation/end` | 綠燈 | 非錄音中回 400 | 維持；加 `command_id` 冪等（重複綠燈回既有結果） |
| `GET /api/v1/consultation/stats` | 狀態回報 | 回 `state`、`session_id`、`elapsed_seconds` | 維持；bar 以此為本機狀態來源 |

**不建議：** 直接讓 bar 呼叫 `/api/v1/consultation/ws`（WebSocket）；它是逐字稿串流，不是指令通道，且對 bar 而言過重。

**綁定方式：** `session_id` 由 SoapVoice 於 start 時產生（`session_manager` 既有 `_generate_session_id`），`cycle_id` 由 server 於綠燈前建立，兩者以 `session_id` 對應（既有 `soap_recording_sessions` 表已做 `session_id → draft_id` 映射）。

### Anti-Patterns to Avoid
- **在 bar 內錄音或 import 音訊函式庫：** 違反 D-31-01。驗證方式見 Validation Architecture。
- **用 `deploy/windows_agent/window_utils.keep_on_top()` 給 bar：** 該函式呼叫 `focus_force()`，會搶走焦點，可能干擾 HIS 的 UIA 寫入（agent-desktop 依前景視窗操作）。bar 應僅設 `-topmost`，不取焦點。
- **用 `/api/soap/live-session` 作為監控資料來源：** 該端點是寫死的示範資料（`his_integration.py` 內 `PATIENT_DB` 與固定 `is_recording: True`），不反映真實狀態；且其名稱與 D-31-15 易混淆。
- **用 `agent_heartbeats` 表做 D-31-15 監控：** 只有 `is_online`（30 分鐘）與 HIS 狀態，無循環狀態、無 room。
- **以 `case_seq` 作為循環鍵：** 違反 AGENTs.md 不變式 3；循環鍵必須為 `cycle_id`（UUID）或 `session_id`。
- **把 `pending-review` 清單直接當作確認視窗來源：** 該端點回傳**所有**已驗證草稿（見 Pitfalls #4），違反 D-31-16。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Server 自動探索 | 新的 UDP 或子網掃描 | `deploy/windows_agent/discovery.py` 的 `discover_server()` | D-30-08 已實作；含 `/api/health` 身分檢查與「探測不送 key」規則 |
| 手動輸入伺服器位址 | 新表單 | `validate_manual_server_url()` | 已限制 RFC1918 與 http scheme |
| 認證比對 | `==` 比對 key | `hmac.compare_digest`（`auth.resolve_caller`） | 時序側通道；AGENTs.md 已規定 |
| 狀態機轉換 | 散落的 if-else | 既有 `soap_draft_states.py` 的轉換表模式，循環狀態機照此做 | 既有 `assert_draft_transition_allowed` 即為範本 |
| 冪等請求 | 自製 flag | 既有 `soap_recording_sessions` 的 session_id 映射模式，並修正其 TOCTOU（見 Pitfalls） | 已有 UNIQUE 語意的基礎 |
| 認證失效／權限切換 | 自製權限表 | `ELC_AGENT_KEYS` + `AGENT_ALLOWED_ENDPOINTS` 的 default-deny 模式 | 新端點預設受保護（`security.py` before_request） |
| 單一實例（bar 不可開兩個） | 檔案鎖自寫 | Windows named mutex（`ctypes.windll.kernel32.CreateMutexW`）[ASSUMED，未驗證 API 細節] | 標準做法；列為待實作驗證 |
| 開機自動啟動 | 寫登錄檔 | Inno Setup `{userstartup}` 捷徑（`PrivilegesRequired=lowest`） | 既有安裝腳本已用 lowest 權限 |

**Key insight:** 本 phase 最容易出錯的不是 UI，而是「誰能看到誰的草稿」與「存檔／寫入是否重複」。這些都應複用既有的 CAS、session 冪等與 default-deny 認證，而非新寫。

## Common Pitfalls

### Pitfall 1: 黃燈「確認」與「HIS 寫入完成」不是同一件事
**What goes wrong:** `approve` 只把草稿推進到 `approved → queued` 並排入 HIS_PUSH；真正寫入由 Windows agent 非同步完成，可能失敗並進入重試（最多 3 次後 `FAILED_PERMANENT`）。
**Why it happens:** `_approve_draft_record` 將「醫師確認」與「排入寫入」合併，寫入結果不回流到 approve。
**How to avoid:** planner 須決定黃燈門檻（見 Open Questions Q3）：建議至少 `approved`/`queued`；若要求 `pushed` 則黃燈會被 HIS 寫入速度卡住。封存內容需記錄「確認版 content_hash」而非「寫入結果」。
**Warning signs:** 黃燈後草稿仍為 `queued`，或 HIS_PUSH 任務 `FAILED`。

### Pitfall 2: approve 的崩潰窗口（已由程式碼確認）
**What goes wrong:** `_approve_draft_record` 依序執行：(a) 更新草稿為 `approved` → (b) `enqueue_job` → (c) 更新為 `queued`。若 (a) 與 (b) 之間程序崩潰，草稿停在 `approved`，**沒有對應 HIS_PUSH 任務**。而 `approved` 不在 `(validated, failed)` 允許名單，醫師重按 approve 會得到 409，草稿永久卡住。
**Why it happens:** 三個寫入不在同一交易內；`enqueue_job` 使用獨立的 store 呼叫。
**How to avoid:** 在 planner 的計畫中加入：(1) 將 (a)(b)(c) 包進單一交易，或 (2) 允許 `approved` 狀態重新 enqueue（以 `draft_id` + `content_hash` 冪等）；並加入對應崩潰測試。黃燈的 `ARCHIVE_FAILED` 重試亦依賴此修正。
**Warning signs:** 草稿為 `approved` 但 `bridge` 任務表無對應 `draft_id`。

### Pitfall 3: HIS_PUSH 任務未綁定 agent（多機時會錯機寫入）
**What goes wrong:** `ElcAgent` 以 `GET /api/bridge/jobs/pending?sTypeCode=HIS_PUSH` 輪詢，**不帶 agent 識別**，`list_pending_jobs` 也**不依 agent 過濾**。任何一台已校正的 agent 都可能認領他診間的任務。
**Why it happens:** Phase 29 設計為單一診間單一 agent；多連線（D-31-16）打破此假設。
**How to avoid:** 將 `machine_id`（或 `room_id`）寫入 HIS_PUSH 的 `extra_payload`，agent 輪詢時帶上自身 `machine_id`，`list_pending` 僅回傳相符任務。這是 D-31-16 的必要修正，應列為獨立子任務。
**Warning signs:** 同一任務出現 `patient_mismatch` 失敗並累計 `retry_count`，最後 `FAILED_PERMANENT`。

### Pitfall 4: 草稿清單與確認視窗跨診間混用（D-31-16 違反點）
**What goes wrong:** `GET /api/soap/drafts/pending-review` 回傳**所有** `validated` 草稿（最多 50 筆），`review_window.py` 以下拉選單呈現。兩台客戶端同時有草稿時，醫師可能在 A 機的循環中確認了 B 機的草稿。
**Why it happens:** 既有 review window 不知道 cycle，只知道全域清單。
**How to avoid:** 循環確認必須以 `cycle_id → draft_id` 直接開啟，不得經由全域清單；全域清單僅保留給既有的人工審核流程。
**Warning signs:** 確認視窗的草稿 `draft_id` 與該循環記錄不一致。

### Pitfall 5: SoapVoice `start` 會丟棄進行中錄音
**What goes wrong:** `consultation_api.start_consultation` 在 `RECORDING`/`PAUSED` 時呼叫 `flow.reset()`。紅燈若因按鈕重複、網路重送或 bar 重啟後誤判狀態而重送，**進行中的錄音與逐字稿會被清除**。
**Why it happens:** 設計上以「重開一個會話」處理衝突，對指令通道而言是危險語意。
**How to avoid:** SoapVoice 改為 409；bar 以 `stats` 為準，並搭配 `command_id` 冪等。這是 SoapVoice 倉的必要變更。
**Warning signs:** 紅燈後 `elapsed_seconds` 歸零、`session_id` 變更。

### Pitfall 6: SoapVoice 控制介面無認證且預設綁定 0.0.0.0
**What goes wrong:** `start_server.py` 預設 `HOST=0.0.0.0`，`consultation_api` 的 `/start`、`/end` 無任何認證依賴（grep 無 `Depends`/`api_key`）。區網任何機器都能遙控診間錄音。
**Why it happens:** SoapVoice 原為單機開發設計。
**How to avoid:** 指令通道綁定 `127.0.0.1`；並加本機 token（存於 bar 與 SoapVoice 共同的權限受限設定，如 `%LOCALAPPDATA%`），不得放在 repo。
**Warning signs:** `netstat` 顯示 SoapVoice 監聽 `0.0.0.0:<port>`。

### Pitfall 7: `/api/soap/recordings` 冪等檢查為 TOCTOU（非原子）
**What goes wrong:** `receive_recording` 順序為：`get_recording_session(session_id)` → 寫入音檔 → `_create_draft_record` → `put_recording_session`。兩個同 `session_id` 的並發請求（例如綠燈重送、或 SoapVoice 佇列重試）可能都通過第一步，建立**兩份草稿**。
**Why it happens:** 查詢與寫入不在同一交易，且音檔寫入在前。
**How to avoid:** 以 `session_id` 的 UNIQUE 約束先行「占位」（INSERT 成功才繼續），或以 per-session 鎖；失敗路徑需清除音檔（既有程式已有清除邏輯，但只在 draft 建立失敗時觸發）。
**Warning signs:** `soap_drafts` 同一 `case_id` 出現多筆 `validated`，且其 `session_id` 相同。（[ASSUMED] 本研究僅由程式碼推論，未以並發測試重現。）

### Pitfall 8: 崩潰後循環狀態遺失（bar 重啟）
**What goes wrong:** 若 bar 狀態只存在記憶體，重啟後會誤判為「待命」，使 SoapVoice 仍在錄音的循環被遺忘，或紅燈被重送（見 Pitfall 5）。
**Why it happens:** 本機無持久循環狀態。
**How to avoid:** bar 不持有權威狀態；啟動時先以 `GET /api/v1/consultation/stats`（SoapVoice）與 `GET /api/cycles?machine_id=`（server）還原。若 SoapVoice 仍在 `RECORDING` 但 server 無對應 cycle，標為 `INTERRUPTED`，**由醫師明確選擇**（不得靜默丟棄音檔）。
**Warning signs:** 重啟後 SoapVoice `state=RECORDING` 而 bar 顯示「待命」。

### Pitfall 9: 黃燈雙擊（double-submit）
**What goes wrong:** 醫師雙擊黃燈，送出兩個封存請求。
**How to avoid:** 三層防護：(1) bar 按下即轉 `ARCHIVING` 並停用所有按鈕；(2) server `archive` 以 `recording_cycles.state` 做 CAS（`WHERE state IN ('CONFIRMED','ARCHIVE_FAILED')`），第二次回 `already_archived` 200（冪等，回傳同一封存清單）；(3) 封存清單以 `cycle_id` 為鍵。
**Warning signs:** 同一 `cycle_id` 出現兩筆 archive 審計列。

### Pitfall 10: Tk 視窗搶焦點或遮擋 HIS 操作區
**What goes wrong:** `-topmost` 視窗若與 HIS 寫入區重疊，會擋住 agent-desktop 的點擊；若取得焦點，會打斷 HIS 輸入。
**How to avoid:** 窗口尺寸小、固定於工作列上方右下角（CONTEXT 已指定）；使用 `-toolwindow True`（Windows 專屬，隱藏工作列按鈕）與 `-topmost True`；**不呼叫** `focus_force`；標題避免包含 HIS 名稱（AGENTs.md §5b 指出 `--app` 關鍵字可能造成 `AMBIGUOUS_TARGET`）。
**Warning signs:** agent-desktop `set-value` 失敗或目標視窗誤判。

### Pitfall 11: 多螢幕或 DPI 導致位置記憶失效
**What goes wrong:** 記住的座標若落在已拔除的螢幕，視窗會「消失」。
**How to avoid:** 讀取位置後檢查是否落在任一螢幕可視範圍，否則回到右下角預設值（純函式，可測）。

### Pitfall 12: Tk 的 `overrideredirect` 會失去視窗管理器控制
**What goes wrong:** 若用 `overrideredirect(True)` 做無邊框，視窗不再受視窗管理器管理，拖曳與焦點行為需自行處理。
**How to avoid:** 建議用 `-toolwindow` 而非 `overrideredirect`；若必須無邊框，拖曳以 `<ButtonPress-1>`／`<B1-Motion>` 自行實作。[CITED: https://www.tcl-lang.org/man/tcl8.6/TkCmd/wm.htm — overrideredirect 的說明]

## Code Examples

### Example A：heartbeat 端點的 PHI-free 回應（建議，尚未實作）
```python
# 建議位置：src/elc_audit_engine/api/routes/clients.py（新）
# 參照既有 agent_bridge.py 的 _json_object() 與 record_agent_heartbeat 模式
@bp.route("/api/clients/heartbeat", methods=["POST"])
def client_heartbeat():
    data = _json_object()
    machine_id = str(data.get("machine_id") or "").strip()
    if not machine_id:
        raise ApiError("缺少 machine_id", status=422)
    store = case_store()
    store.upsert_client_presence(
        machine_id=machine_id,
        room_id=str(data.get("room_id") or "").strip() or None,
        cycle_state=str(data.get("cycle_state") or "").strip() or None,
    )
    notify = store.pending_notification_for_machine(machine_id)  # 只回 ID 與狀態
    return jsonify({"status": "ok", "notify": notify}), 200
```
（建議命名；實際端點命名與 blueprint 註冊需依 `api/routes/__init__.py` 的 `ALL_BLUEPRINTS` 模式。）

### Example B：指令通道的認證 header（bar → SoapVoice，建議）
```python
# 本機 token 不得寫入 repo；由安裝程序寫入使用者權限設定檔
req = urllib.request.Request(
    "http://127.0.0.1:<soapvoice_port>/api/v1/consultation/start",
    data=json.dumps({"command_id": cmd_id, "patient_context": ctx}).encode("utf-8"),
    headers={"Content-Type": "application/json", "X-Local-Token": local_token},
    method="POST",
)
```
（`X-Local-Token` 為建議 header 名稱；SoapVoice 端需新增驗證依賴，目前不存在。）

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `agent_heartbeats` 30 分鐘離線判定 | 秒級 presence（5 秒心跳、15 秒離線）| 本 phase 新增 | D-31-15 所需 |
| `/api/soap/live-session` 寫死示範資料 | 真實 `recording_cycles` 查詢 | 本 phase | 避免監控頁顯示假資料 |
| 全域 `pending-review` 清單確認 | 循環綁定的 `cycle_id → draft_id` | 本 phase | D-31-16 |

**Deprecated/outdated（本 repo 內）：**
- `/api/soap/live-session` 與 `his_integration.PATIENT_DB`：示範用，不應作為監控資料來源。
- Phase 30 的 `DEFAULT_CENTRAL_SERVER_URL = "http://192.168.68.118:5000"`（`deploy/windows_agent/main.py`）：硬編碼 IP，與 D-30-08「不得依賴固定 IP」衝突，bar 應重用 discovery 而非複製此常數。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `EventSource` 無法設定自訂 HTTP 標頭（需改 query string 或 cookie） | Pattern 2 | 若可行，SSE 認證成本降低，但仍有 thread 佔用問題，結論不變 |
| A2 | Nginx 預設緩衝 SSE 需以 `X-Accel-Buffering: no` 關閉 | Pattern 2 | 代理設定錯誤會導致推送延遲，需實機驗證 |
| A3 | Windows named mutex 以 `CreateMutexW` 實作單一實例 | Don't Hand-Roll | 替代方案為鎖檔，風險低 |
| A4 | `-topmost` 在全螢幕應用下可能失效，需定期 `lift` 或接受限制 | Pitfall 10 | 若失效，需 planner 決定是否加定時重設頂 |
| A5 | `/api/soap/recordings` 的 TOCTOU 會在並發下產生重複草稿 | Pitfall 7 | 若 DB 有隱性 UNIQUE 約束則不會發生；需並發測試確認 |
| A6 | `start_server.py` 的預設連接埠 8010 為實際部署埠 | Pattern 3 | `run_gui.py` 用 8000，兩者不一致；需確認（Q6） |
| A7 | 病歷保存期限與「封存」的法規要求 | Architecture（封存內容） | 屬法規事項，本研究未查證，不得臆測（Q9） |
| A8 | SoapVoice 的錄音格式為 WAV（符合 `/api/soap/recordings` 契約） | Open Question Q7 | 若為 Opus，上傳會 422 |

**If this table is empty:** N/A（有上列假設，均需使用者或實機確認後才能成為鎖定決策）。

## Open Questions

1. **Q1 診間（room）的識別來源**
   - What we know: `config/facility.json` 有機構代碼 `code`（`get_facility_code()` 讀取），屬於**診所**層級，不區分診間。`deploy/windows_agent/config.template.json` 有 `machine_id` 欄位（空字串）。目前沒有任何「診間」清單來源。
   - What's unclear: 同一診所有幾間診間、是否每間都有一台工作站、診間名稱由誰定義。
   - Recommendation: **建議選項 A**：工作站 `config.json` 新增 `room_id`，於首次啟動（沿用 D-30-08 的手動輸入畫面）填寫，server 以 `config/` 內的白名單驗證；未設定顯示「未指定診間」。**不建議**以 IP 推斷（Phase 29 已確認主機 IP 不固定；D-30-08 亦要求不依賴固定 IP）。
   - **需使用者確認：** 診間清單來源（誰維護？放 `facility.json` 或新檔？）。

2. **Q2 ElcTrafficBar 與 ElcAgent 的發行方式**
   - What we know: `installer/build_clinic_installer.py` 的 Inno Setup 元件為 LittleB、AgentDesktop、WebBrainBridge、RetryManager，**不含** ElcAgent；ElcAgent 另以 `ElcAgent.spec` 做 one-folder 攜帶版（D-30-07）。
   - Recommendation: bar 做成獨立 `ElcTrafficBar.spec`（`console=False`），加入 Inno 元件並以 `{userstartup}` 捷徑開機啟動。
   - **需使用者確認：** 是否與 ElcAgent 同包或獨立；「安裝後自動啟動」是否接受每使用者（非系統服務）的啟動方式。

3. **Q3 黃燈門檻：`approved` / `queued` / `pushed`？**
   - Recommendation: 至少 `approved` 或 `queued` 即可亮黃燈（醫師已確認），`pushed` 由後續狀態通知更新但不阻擋封存。需使用者確認「醫師已確認」的定義是否包含「HIS 寫入失敗後仍封存」。

4. **Q4 草稿為 `quality_failed` 或醫師 `reject` 時循環如何處置？**
   - What we know: 兩者皆為終態（`soap_draft_states.py`），不能再 approve。D-31-08 規定黃燈需醫師確認。
   - Recommendation: 新增循環狀態 `NEEDS_REGENERATE`，允許重新產生草稿（SoapVoice 再 `/soap/generate` 並以同一 `session_id` 不可重用 → 需新 `session_id`，產生新 cycle 或同 cycle 新 draft 的規則需定）。需 planner 決定。

5. **Q5 bar 使用哪一把 key？**
   - What we know: `ELC_AGENT_KEYS` 的角色只允許心跳與 HIS_PUSH 相關端點（`AGENT_ALLOWED_ENDPOINTS`）；讀取草稿內容與封存需要非 agent 的 operator key（既有 review window 也使用 `operator_key`）。
   - Recommendation: heartbeat 用 agent key（需把 `clients.heartbeat` 加入 `AGENT_ALLOWED_ENDPOINTS`）；讀草稿與封存用 operator key（既有 `operator_key` 設定）。此設計讓工作站持有可讀病歷的 key，需使用者確認可接受（D-30-09 已採此模式）。

6. **Q6 SoapVoice 的實際埠號與綁定位址**
   - What we know: `start_server.py` 預設 8010、`HOST=0.0.0.0`；`run_gui.py` 使用 `127.0.0.1:8000`。
   - Recommendation: 統一為 `127.0.0.1:<固定埠>`，埠號由兩倉共同定義（D-31-03）。

7. **Q7 SoapVoice 上傳音檔格式**
   - What we know: `/api/soap/recordings` 僅接受 `audio/wav` 或 `.wav`（`validate_recording_payload`）；SoapVoice LAN 處理端點將音檔壓縮為 Opus（`lan_process_api.py` 註解）。SoapVoice 倉目前有未提交變更（`client/lan_client.py` 已含 `_do_upload_to_elc`）。
   - Recommendation: 實作前確認實際上傳格式；若為 Opus，需在 SoapVoice 端轉 WAV 或兩倉同步放寬契約（列入 D-31-03）。

8. **Q8 Phase 30 的相依狀態**
   - What we know: `git log` 顯示 Phase 30 停在 `30-09` 探針 PASS（WinBoat）；`30-11`（雲端回傳與預先校正）尚未完成；D-31-14 需要校正 profile。
   - Recommendation: planner 應在計畫中標明「依賴 Phase 30 的 30-09 PASS 與 30-10 校正精靈」；未校正機器的回寫門檻沿用 D-30-11。

9. **Q9 封存（D-31-06）的保存期限與位置**
   - 本研究未查證病歷保存年限，不得自行決定。需使用者或法規確認後才能定案保存期限與是否離機備份（D14 雲端備份政策仍在延後事項）。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python（Windows 客戶端） | bar、agent | 本研究環境為 Linux，**Windows 實機未驗證** | 倉庫要求 3.12（`.venv` 由 uv 管理） | — |
| tkinter | bar 視窗 | 於 Linux 開發機可 import（需 `python3-tk`）；Windows 隨 Python 安裝 | 隨 Python | 無（必要） |
| Windows 實機（置頂、toolwindow、工作列隱藏行為） | D-31-09～11 驗證 | ✗（本研究無實機） | — | 需人工 UAT（WinBoat 或實體機） |
| PyInstaller | `ElcTrafficBar.spec` | 既有 `ElcAgent.spec` 使用 | 既有 | — |
| SoapVoice 服務（`127.0.0.1` 指令通道） | 紅綠燈指令 | 需於 Windows 實機運行 | — | 無；離線時 bar 顯示「SoapVoice 未連線」並停用紅燈 |
| elc-audit-engine（gunicorn） | 監控與封存 | Linux 開發機為 `systemctl --user` 服務（AGENTs.md §6） | 既有 | 離線時 bar 顯示 server 未連線，封存需重試（D-31-07） |

**Missing dependencies with no fallback:**
- Windows 實機驗證（置頂、toolwindow、UIA 互動）——需人工 UAT，無法在本研究環境完成。

**Missing dependencies with fallback:**
- 無。

## Validation Architecture

> 依 `workflow.nyquist_validation` 設定：本研究依使用者要求納入此節（未檢查 `.planning/config.json` 的該鍵，列為待確認）。

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest（`pyproject.toml` dev 依賴） |
| Config file | 既有 `tests/conftest.py`（AGENTs.md 指出含 `make_api_app` 隔離 DB fixture [CITED: AGENTs.md §5]，未於本研究實際開檔確認） |
| Quick run command | `ELC_ALLOW_NO_AUTH_FOR_TESTS=1 uv run pytest -q tests/test_<新模組>.py` |
| Full suite command | `ELC_ALLOW_NO_AUTH_FOR_TESTS=1 uv run pytest -q tests doc/tests` [CITED: AGENTs.md §5] |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| D-31-01 | bar 程序不 import 錄音相關模組、不開音訊裝置 | unit（靜態掃描） | `pytest tests/test_traffic_bar_no_recording.py -x` | ❌ Wave 0 |
| D-31-02 | 紅燈 payload 含病人資訊來源，bar 僅顯示 bound 旗標 | contract | `pytest tests/test_soapvoice_ipc_contract.py -x` | ❌ Wave 0 |
| D-31-03 | 兩倉共用 IPC fixture（start/end/stats 的 JSON 形狀） | contract（兩倉各跑一次） | `pytest tests/test_soapvoice_ipc_contract.py -x`（elc）；SoapVoice 同名測試 | ❌ Wave 0（兩倉） |
| D-31-05 | 循環完整路徑 IDLE→RECORDING→AWAITING_DRAFT→AWAITING_CONFIRM→CONFIRMED→ARCHIVED | unit（純函式） | `pytest tests/test_cycle_state_machine.py -x` | ❌ Wave 0 |
| D-31-06 | 封存包含音檔、草稿、確認版 hash、審計；成功才回 IDLE | integration（API＋tmp DB） | `pytest tests/test_cycle_archive.py -x` | ❌ Wave 0 |
| D-31-07 | 封存失敗 → ARCHIVE_FAILED，保留循環，可重試 | integration（注入失敗） | `pytest tests/test_cycle_archive.py::test_failure_keeps_state -x` | ❌ Wave 0 |
| D-31-08 | 草稿未確認時封存回 409；黃燈停用 | unit＋API | `pytest tests/test_cycle_archive.py::test_archive_requires_confirmed -x` | ❌ Wave 0 |
| D-31-09 | 位置記憶；離開螢幕範圍時回預設 | unit（純函式） | `pytest tests/test_bar_position.py -x` | ❌ Wave 0 |
| D-31-10 | 收合三鈕；展開僅顯示狀態與連線 | manual UAT（Windows） | 人工驗證（無自動化） | — |
| D-31-11 | 非法操作忽略並回提示；狀態機表 | unit（純函式） | `pytest tests/test_bar_state.py -x` | ❌ Wave 0 |
| D-31-12 | 未認證請求無病歷內容；heartbeat 回應 schema 不含 soap 鍵 | API（無 key／錯 key） | `pytest tests/test_client_notify_auth.py -x` | ❌ Wave 0 |
| D-31-13 | 確認視窗 S/O/A/P 四欄；advisory 為 read_only | UI（Tk）＋API | `pytest tests/test_review_advisory_readonly.py -x`（API）；視窗為人工 UAT | ❌ Wave 0 |
| D-31-14 | 未校正不得真實回寫；封存不繞過校正門檻 | unit（既有 `_writeback_allowed` 測試延伸） | `pytest tests/test_agent_calibration_gate.py -x` | ⚠️ 既有模式，需新增案例 |
| D-31-15 | `/api/clients` 列出 machine、room、狀態、最後心跳 | API | `pytest tests/test_clients_monitor.py -x` | ❌ Wave 0 |
| D-31-16 | 兩客戶端並行循環，草稿不互混；跨 client 讀取被拒 | integration（併發） | `pytest tests/test_cycle_isolation.py -x` | ❌ Wave 0 |
| D-31-17 | 監控列表 schema 不含 SOAP 內文；點入需權限 | API | `pytest tests/test_clients_monitor.py::test_no_content -x` | ❌ Wave 0 |
| (風險) Pitfall 2 | approve 崩潰後草稿可恢復 | integration（注入崩潰） | `pytest tests/test_approve_crash_window.py -x` | ❌ Wave 0 |
| (風險) Pitfall 3 | HIS_PUSH 任務不被錯機領取 | integration | `pytest tests/test_bridge_agent_affinity.py -x` | ❌ Wave 0 |
| (風險) Pitfall 5 | SoapVoice 錄音中 start 回 409，不 reset | SoapVoice 單元 | SoapVoice 倉 `pytest` | ❌ Wave 0（SoapVoice） |
| (風險) Pitfall 7 | 同 session_id 並發只產生一份草稿 | integration（並發） | `pytest tests/test_recording_idempotency_race.py -x` | ❌ Wave 0 |
| (風險) Pitfall 9 | 雙擊黃燈只產生一筆封存 | integration（並發） | `pytest tests/test_cycle_archive.py::test_double_submit -x` | ❌ Wave 0 |
| (風險) Pitfall 10 | 視窗不取得焦點、不遮擋 HIS | 人工 UAT（WinBoat） | 人工驗證 | — |

### Sampling Rate
- **Per task commit:** 該任務對應的單一 `pytest tests/test_<module>.py -x`
- **Per wave merge:** `ELC_ALLOW_NO_AUTH_FOR_TESTS=1 uv run pytest -q tests`
- **Phase gate:** 全套件綠燈＋Windows 實機 UAT 清單（D-31-09/10/11/13/10 與 Pitfall 10）完成後才能 `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_cycle_state_machine.py` — 循環狀態機（D-31-05/08/11）
- [ ] `tests/test_cycle_archive.py` — 封存、失敗保留、冪等（D-31-06/07/08、Pitfall 9）
- [ ] `tests/test_clients_monitor.py` — presence 與監控 schema（D-31-15/17）
- [ ] `tests/test_client_notify_auth.py` — 推送認證（D-31-12）
- [ ] `tests/test_cycle_isolation.py` — 多客戶端綁定（D-31-16）
- [ ] `tests/test_soapvoice_ipc_contract.py` — 兩倉共用 IPC 契約（D-31-03）
- [ ] `tests/test_bridge_agent_affinity.py` — HIS_PUSH 綁定（Pitfall 3）
- [ ] `tests/test_approve_crash_window.py` — Pitfall 2
- [ ] `tests/test_recording_idempotency_race.py` — Pitfall 7
- [ ] `deploy/windows_agent/traffic_bar/` 純函式測試（bar_state、bar_position）可於 Linux 執行，不需 tkinter 實際顯示
- [ ] SoapVoice 倉：`tests/test_consultation_ipc.py`（start 409、command_id 冪等、綁定 127.0.0.1）

## Security Domain

> `security_enforcement` 未於本研究確認為 false，故納入。

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | 既有 `auth.resolve_caller`（`hmac.compare_digest`）；bar 與 agent 使用不同 key 角色 |
| V3 Session Management | partial | 無瀏覽器 session；bar 以 token/key，不做 cookie |
| V4 Access Control | yes | `AGENT_ALLOWED_ENDPOINTS` default-deny；新端點預設受保護（`security.py` before_request） |
| V5 Input Validation | yes | `cycle_id`、`machine_id`、`room_id` 採 `safe_filename` 或正規表示式（同 `_SESSION_ID_RE`）；拒絕而非清洗 |
| V6 Cryptography | yes（僅沿用） | 不新做加密；本機 token 以 OS 權限保護 |
| V7 Error Handling and Logging | yes | `record_access(detail=...)` 有 PHI 鍵禁令（`AuditFieldError`，`audit_log.py`）；循環事件僅記 `cycle_id`/`draft_id` |
| V8 Data Protection | yes | 監控列表不含 SOAP（D-31-17）；封存音檔存放位置待 Q9 |
| V13 API and Web Service | yes | 指令通道綁定 127.0.0.1；SoapVoice 目前無認證，須補 |

### Known Threat Patterns for 本 phase 技術堆疊

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 區網其他機器遙控 SoapVoice 錄音（無認證 `/start`） | Spoofing／Elevation | 綁定 127.0.0.1 ＋ 本機 token（Pitfall 6） |
| 工作站偽造 `machine_id` 冒充他診間心跳 | Spoofing | 每台工作站獨立 key；`machine_id` 與 key 綁定（server 端以 key 解析，不採信 body） |
| 監控頁或 heartbeat 洩漏 SOAP | Information Disclosure | 回應 schema 測試（D-31-12/17） |
| 跨診間讀取草稿（循環 ID 猜測） | Information Disclosure | `cycle_id` 為 UUID；讀取時驗證 caller 權限；不回傳他機循環 |
| 重放封存請求 | Tampering／Repudiation | CAS＋冪等（Pitfall 9） |
| 審計 `detail` 夾帶 PHI | Information Disclosure | 只放 `cycle_id`、`draft_id`、`content_hash`，不放病人欄位 |
| 錯機寫入 HIS | Tampering | HIS_PUSH agent 綁定（Pitfall 3）＋ patient fail-closed（既有） |

## Sources

### Primary（HIGH confidence — 程式碼直接讀取）
- `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-CONTEXT.md` — D-31-01～17
- `.planning/phases/30-windows-exe-soap-review-calibration/30-CONTEXT.md` — D-30-01～12
- `deploy/windows_agent/agent.py`（`poll_pending_jobs` 僅以 sTypeCode 查詢；`run_once`；`heartbeat_interval=30`）
- `deploy/windows_agent/window_utils.py`（`keep_on_top` 使用 `focus_force`）
- `deploy/windows_agent/config.py`、`config.template.json`（`machine_id`、`operator_key`）
- `deploy/windows_agent/discovery.py`、`main.py`（`DEFAULT_CENTRAL_SERVER_URL` 硬編碼）
- `deploy/windows_agent/ElcAgent.spec`（`console=True`；僅排除 `tkinter.test`）
- `deploy/gunicorn.conf.py`（`workers=1`、`worker_class="gthread"`、`threads` 預設 8、`timeout` 300）
- `src/elc_audit_engine/api/security.py`（before_request、`AGENT_ALLOWED_ENDPOINTS`、私有 IP 免 key 僅限錄音端點）
- `src/elc_audit_engine/api/routes/bridge.py`（`list_pending_jobs` 僅 sTypeCode 過濾）
- `src/elc_audit_engine/bridge_queue.py`（CAS、租約、`max_retries`）
- `src/elc_audit_engine/api/routes/soap_review.py`（`_approve_draft_record`、`_maybe_auto_accept`、`approve_draft`）
- `src/elc_audit_engine/api/routes/soap_review_queue.py`（`pending-review` 回傳全部 validated 草稿）
- `src/elc_audit_engine/api/routes/soap_recording.py`（`receive_recording` 冪等順序；`validate_recording_payload` 僅 WAV）
- `src/elc_audit_engine/api/routes/agent_bridge.py`、`case_store/store.py`（`record_agent_heartbeat` upsert；`list_agent_heartbeats` 30 分鐘）
- `src/elc_audit_engine/case_store/db.py`（`agent_heartbeats` 表結構）
- `src/elc_audit_engine/case_store/store.py`（`update_soap_draft_state` 於單一交易內檢查轉換）
- `src/elc_audit_engine/api/routes/his_integration.py`（`/api/soap/live-session` 寫死資料）
- `src/elc_audit_engine/audit_log.py`（`detail` PHI 鍵禁令）
- `src/elc_audit_engine/api/routes/misc.py`（`/` 回傳 `static/index.html`，`/api/health`）
- `static/index.html`（`authFetch` 1850 行；`setInterval` 1983 行；`getApiKey` localStorage）
- `installer/build_clinic_installer.py`（元件清單不含 ElcAgent；`PrivilegesRequired=lowest`）
- `AGENTs.md`（§2 Hard Invariants；§5 測試指令；§5b MockHIS 不變式；§6 部署與 LAN 檢核）
- SoapVoice 倉（`~/Desktop/SoapVoice`）：`src/api/consultation_api.py`（start/end/stats；無 Depends）、`src/consultation/consultation_flow.py`、`src/consultation/session_manager.py`、`start_server.py`（預設 HOST 0.0.0.0、埠 8010）、`run_gui.py`（127.0.0.1:8000）、`client/lan_client.py`（`_do_upload_to_elc` → `/api/soap/recordings`；工作區有未提交變更）、`src/main.py`（路由掛載）

### Secondary（MEDIUM confidence）
- [CITED: https://www.tcl-lang.org/man/tcl8.6/TkCmd/wm.htm] — `wm attributes`：`-topmost` 為全平台屬性；`-toolwindow` 為 Windows 專屬（toolwindow 樣式）；`overrideredirect` 使視窗管理器忽略該視窗

### Tertiary（LOW confidence / ASSUMED）
- 見 Assumptions Log A1～A8（瀏覽器 `EventSource` 標頭限制、Nginx SSE 緩衝、Windows named mutex API、全螢幕 topmost 行為、TOCTOU 並發實際表現、SoapVoice 埠號、保存期限、WAV 格式）

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 全部為既有 repo 模式或標準函式庫，已由程式碼確認
- Architecture（循環狀態機、heartbeat 搭便車、指令通道）: MEDIUM — 設計建議，需於 Windows 實機與兩倉整合測試驗證
- Pitfalls: HIGH for #1～#6、#8、#9（程式碼可證）；MEDIUM for #7（僅程式碼推論）；MEDIUM for #10～#12（Tk 文件＋推論，未於實機重現）

**Research date:** 2026-11-12
**Valid until:** 2026-12-12（SoapVoice 倉有未提交變更，若該倉於此期間變動需重驗 IPC 端點；Phase 30 狀態變動亦會影響 Q8）

## Project Constraints（from AGENTs.md，無 CLAUDE.md）

- 工作區無 `./CLAUDE.md`；專案指示位於 `AGENTs.md`。其中 BLOCKING 不變式（§2）要求：`case_id` 為唯一全域鍵（不得以 `case_seq`）；日誌與審計不得含病人姓名、身分證、生日或 SOAP 文字；認證採 `X-API-Key`；`ELC_ALLOWED_HOSTS` 白名單。
- 伺服器綁定 `127.0.0.1`，LAN 開放需依 §6 檢核（反向代理 TLS、`ELC_ALLOWED_HOSTS`、強 key、不得設 `DISABLE_AUTH`）。bar 連線 LAN server 時，Host 標頭必須在白名單內。
- 測試指令：`ELC_ALLOW_NO_AUTH_FOR_TESTS=1 uv run pytest -q tests doc/tests`；測試不得寫入正式資料庫。
- 依賴鎖定：`uv lock --no-config`（全域 pydantic 限制）。本 phase 不新增依賴，故不影響。
- MockHIS 不變式（§5b）：Tk 子控件對 UIA 不可見；視窗標題避免與 HIS 應用程式關鍵字衝突。
- 使用者全域規則：回覆與文件以繁體中文為主、技術識別字保留英文。
