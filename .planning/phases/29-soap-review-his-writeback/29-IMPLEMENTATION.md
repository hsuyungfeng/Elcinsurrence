# Phase 29 實作紀錄：LLM SOAP 草稿 → 標準範本比對 → 醫師審核 → Windows Agent 寫入 HIS

實作日期：2026-11-09  
依據規範：`.planning/phases/29-soap-review-his-writeback/29-DESIGN.md`（含 §11 最新確認事項）  
狀態：實作完成、單元與整合測試全數通過（**遵照指令：不要 commit**）

---

## 1. 最新確認事項調整摘要 (§11)

| # | 最新確認事項 | 實作調整與對應模組 |
|---|---|---|
| 1 | **標準範本來源 = 現有 `soap_templates`** | `soap_review.py` 在建立或編修草稿時，透過 `store.get_soap_template(order_code, primary_diagnosis)` 讀取已存在的通用/特定標準範本比對，比對結果僅供 advisory 參考，不自動改寫草稿狀態。 |
| 2 | **HIS 廠商須現場校準 (§7.4)** | `DEFAULT_HIS_PROFILES` 預設標註 `calibrated: False`；`WindowsAgent` 啟動（`__init__`）時執行 `validate_startup_calibration()`，未經校準之廠商設定檔直接拋出 `UncalibratedVendorProfileError` 拒絕啟動正式寫入。 |
| 3 | **逐案與批次核准端點 (§6)** | 提供 `POST /api/soap/drafts/<id>/approve` 與批次端點 `POST /api/soap/batches/<batch_id>/approve`。批次核准逐案比對傳入各草稿之 `content_hash`，若版本變動則標記 `skipped` 不核准，並回傳每案結果。 |
| 4 | **寫入範圍：只寫 S/O/A/P (§8.9)** | `push_case_to_his` 支援 `write_soap_only=True`，Windows Agent 寫入時僅推送 `soap_s`、`soap_o`、`soap_a`、`soap_p`；診斷碼、醫令、藥令僅作為建議顯示於審核畫面，絕不寫入 HIS。 |

---

## 2. 檔案異動清單

### 2.1 T1: `soap_drafts` 資料表與狀態機 (§4)
- **`src/elc_audit_engine/case_store/soap_draft_states.py`**（新增，95 行）
  - 定義 8 個草稿狀態：`draft`、`validated`、`quality_failed`、`approved`、`queued`、`pushed`、`rejected`、`failed`。
  - 定義 `_DRAFT_TRANSITIONS` 嚴格轉換規則表，未定義的非法轉換拋出 `IllegalDraftTransitionError`。
  - 提供 `canonical_soap_text` 規範化字串與 `compute_soap_content_hash` SHA-256 雜湊計算函式。
- **`src/elc_audit_engine/case_store/db.py`**（修改）
  - 新增 `soap_drafts`、`soap_draft_history`、`agent_heartbeats` 資料表綱要與關聯索引。
- **`src/elc_audit_engine/case_store/store.py`**（修改）
  - 新增 `SoapDraftRecord` dataclass。
  - 新增草稿 CRUD、狀態機推進（`update_soap_draft_state`）、編修版本歷程（`edit_soap_draft`）、冪等檢查（`find_pushed_soap_draft`）與心跳紀錄。
- **`tests/test_soap_draft_states.py`**（新增，4 項測試）
  - 狀態機合法/非法轉換、雜湊計算、資料庫 CRUD 與歷程記錄。

### 2.2 T2: 標準範本比對純函式 (§5)
- **`src/elc_audit_engine/comparator/soap_comparison.py`**（新增，108 行）
  - 純函式 `compare_soap_with_template(draft_soap, template_soap, rule_text)`：
    - 比對 S、O、A、P 相似度（`difflib.SequenceMatcher`）。
    - 檢查缺漏欄位、字數長度統計。
    - 萃取 A 欄之 ICD-10 代碼並與標準範本或法規原文比對一致性。
- **`tests/test_soap_comparison.py`**（新增，4 項測試）
  - 驗證完全相同、相異、缺漏與 ICD-10 一致性比對。

### 2.3 T3 & T4: 醫師審核 API 與 HIS_PUSH 佇列整合 (§6, §8.6)
- **`src/elc_audit_engine/api/routes/soap_review.py`**（新增，420 行）
  - `POST /api/soap/drafts`: 建立草稿，自動自既有 `soap_templates` 比對標準範本。
  - `GET /api/soap/drafts/<draft_id>`: 讀取草稿、版本、品質分數與比對摘要。
  - `POST /api/soap/drafts/<draft_id>/approve`: 逐案核准目前版本，核對 `content_hash`，冪等檢查通過後排入 `HIS_PUSH`。
  - `POST /api/soap/batches/<batch_id>/approve`: 批次核准端點，逐案以各自 `content_hash` 核准，已變動者標記 `skipped`。
  - `POST /api/soap/drafts/<draft_id>/edit`: 醫師修改 S/O/A/P，版本號遞增。
  - `POST /api/soap/drafts/<draft_id>/reject`: 醫師退回草稿（記錄原因代碼）。
  - **嚴格無 PHI 審計**：所有審計一律呼叫 `audit_log.record_access`，不記錄 SOAP 內文與病患識別資料。
- **`src/elc_audit_engine/api/routes/bridge.py`**（修改）
  - 掛載 `HIS_PUSH` 任務狀態回報 hook：Agent 回報 `SUCCESS` 自動推進草稿至 `pushed`，回報 `FAILED` 轉為 `failed`。

### 2.4 T5: Agent 心跳端點與 Agent 金鑰權限隔離 (§7.2, §7.3)
- **`src/elc_audit_engine/auth.py`**（修改）
  - 支援 `ELC_AGENT_KEYS` 環境變數。
- **`src/elc_audit_engine/api/security.py`**（修改）
  - 實作 Agent 金鑰端點白名單限制（`AGENT_ALLOWED_ENDPOINTS`），禁止存取非授權之業務端點（403 Forbidden）。
- **`src/elc_audit_engine/api/routes/agent_bridge.py`**（新增，45 行）
  - `POST /api/agent/heartbeat` 與 `GET /api/agent/status`。
- **`tests/test_soap_review_api.py`**（新增，5 項測試）
  - 逐案工作流程、退回與終態限制、Agent 金鑰權限隔離、批次核准、標準範本比對整合測試。

### 2.5 T6: Windows Agent 常駐程式與寫入流程 (§7, §8, §8.9)
- **`src/elc_audit_engine/agent_desktop_bridge.py`**（修改）
  - `DEFAULT_HIS_PROFILES`：加入 `calibrated: False`、`calibrated_at: None`、`calibrated_by: None` 骨架設定。
  - `push_case_to_his`：支援 `write_soap_only: bool = True`，貫徹 §8.9 只寫 S/O/A/P。
- **`deploy/windows_agent/agent.py`**（新增，265 行）
  - 實作 `WindowsAgent` 客戶端：
    - Python 內建 `urllib` 輕量實作，無額外依賴。
    - **啟動檢查**：`validate_startup_calibration` 確保未校準廠商設定檔不得啟動。
    - **主動拉取**：`GET /api/bridge/jobs/pending?sTypeCode=HIS_PUSH` 與 CAS 認領。
    - **病患比對**：比對目前前景病歷 `case_id`，不符回報 `patient_mismatch`。
    - **寫入執行**：調用 `push_case_to_his(write_soap_only=True)`。
    - **讀回驗證**：讀回 S/O/A/P 計算雜湊並與 `content_hash` 比對，不一致回報 `readback_mismatch`。
    - **日誌安全**：全面保護，不印出 SOAP 內文。
- **`tests/test_windows_agent.py`**（新增，8 項測試）
  - 完整成功流程、啟動拒絕未校準、執行階段攔截未校準、病患不符、讀回不一致、UI 異常重試、只寫 S/O/A/P 斷言、PHI 日誌安全性測試。

---

## 3. 測試總結

- **新增測試**：21 passed（100% 通過）
- **迴歸測試**：84 passed（100% 通過）
- **詳細測試紀錄**：請參閱同目錄之 [`29-TEST-NOTES.md`](./29-TEST-NOTES.md)。

---

## 4. 未完成事項（留待實機環境部署）

依 `29-DESIGN.md §7.4` 與 `§14`：
1. **實機現場校準**：初版之 vision、yaosheng、minger、chihshi 廠商設定檔為未校準骨架，診所實體主機上線前須由工程師以測試病歷完成現場校準，並設定 `calibrated: True`。
2. **Windows 服務安裝排程**：建立 Windows 工作排程器或 NSSM 腳本，設定開機自動在背景啟動 `agent.py`。
3. **前端審核 UI 串接**： Stage 2 審核介面串接批次核准與逐案審核 API。
