# Plan 31-04 Summary: HIS_PUSH 任務 machine_id 綁定與跨機隔離 (D-31-37, D-31-16, D-31-14)

**完成時間**：2026-11-12
**執行狀態**：完成 (RED → GREEN TDD 流程)

## 變更項目

1. **`src/elc_audit_engine/case_store/store.py`**：
   - `list_bridge_jobs` 支援 `machine_id` 篩選參數，以 `_UNSET_MACHINE` 哨兵區分「不篩選」（預設相容）、「未綁定（IS NULL）」與「指定機器＋未綁定（IS NULL OR = ?）」。
2. **`src/elc_audit_engine/bridge_queue.py`**：
   - `list_pending` 支援 `machine_id` 參數並透傳至 `store.list_bridge_jobs`。
   - `report_status` 比對任務 `extra_payload.machine_id`，若不符則拋出 `BridgeConflictError`（409）。
3. **`src/elc_audit_engine/api/routes/bridge.py`**：
   - `list_pending_jobs` 讀取 query `machine_id`，對 `HIS_PUSH` 代碼實施「指定機器＋未綁定」過濾；未帶者僅回傳未綁定任務。
   - `report_bridge_job_status` 在草稿狀態同步前嚴格檢查 `machine_id`，跨機認領/回報立即阻斷並回 409。
4. **`src/elc_audit_engine/api/routes/soap_review.py`**：
   - `approve_draft` 接收可選 `machine_id` 並校驗格式，透傳給 `approve_and_enqueue`。
5. **`deploy/windows_agent/agent.py`**：
   - `poll_pending_jobs` 在設有 `machine_id` 時帶入 query 參數。
   - `claim_job` 與 `report_job_status` 於請求 body 帶入 `machine_id`。
6. **`deploy/windows_agent/review_client.py`**：
   - `ReviewClient` 建構支援可選 `machine_id`，`approve` 請求 body 自動帶入 `machine_id`。
7. **`tests/test_bridge_agent_affinity.py`**：
   - 8 項單元與整合測試（輪詢過濾、未綁定隔離、跨機阻斷 409、SUCCESS 標記 pushed、WindowsAgent 帶 machine_id、ReviewClient 帶 machine_id、未校正防護）。

## 測試驗證
- **RED 階段**：修正前 6 failed，2 passed（確認跨機任務混雜、跨機可認領等缺陷）。
- **GREEN 階段**：
  - `tests/test_bridge_agent_affinity.py`: **8 passed in 0.42s**
  - 回歸整合測試套件（`test_bridge_api.py`、`test_bridge_queue_reliability.py`、`test_windows_agent.py`、`test_agent_entrypoint.py`、`test_approve_crash_window.py`）: **91 passed in 2.99s**
- 未提交任何 git commit。
