# Plan 31-10 Summary: 循環草稿送出、檢索隔離與通用審核保護 (Task 1 & Task 2)

## 成果摘要
- **模組交付**：
  1. `src/elc_audit_engine/cycles/drafts.py`：
     - `submit_cycle_draft`：需 `upload_complete=1`，以 `session_id` 冪等，保存逐字稿至 `DATA_DIR/cycles/{cycle_id}/transcript.txt`，extras 儲存中文對話摘要、過去病史與建議項。
     - **不觸發自動接入（D-31-08）**：循環草稿一律須由醫師在快捷列確認視窗確認。
     - `cycle_draft_view`：結構化草稿檢視，建議項標記 `read_only=True`，支援 `include_transcript=1` 參數。
     - `cycle_bound_draft_ids` 與 `is_cycle_bound`：快速判定草稿是否為循環綁定。
     - `extract_advisory`：共用建議項萃取邏輯。
  2. `src/elc_audit_engine/api/routes/soap_review_queue.py`：
     - **全域審核佇列隔離（D-31-39）**：`list_pending_review` 排除所有已綁定循環之草稿，避免不同診間醫師誤審。
  3. `src/elc_audit_engine/api/routes/soap_review.py`：
     - **通用審核端點保護（D-31-16）**：`approve_draft` 與 `edit_draft` 對已綁定循環之草稿回傳 409（提示使用快捷列確認視窗）；`approve_batch` 自動跳過已綁定草稿。
  4. `src/elc_audit_engine/api/routes/cycles.py`：
     - `POST /api/cycles/<cycle_id>/draft`：接收草稿送出。
     - `GET /api/cycles/<cycle_id>/draft`：取得草稿結構化檢視。
  5. 測試套件：
     - `tests/test_cycle_isolation.py`：TDD 先紅後綠，驗證 pending-review 排除、通用端點 409 阻絕、雙機草稿隔離。
     - `tests/test_cycle_drafts.py`：涵蓋未完成上傳阻絕、冪等重送、品質未達 unusable、邊界長度驗證、認證阻絕、審計日誌無洩漏等 9 項行為。
- **測試結果**：
  - `test_cycle_isolation.py` + `test_cycle_drafts.py` 12 passed。
  - 回歸測試套件 134 passed (2.18s)。

## 偏離與路徑對應
- 無偏離。本計畫全數於 `Elcinsurrence` 倉庫實作，無 git commit。
