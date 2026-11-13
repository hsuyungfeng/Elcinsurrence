# Plan 31-14 Summary: 循環確認存檔與黃燈封存 (Wave 4)

## 成果摘要
- **模組交付**：
  1. `src/elc_audit_engine/cycles/archive.py`：
     - `confirm_cycle`：
       - 驗證 `content_hash`，支援 `AWAITING_CONFIRM`、`DRAFT_UNUSABLE`、`CONFIRMED`。
       - 存入 `cycle_confirmations` 表（完整儲存 S/O/A/P、中文摘要、過去病史、建議項、版本、hash、reviewer_id、confirmed_at）。
       - 支援醫師在確認視窗修改 SOAP 內文（品質重檢），合格則建立新草稿遞增版本並更新綁定；不合格則轉 `DRAFT_UNUSABLE` 並回傳 422 附品質檢核問題。
       - 呼叫 `approve_and_enqueue(machine_id=cycle["machine_id"])`，排入綁定該工作站的 `HIS_PUSH` 任務（HIS 任務 payload 僅含 s, o, a, p，絕不包含中文摘要或病史，D-31-26）。
       - 推進循環狀態至 `CONFIRMED`。
       - 記錄審計日誌 `cycle_confirm`（零 PHI，僅含 action, cycle_id, draft_id, content_hash）。
     - `archive_cycle`：
       - 黃燈封存前置檢查：未確認前封存回 409 `not_confirmed`（D-31-08）；確認版快照遺失回 409 `confirmation_missing`。
       - 草稿狀態判定：
         - `pushed`：CAS 推進循環至 `ARCHIVED`（填入 `archived_at`），記錄審計日誌 `cycle_archive`，回傳 200 `archived`；已封存者回傳 200 `already_archived`（冪等）。
         - `approved` 或 `queued`：自動恢復卡住的 approved 任務，狀態轉為 `ARCHIVING`，回傳 202 `his_pending`。
         - `failed`：若循環已為 `ARCHIVE_FAILED`，則重試排入新 `HIS_PUSH` 任務並轉 `ARCHIVING` 回傳 202 `his_retry_queued`（確認版不重寫）；若為首次失敗則轉 `ARCHIVE_FAILED` 回傳 409 `his_failed`（附帶 failure_reason）。
       - 併發雙擊防護：在單一交易內 CAS，保證恰一次狀態轉換與恰一筆審計。
       - 封存後同一 `machine_id` 解除索引約束，可立即建立新循環。
       - 封存不刪除 `DATA_DIR/cycles/{id}/` 之錄音檔案（D-31-29）。
  2. `src/elc_audit_engine/api/routes/cycles.py`：
     - 新增 `POST /api/cycles/<cycle_id>/confirm`
     - 新增 `POST /api/cycles/<cycle_id>/archive`
  3. `src/elc_audit_engine/api/errors.py`：
     - `ApiError` 支援 `extra` 字典，供 422 錯誤傳遞結構化欄位（如 `quality_issues`）。
  4. `src/elc_audit_engine/cycles/store.py`：
     - `cycle_view` 新增 `archived_at` 欄位。
  5. 測試套件：
     - `tests/test_cycle_confirm.py`（10 項測試）
     - `tests/test_cycle_archive.py`（9 項測試）
- **測試結果**：
  - `tests/test_cycle_confirm.py` + `tests/test_cycle_archive.py`：19 passed。
  - 迴歸測試（78 passed）：全數通過無回歸。
  - 快捷列與 Agent 測試（28 passed）：全數通過。

## 偏離與修正
1. `validate_soap_quality` 匯入路徑修正為 `from elc_audit_engine.comparator.soap_advice import validate_soap_quality`。
2. `ApiError` 增加 `extra: dict | None = None` 參數，以便在 422 品質未過時將 `quality_issues` 傳回客戶端。
3. `tests/phase31_support.py` 補足 `config["AUDIT_LOG_PATH"]`，使測試環境審計日誌讀取正常。
4. `tests/test_cycle_archive.py` 測試替身對齊 bridge API 協定（使用 `GET /api/bridge/jobs/pending` 認領並以 `SENDING` -> `SUCCESS`/`FAILED` 回報）。
5. 無 git commit，無 push。
