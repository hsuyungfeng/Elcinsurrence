# Phase 29 設計文件：LLM SOAP 草稿 → 標準範本比對 → 醫師審核 → Windows Agent 寫入 HIS

狀態：草案（待檢查）
範圍來源：使用者於 2026-11-09 的三點確認（見「需求對應」）

## 1. 目標

讓 LLM 預生成的 SOAP 草稿，經過「標準 SOAP 範本比對」與「醫師審核」後，才由區網內 Windows 主機上的
agent-desktop 寫入 HIS 門診病歷，並把寫入結果回存資料庫。未經醫師核准的內容一律不得寫入 HIS。

## 2. 需求對應（使用者確認）

| # | 使用者需求 | 設計對應 |
|---|---|---|
| R1 | LLM 預生成 SOAP 與標準 SOAP 範本比對，經醫師檢查後使用 | §4 草稿狀態機、§5 標準範本比對、§6 醫師審核 API |
| R2 | Windows 端 exe 使用 agent-desktop 寫入 HIS，並寫回資料庫 | §7 Windows Agent（沿用 `AgentDesktopRunner`／`HISPushAutomator`）、§8 寫入與寫回 |
| R3 | Windows 主機 IP 不固定，但同一區網、24 小時開機 | §7.2 Agent 主動拉取（pull）、心跳、無需固定位址 |

## 3. 既有可重用元件（已在程式中確認）

- `src/elc_audit_engine/bridge_queue.py`：CAS 任務佇列（PENDING → SENDING → SUCCESS／FAILED），租約逾時回收，重試上限。
- `src/elc_audit_engine/api/routes/bridge.py`：`POST /api/bridge/jobs`、`GET /api/bridge/jobs/pending`、`POST /api/bridge/jobs/<id>/status`、`GET /api/bridge/jobs/<id>`。
- `src/elc_audit_engine/agent_desktop_bridge.py`：`AgentDesktopRunner`（Observe–Act–Verify）、`HISPushAutomator`、`process_his_push_job`（以 CAS 保護的 HIS_PUSH 任務處理）。
- `src/elc_audit_engine/case_store/store.py`：`get_soap_template`／`put_soap_template`（既有通用範本快取，見 Phase 15/18）。
- `src/elc_audit_engine/comparator/soap_advice.py`：`validate_soap_quality`（200–500 字、英文為主、佔位字檢核）。

**不新增佇列系統**：HIS 寫入任務沿用 `bridge_queue`（`s_type_code="HIS_PUSH"`）。

## 4. 草稿狀態機（新）

```
draft ──validate(pass)──▶ validated ──compare(advisory)──▶ validated
  │                          │
  │                          ├── physician approve ──▶ approved ──enqueue HIS_PUSH──▶ queued ──agent ok──▶ pushed（終態）
  │                          │                                                        └──agent fail──▶ failed（可重試或人工）
  │                          └── physician reject ──▶ rejected（終態，不得寫入）
  └── validate(fail) ──▶ quality_failed（不得進入審核；可重新生成）
```

- 每次醫師編修產生新版本（`version` 遞增），`content_hash` 為 S/O/A/P 正規化文字的 SHA-256。
- `approved` 綁定 `content_hash`：送出 HIS_PUSH 時以雜湊為準，若之後內容變動則必須重新審核。
- `pushed`、`rejected`、`quality_failed` 為終態（`failed` 可由醫師重新排入，記錄原因）。
- 非法轉換拋出錯誤（與 `case_store/states.py` 同一原則：未知狀態不得默默忽略）。

## 5. 標準範本比對（advisory，不改寫草稿）

- 輸入：LLM 草稿（S/O/A/P）與該醫令的標準範本。**標準範本來源 = 現有 `soap_templates`**（已確認）。
- 輸出：每欄 `difflib` 相似度（0–1）、缺漏欄位、超出字數的欄位、ICD-10 代碼是否與規定原文一致。
- 比對結果只供醫師參考，**不作為自動核准條件**。
- 不得以比對分數自動把草稿改為 `validated` 以外的狀態。

## 6. 醫師審核 API（新）

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/api/soap/drafts/<draft_id>` | 草稿內容、版本、品質分數、比對摘要（需 X-API-Key） |
| POST | `/api/soap/drafts/<draft_id>/approve` | 逐案核准目前版本；body 含 `reviewer_id`、`content_hash`（防止審核舊版） |
| POST | `/api/soap/batches/<batch_id>/approve` | **批次核准**：對批次內所有 `validated` 草稿，逐案以各自 `content_hash` 核准；回傳每案結果，已變動者不核准 |
| POST | `/api/soap/drafts/<draft_id>/edit` | 醫師修改 S/O/A/P，建立新版本（回到 `validated` 並重新檢核） |
| POST | `/api/soap/drafts/<draft_id>/reject` | 退回，附 `reason`（代碼＋說明，不含病患資料） |

- 審核紀錄寫入 CaseStore 的審計欄位：`reviewer_id`、`decision`、`content_hash`、時間。日誌不記錄 SOAP 文字。
- `reviewer_id` 由呼叫端 API Key 對應，不接受任意字串。

## 7. Windows Agent（新，部署於區網 Windows 主機）

### 7.1 元件
- `deploy/windows_agent/agent.py`：常駐程序（以 Windows 服務或工作排程器開機啟動）。
- 使用既有 `AgentDesktopRunner` 與 `HISPushAutomator`；本機不新增 UIA 實作。
- 設定檔：伺服器 URL、Agent 金鑰、HIS 廠商設定檔名稱（vision／yaosheng／minger／chihshi）。

### 7.2 通訊（pull，解決 IP 不固定）
1. Agent 啟動後每 30 秒送心跳：`POST /api/agent/heartbeat`（Agent ID、版本、HIS 狀態、時間）。
2. 有空閒時 `GET /api/bridge/jobs/pending?sTypeCode=HIS_PUSH` 取得待處理任務（既有端點，參數為 `sTypeCode`，無 `limit`），再以 CAS 認領（既有 `claim` 邏輯）。
3. 完成後 `POST /api/bridge/jobs/<job_id>/status`，回報 `success` 或 `failed` 與原因代碼。
4. 伺服器端若 30 分鐘內沒有心跳，標記 agent 離線並通知（不影響 Linux 端其他功能）。
5. 網路中斷時 Agent 指數退避重試；伺服器重啟後租約逾時的任務由 `bridge_queue` 自動回收（既有機制）。

### 7.3 身分與權限
- Agent 使用獨立 Agent 金鑰（與醫師 API Key 分開），僅能呼叫心跳與 HIS_PUSH 相關端點。
- 伺服器只接受區網網段（`ELC_ALLOWED_HOSTS` 與防火牆）；金鑰不寫入日誌。

## 7.4 HIS 廠商設定檔（須現場校準）

- HIS 廠商未固定，寫入流程以**廠商設定檔**抽象：UI 元素定位、欄位名稱、讀回方式各自一份設定。
- 初版提供 vision／yaosheng／minger／chihshi 的骨架設定，**標示為未校準**。
- 上線前須在現場以測試病歷逐一校準，校準結果寫入設定檔並記錄校準日期與人員；未校準的廠商設定不得用於正式寫入（Agent 啟動時檢查並拒絕）。

## 8. 寫入與寫回（R2）

1. Agent 認領 HIS_PUSH 任務，payload 含 `case_id`、`content_hash`、`soap`（已核准版本）。
2. 寫入前先比對本機 HIS 目前病歷的 `case_id` 與就醫日，不符即 `failed`（reason `patient_mismatch`），不寫入。
3. 呼叫 `HISPushAutomator` 寫入 S/O/A/P。
4. **寫後讀回驗證**：讀回 HIS 中的文字，正規化後與 `content_hash` 比對；不一致即 `failed`（reason `readback_mismatch`）。
5. 成功後回報 `success`；伺服器端將草稿狀態改為 `pushed`，並記錄 `pushed_at`、`agent_id`。
6. **冪等**：同一 `case_id` 與 `content_hash` 已 `pushed` 時，新任務直接回 `already_pushed`，不再寫入。
7. STALE_REF 或 UIA 逾時屬系統故障，回報 `failed`（reason `ui_error`），不視為業務結論。
8. 併發固定為 1（單一 Agent 同時只處理一筆）。

## 8.9 寫入範圍（已確認）

- **只寫 S/O/A/P**。
- 診斷碼、醫令、藥令僅作為**建議**顯示於審核畫面，醫師自行決定，**不寫入 HIS**，也不計入 `content_hash`。

## 9. 排程與資源守門

- LLM 預生成（Linux 端）與 HIS 寫入（Windows 端）獨立執行，不互相等待。
- 預生成批次只在本機負載低於門檻時執行（沿用 `pregen_rules_run.py` 的斷路保護）。
- Agent 只在 HIS 前景視窗未被使用者操作時寫入；偵測到使用者操作即暫停並延後。

## 10. 資料與隱私

- 草稿、審核紀錄、寫入結果存於 CaseStore（本機），不離開區網。
- 日誌與審計只記錄：案件 ID、版本、雜湊、決定、狀態、時間、原因代碼。
- SOAP 文字僅出現在草稿資料表與 HIS 寫入 payload，不寫入一般日誌。

## 11. 已確認事項（使用者 2026-11-09 回覆）

1. **標準 SOAP 範本** = 現有 `soap_templates`。
2. **HIS 廠商** 未固定，須現場上線校準（見 §7.4）。
3. **醫師審核** 逐案與批次都要（見 §6 批次核准端點）。
4. **寫入範圍** 目前只寫 S/O/A/P；診斷、醫令、藥令僅建議，不寫入（見 §8.9）。

## 12. 驗收標準

- A1：未經 `approved` 的草稿，不會產生 HIS_PUSH 任務（測試覆蓋）。
- A2：`content_hash` 不符的核准被拒絕（防止審核舊版）。
- A3：寫入後讀回不一致時，任務標為 `failed` 而非 `success`。
- A4：同一 case_id＋content_hash 重送不會重複寫入。
- A5：Agent 離線或伺服器重啟後，任務可被回收並重新認領，不遺失。
- A6：Stage 2 案件狀態不因草稿審核或寫入而改變。
- A7：日誌與審計不含 SOAP 文字與病患識別資訊（測試掃描）。
- A8：既有測試全數通過（不回歸）。

## 13. 任務分解

| 任務 | 內容 | 負責 |
|---|---|---|
| T1 | `soap_drafts` 資料表、狀態機與非法轉換拒絕、content_hash | agy（實作）|
| T2 | 標準範本比對函式（純函式，advisory） | agy |
| T3 | 醫師審核 API（approve／edit／reject）與審計欄位 | agy |
| T4 | approve → 排入 HIS_PUSH（bridge）、冪等檢查 | agy |
| T5 | Agent 心跳端點、Agent 金鑰驗證、離線標記 | agy |
| T6 | `deploy/windows_agent/agent.py`：拉取、寫入、讀回、回報（以 fake automator 測試） | agy |
| T7 | 測試：A1–A7 的負向與邊界案例、競態、PHI 掃描 | hermes（測試）|
| T8 | 檢查與修正：對照 §12 驗收，修正失敗項目 | Claude（檢查與修正）|

## 14. 不在範圍內

- 實機 HIS 寫入的人工驗收（需 Windows 主機與 HIS 環境，留待部署後驗證）。
- 申復與抽審流程的變更。
- 雲端病歷與照片的補強（另案）。
