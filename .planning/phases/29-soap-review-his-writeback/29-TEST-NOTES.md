# Phase 29 測試筆記（TEST-NOTES.md）

日期：2026-11-09  
測試人員：hermes（測試負責）  
依據規範：`.planning/phases/29-soap-review-his-writeback/29-DESIGN.md` §11, §12  

---

## 1. 測試套件架構與涵蓋項目

| 測試檔案 | 測試數量 | 測試目標 | 涵蓋設計規範 |
|---|---|---|---|
| `tests/test_soap_draft_states.py` | 4 項 | 草稿狀態機轉換、非法轉換拒絕、內容雜湊計算、歷程追蹤 | §4 草稿狀態機 (T1) |
| `tests/test_soap_comparison.py` | 4 項 | 標準範本比對純函式（difflib 相似度、缺漏檢測、ICD-10 比對） | §5 標準範本比對 (T2) |
| `tests/test_soap_review_api.py` | 5 項 | 醫師審核 API（逐案/批次 approve, edit, reject）、冪等性、Agent 金鑰權限隔離 | §6, §7.2, §7.3, §8.6 (T3, T4, T5) |
| `tests/test_windows_agent.py` | 8 項 | Windows Agent 主動拉取、CAS 認領、未校準拒絕、病患比對、S/O/A/P 寫入與讀回驗證、PHI 日誌掃描 | §7, §7.4, §8, §8.9 (T6) |
| **合計** | **21 項** | **Phase 29 新增測試全數通過（PASS）** | **A1–A8 全涵蓋** |

---

## 2. §11 已確認事項與最新設計需求驗證結果

### (1) 標準範本來源 = 現有 `soap_templates` 資料表 (§5, §11)
- **測試案例**：`test_soap_draft_template_comparison_from_store`
- **驗證項目**：
  - 由 `CaseStore.put_soap_template` 寫入標準範本（order_code="28016C"）。
  - 呼叫 `POST /api/soap/drafts` 建立草稿，伺服器自動向 `soap_templates` 查詢對應醫令與主診斷之標準範本。
  - 成功產生 `comparison` 物件（`section_similarities`, `icd10_comparison`）。
  - 比對結果僅作為 `advisory_only: True`，絕不自動更改草稿狀態。

### (2) HIS 廠商設定檔現場校準與啟動拒絕 (§7.4)
- **測試案例**：
  - `test_windows_agent_startup_rejects_uncalibrated`：
    - 當 `calibrated=False` 且未顯式設定 `allow_uncalibrated=True` 時，`WindowsAgent.__init__` 立即拋出 `UncalibratedVendorProfileError`，禁止啟動並終止程序。
  - `test_windows_agent_uncalibrated_profile_rejected`：
    - 若測試模式繞過啟動檢查，於執行寫入任務時，仍會被 `execute_job` 攔截，回報 `FAILED` 並帶原因代碼 `uncalibrated_profile`。

### (3) 逐案與批次核准 API (§6)
- **測試案例**：
  - 逐案：`test_soap_draft_full_api_workflow`（`POST /api/soap/drafts/<id>/approve`）。
  - 批次：`test_soap_batch_approve`（`POST /api/soap/batches/<batch_id>/approve`）。
- **驗證項目**：
  - 傳入草稿清單 `items: [{"draft_id": d1, "content_hash": h1}, {"draft_id": d2, "content_hash": "wrong_hash"}]`。
  - d1 雜湊相符：核准並排入 `HIS_PUSH`，狀態轉為 `queued`，回報 `status: "approved"`。
  - d2 雜湊不符（內容已遭變動）：被安全跳過，狀態維持 `validated`，回報 `status: "skipped"`。
  - 批次核准逐案回報每案結果，有效阻絕過期或非預期版本寫入。

### (4) 寫入範圍：只寫 S/O/A/P，不寫診斷/醫令/藥令 (§8.9)
- **測試案例**：`test_windows_agent_writes_only_soap_never_icd10`
- **驗證項目**：
  - 建立帶有 `icd10_code: "K35.80"` 與 `medication: "Amoxicillin..."` 的任務 payload。
  - 調用 `push_case_to_his(..., write_soap_only=True)`。
  - 斷言 UI 驅動層實際寫入之欄位：
    - `@s`、`@o`、`@a`、`@p` 確實寫入正確文字並通過驗證。
    - `@icd`（主診斷碼）或其他醫令欄位**絕未被寫入**（`assert "@icd" not in written_fields`）。

---

## 3. 隱私與 PHI 防護驗證 (§10, A7)

- **日誌無 SOAP 文字**：
  - `test_windows_agent_phi_log_safety`：以 `caplog` 攔截整個 Agent 寫入流程之所有 DEBUG/INFO/WARNING/ERROR 日誌，斷言包含病徵機敏字串的 SOAP 內文絕不出現在日誌。
- **審計端點白名單**：
  - `src/elc_audit_engine/api/routes/soap_review.py` 之 `approve`, `edit`, `reject`, `batch_approve` 均僅呼叫 `audit_log.record_access`，記錄 `action`, `draft_id`, `version`, `reason_code` 等識別碼，嚴禁包含 `_FORBIDDEN_KEYS`（`soap`, `soap_text`, `record_no`, `patient_name`, `id_number`, `birth_date`）。

---

## 4. 迴歸測試結果

於本機執行全部相關歷史測試套件，結果如下：
- `tests/test_bridge_api.py`：20 passed
- `tests/test_agent_desktop_bridge.py`：8 passed
- `tests/test_monthly_pregen_soap.py`：56 passed
- **總計 84 項迴歸測試全數通過（PASS），零回歸**。
