# Plan 31-02 Summary: 核准流程崩潰窗口收斂與可恢復核准核心 (D-31-38, D-31-07)

**完成時間**：2026-11-12
**執行狀態**：完成 (RED → GREEN TDD 流程)

## 變更項目

1. **`src/elc_audit_engine/case_store/db.py`**：
   - `SCHEMA_SOAP_DRAFTS` 新增 `his_job_id TEXT` 與 `his_machine_id TEXT` 欄位定義。
   - `init_schema` 內加入以 `PRAGMA table_info` 判斷的冪等遷移，對舊資料庫自動以 `ALTER TABLE ADD COLUMN` 補上欄位。
2. **`src/elc_audit_engine/case_store/store.py`**：
   - `SoapDraftRecord` 與 `_row_to_soap_draft_record` 加入 `his_job_id`、`his_machine_id` 讀取支援。
   - `update_soap_draft_state` 支援在同一交易內寫入 `his_job_id` 與 `his_machine_id`。
   - 新增 `set_soap_draft_his_job(draft_id, his_job_id, his_machine_id)` 方法，供舊草稿卡在 approved 時補填固定任務 ID。
3. **`src/elc_audit_engine/bridge_queue.py`**：
   - `enqueue_job` 支援自訂 `job_id` 參數（驗證 32 位小寫 hex），避免重複產生。
   - 新增 `ensure_job(store, *, job_id, s_type_code, target_id, actor, extra_payload)`，捕捉 `DuplicateCaseError` 達到任務建立冪等性。
4. **`src/elc_audit_engine/api/routes/soap_review.py`**：
   - 抽出 `approve_and_enqueue(store, *, draft_id, reviewer_id, machine_id)` 核心函式，支援 `validated`、`failed` 與 `approved` 狀態之推進與收斂。
   - `_approve_draft_record` 與 `approve_batch` 一致改用 `approve_and_enqueue`。
   - 新增 `recover_stuck_approved(store, limit=50)` 掃描函式。
5. **`tests/test_approve_crash_window.py`**：
   - 包含 6 項崩潰與遷移測試（核准崩潰重試、佇列崩潰重試、掃描修復、失敗重試新任務、批次核准崩潰恢復、舊 DB 自動相容）。

## 驗證結果
- **RED 階段**：未修改前測試因 409、找不到 `recover_stuck_approved` 等原因 5 failed, 1 passed。
- **GREEN 階段**：
  - `tests/test_approve_crash_window.py`: **6 passed in 0.44s**
  - 既有回歸測試套件（`test_phase29_soap_review_api.py`、`test_soap_review_api.py`、`test_bridge_api.py`、`test_bridge_queue_reliability.py`）: **135 passed in 3.64s**
- 未提交任何 git commit。
