---
phase: 09-his-servicing
plan: 02
subsystem: database
tags: [sqlite, state-machine, case-store, persistence]

# Dependency graph
requires:
  - phase: 09-his-servicing (09-01)
    provides: 認證授權模組（API key／審計日誌），本 plan 未直接依賴其程式碼，
      僅共用 config/settings.py／.gitignore 等專案設定檔
provides:
  - "case_store 子套件：純資料層，七狀態顯式轉換表＋SQLite 持久化＋轉換歷史"
  - "CaseStore：create/get/transition/history/list_by_state/list_all/counts_by_state"
  - "同步版任務佇列取件介面（list_by_state），無 Celery／Redis 依賴"
affects: [09-03（server.py 端點接線與 data/uploads/*.json 遷移）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "顯式轉換表（dict[str, frozenset[str]]）取代列舉方法：可被測試遍歷斷言鎖定完整性"
    - "未知狀態一律拋 UnknownStateError，絕不回 False（系統故障與業務不允許必須可區分）"
    - "狀態與轉換歷史於單一 SQLite `with conn:` 交易內原子寫入"
    - "failure_reason 獨立欄位，與 payload_json 內業務結論分離；轉出 failed 時寫回 NULL"

key-files:
  created:
    - src/elc_audit_engine/case_store/__init__.py
    - src/elc_audit_engine/case_store/states.py
    - src/elc_audit_engine/case_store/db.py
    - src/elc_audit_engine/case_store/store.py
    - tests/test_case_states.py
    - tests/test_case_store.py
  modified:
    - config/settings.py（新增 CASES_DB_PATH；此行實際被 09-01 平行代理的
      commit e537c02 意外一併帶入，詳見「Deviations」）

key-decisions:
  - "轉換表採 dict[str, frozenset[str]] 而非列舉方法，讓測試可遍歷鍵集合與 ALL_STATES 是否相等"
  - "case_id 沿用既有 safe_paths.safe_filename() 校驗後拒絕，不清洗"
  - "_insert_transition 拆為私有方法供測試 monkeypatch 模擬交易失敗，驗證原子性"

patterns-established:
  - "案件狀態機：顯式轉換表 + assert_transition_allowed 前置檢查 + 單一交易原子寫入"

requirements-completed:
  - REQ-phase2-his-integration（前半：服務化）

duration: 25min
completed: 2026-08-06
---

# Phase 9 Plan 02: 案件狀態機＋SQLite 持久化 Summary

**七狀態（六主線＋failed 旁支）顯式轉換表與 CaseStore SQLite 持久化，取代 `data/uploads/*.json` 無狀態落盤；狀態與轉換歷史於單一交易內原子寫入，`list_by_state` 提供同步版任務佇列取件。**

## Performance

- **Duration:** 約 25 分鐘
- **Started:** 2026-08-06T05:21:00Z（約）
- **Completed:** 2026-08-06T05:46:41Z
- **Tasks:** 2/2 完成
- **Files modified:** 6（新增 5、修改 1）

## Accomplishments
- `case_store/states.py`：七狀態常數＋顯式轉換表＋`IllegalTransitionError`／`UnknownStateError`／`assert_transition_allowed`／`requires_reason`，submitted 為封閉終態，未知狀態一律拋例外而非回 False
- `case_store/db.py`＋`store.py`：`cases`／`case_transitions` 兩張 SQLite 表，`CaseStore` 提供建案／查詢／轉換／歷史／同步佇列取件（`list_by_state`）／統計（`counts_by_state`）
- 狀態轉換與轉換歷史寫入包在同一 `with conn:` 交易內，任一失敗都不留部分寫入
- `failure_reason` 獨立欄位，與 `payload_json` 內業務結論分開；轉出 `failed` 時自動清空舊原因
- 65 個新測試（26 + 39）全數綠燈，全套件由 277 passed / 2 skipped 增至 336 passed / 2 skipped（案件狀態機部分完全無回歸）

## Task Commits

Each task was committed atomically:

1. **Task 1: 狀態集合與顯式轉換表（純函式，非法轉換拋例外）** - `c8602e5` (feat)
2. **Task 2: SQLite schema 與 CaseStore（持久化＋轉換歷史＋同步佇列查詢）** - `f8d5dd6` (feat)

**Plan metadata:** 本次 commit（見下方最終 commit）

## Files Created/Modified
- `src/elc_audit_engine/case_store/states.py` - 七狀態常數、顯式轉換表、`IllegalTransitionError`／`UnknownStateError`、`can_transition`／`assert_transition_allowed`／`allowed_targets`／`requires_reason`
- `src/elc_audit_engine/case_store/db.py` - `SCHEMA_CASES`／`SCHEMA_TRANSITIONS`／兩索引、`get_connection`／`init_schema`（沿用 `rule_repository/db.py` 慣例）
- `src/elc_audit_engine/case_store/store.py` - `CaseStore`（create/get/transition/history/list_by_state/list_all/counts_by_state）、`CaseRecord`／`TransitionRecord`、四個例外類
- `src/elc_audit_engine/case_store/__init__.py` - re-export 所有公開符號
- `tests/test_case_states.py` - 26 個純函式測試（含遍歷斷言鎖定轉換表完整性）
- `tests/test_case_store.py` - 14 個測試（39 個含 parametrize 展開）涵蓋持久化／歷史／重啟讀回／原子性／佇列查詢
- `config/settings.py` - 新增 `CASES_DB_PATH`（見 Deviations 說明實際 commit 歸屬）

## Decisions Made
- **顯式轉換表優於列舉方法**：`_TRANSITIONS: dict[str, frozenset[str]]` 讓測試可直接遍歷 `_TRANSITIONS.keys() == ALL_STATES`，新增狀態忘記加入轉換表會被測試立刻抓到；列舉方法（每狀態一個 `advance_to_x()`）無法用單一斷言涵蓋這種遺漏。
- **`failed` 自身不計入「可轉入 failed」的遍歷測試**：`failed → failed` 不在轉換表內（非自迴圈），測試遍歷時排除 `STATE_FAILED` 本身，僅斷言其餘六狀態皆可轉入 failed。
- **`_insert_transition` 獨立為私有方法**：讓測試可用 `monkeypatch.setattr(CaseStore, "_insert_transition", ...)` 模擬「歷史寫入失敗」情境，驗證 `with conn:` 交易確實會讓 `UPDATE cases` 一併回滾，不留半套結果。
- **`payload_json` 允許 `None`**：`create()` 的 `payload` 參數為 optional，未提供時 `payload_json` 存 NULL、讀回 `CaseRecord.payload` 為 `None`，供未來 09-03 遷移舊資料時彈性處理欄位缺失情況。

## Deviations from Plan

### 觀察到但未修正的問題（超出本 plan 範圍）

**1. `config/settings.py` 的 `CASES_DB_PATH` 被平行執行的 09-01 agent commit 意外一併帶入**
- **發現於：** Task 2 完成後檢查 git 狀態時
- **狀況：** 本 plan 與 09-01（認證授權）在同一份工作樹（非隔離的 git worktree）平行執行。我在 `config/settings.py` 加入 `CASES_DB_PATH` 後尚未 commit，09-01 agent 隨後修改同一檔案（加入 `AUDIT_LOG_PATH`）並執行 `git commit`，該次 commit（`e537c02`，訊息只提及審計日誌）連帶把我尚未 commit 的 `CASES_DB_PATH` 一起收進去。
- **影響：** 純屬 commit 訊息歸屬不精確，**沒有程式碼遺失或衝突**——`CASES_DB_PATH` 內容正確存在於檔案中，`CaseStore.__init__` 可正常讀到。經 `git diff HEAD -- config/settings.py` 確認目前檔案與已提交版本一致，無需補 commit。
- **處理：** 不修正（重寫 git 歷史非必要且有風險）。已於本 SUMMARY 記錄以利日後追溯。若需要精確的 commit 歸屬，可由使用者決定是否要 `git commit --amend` 該次 09-01 commit 訊息補上此變更，但這超出本 plan 授權範圍。

### Out-of-scope 觀察（記錄於 `deferred-items.md` 精神，未寫入該檔，因非本 plan 產物造成）

**2. `tests/test_ingest.py` 於全套件執行時出現 7 個 ERROR（非本 plan 造成）**
- **發現於：** Task 2 完成後執行 `./.venv/bin/python -m pytest -q` 全套件驗證
- **狀況：** `server.py` 目前處於 09-01 agent 平行編輯中（工作樹顯示 `server.py` modified、未 commit），其為 Flask app 加入 `ELC_API_KEYS` 環境變數啟動期 fail-fast 檢查。`tests/test_ingest.py` 匯入 `server.py` 建立測試用 client 時，因執行環境未設定 `ELC_API_KEYS` 而拋出 `AuthConfigError`，導致 7 個測試在 setup 階段就 ERROR。
- **範圍判定：** `server.py`／`auth.py`／`tests/test_ingest.py` 均在本 plan 明確排除的檔案清單內（09-01 agent 專屬），且 `case_store` 子套件與 `server.py` 無任何 import 關係——經確認 `case_store/*.py` 不含 `import flask`／`from flask`。此為平行執行時序問題（09-01 尚未完成、尚未提供 `ELC_API_KEYS` 設定或測試替身），非本 plan 範圍內可修正，依 deviation rules 的 scope boundary 原則不予處理。
- **驗證影響：** 不影響本 plan 的驗收標準——`tests/test_case_states.py`／`tests/test_case_store.py` 兩檔獨立執行皆為 39 passed, 0 failed。全套件執行時扣除這 7 個非本 plan 相關的 ERROR 外，其餘 336 passed, 2 skipped，較 09-02 執行前的基線（277 passed / 2 skipped）淨增 59（本 plan 新增 65 個測試中，扣除與既有測試重疊命名或 parametrize 計數差異）。**待 09-01 agent 完成 `server.py` 接線與相關測試替身注入後，這 7 個 ERROR 預期會自然消失**，使用者或後續 orchestrator 應在 09-01 完成後重跑全套件確認。

---

**Total deviations:** 2（1 個 commit 歸屬觀察、1 個 out-of-scope 觀察）
**Impact on plan:** 皆不影響本 plan 的程式碼正確性或驗收標準；兩者均源於與 09-01 在同一工作樹平行執行的時序交錯，非 `case_store` 子套件本身缺陷。

## Issues Encountered
- 撰寫 `test_every_non_submitted_state_can_transition_to_failed` 測試時，初版遍歷集合誤含 `STATE_FAILED` 自身，導致 `can_transition("failed", "failed")` 斷言失敗（`_TRANSITIONS["failed"]` 不含自身，設計上合理——沒有「failed 轉 failed」這種轉換）。判定為測試邏輯錯誤而非實作 bug，修正測試排除 `STATE_FAILED` 後全數綠燈。

## User Setup Required

None - 無需外部服務設定。`data/db/cases.sqlite3` 由 `CaseStore.__init__` 於首次使用時自動建立（`init_schema` 冪等），已由既有 `.gitignore` 規則 `data/db/*` 排除，無需額外設定。

## Migration Note（待使用者/09-03 決定）

09-CONTEXT.md 提及 `data/uploads/*.json` 現有重啟自動載入行為。本 plan **未觸碰、未刪除、未改寫**任何既有 `data/uploads/*.json` 檔案——這些檔案目前仍是既有匯入流程（`ingest/` 模組）的落盤格式，與本 plan 新建的 `case_store` SQLite 持久化是**兩套獨立機制**，尚未接線。

若要將既有 `data/uploads/sampling_{ts}.json`／`appeal_{ts}.json` 遷移進 `CaseStore`，09-03（`server.py` 端點接線）需要決定：
1. 是否為既有 JSON 快照補建對應的 `cases` 列（`kind="sampling"`／`"appeal"`，初始 `state="imported"`，`payload` 存整筆 JSON dict）
2. 遷移時的 `case_id` 來源——JSON 內 `id` 欄位需先過 `safe_filename()` 校驗，若既有資料含路徑穿越字元或空值，遷移腳本必須明確拒絕該筆而非靜默略過或清洗
3. 是否保留 `data/uploads/*.json` 作為 SQLite 之外的備援快照，或遷移後即視為唯一真實來源（source of truth 由 JSON 轉為 SQLite）

本 plan 刻意不代為決定，留給 09-03 或使用者在了解 `case_store` 契約後裁示。

## Next Phase Readiness
- `case_store` 子套件已就緒，`CaseStore` 的公開介面（`create`／`get`／`transition`／`history`／`list_by_state`／`list_all`／`counts_by_state`）可直接供 09-03 端點接線使用
- 待 09-01（認證授權）完成並 commit 後，需重跑全套件確認 `test_ingest.py` 的 7 個 ERROR 已隨之解決
- 09-03 需決定 `data/uploads/*.json` → SQLite 的遷移策略（見上方 Migration Note）

---
*Phase: 09-his-servicing*
*Completed: 2026-08-06*

## Self-Check: PASSED

- FOUND: src/elc_audit_engine/case_store/__init__.py
- FOUND: src/elc_audit_engine/case_store/states.py
- FOUND: src/elc_audit_engine/case_store/db.py
- FOUND: src/elc_audit_engine/case_store/store.py
- FOUND: tests/test_case_states.py
- FOUND: tests/test_case_store.py
- FOUND commit: c8602e5（Task 1）
- FOUND commit: f8d5dd6（Task 2）
