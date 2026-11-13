# Plan 31-05 Summary: Server 循環狀態機、資料表與 cycles 核心端點 (D-31-05, D-31-16, D-31-12, D-31-29)

**完成時間**：2026-11-12
**執行狀態**：完成 (Task 1 & Task 2 All Passed)

## 變更項目

1. **`src/elc_audit_engine/case_store/db.py`**：
   - 新增 5 張資料表與索引：`recording_cycles`（含 `machine_id` 部分唯一索引）、`cycle_events`、`cycle_chunks`、`cycle_confirmations`、`client_presence`。
2. **`src/elc_audit_engine/cycles/states.py`**：
   - 定義 9 個循環狀態常數、`ALL_CYCLE_STATES`、`TERMINAL_STATES`、`ACTIVE_STATES`。
   - 實作純函式 `assert_cycle_transition` 嚴格遵循契約 §4 轉換表。
   - 實作 `display_state` 計算 5 種中文監控顯示狀態（離線優先、錄音中、待確認、已封存、待命）。
3. **`src/elc_audit_engine/cycles/store.py`**：
   - 提供 `create_cycle`（command_id 冪等、同機活躍循環衝突拋 `ActiveCycleExistsError`）、`get_cycle`、`get_active_cycle`、`get_last_cycle`、`transition_cycle`、`cycle_view`、`cycle_dir`。
   - 嚴格遵守 D-31-29，程式碼內不含任何刪除檔案的操作。
4. **`src/elc_audit_engine/api/routes/cycles.py`**：
   - 實作 `POST /api/cycles`、`GET /api/cycles`（machine_id 查詢）、`GET /api/cycles/<cycle_id>`、`POST /api/cycles/<cycle_id>/stop`、`POST /api/cycles/<cycle_id>/abandon`。
   - 欄位格式嚴格校驗（拒絕而非清洗，回傳 422）；Agent 金鑰 403 阻絕；每次轉換寫入 `cycle_events` 與審計紀錄（無 PHI）。
5. **`src/elc_audit_engine/api/routes/cycle_chunks.py` & `clients.py`**：
   - 建立並註冊 Blueprint 骨架至 `routes/__init__.py`。
6. **測試套件**：
   - `tests/test_cycle_state_machine.py`: 4 passed
   - `tests/test_cycles_api.py`: 8 passed

## 驗證結果
- `tests/test_cycles_api.py tests/test_cycle_state_machine.py`: **12 passed in 0.50s**
- Phase 31 累積測試: **31 passed in 0.90s**
- 未提交任何 git commit。
