---
phase: 11-paper-appeal-print
plan: 03
subsystem: generators（輸出通道）＋ config（院所層設定）＋ scripts（CLI 入口）
tags: appeal-print, facility-config, cli, pdf, soffice, pypdf, safe-filename

# Dependency graph
requires:
  - phase: 11-paper-appeal-print
    provides: 11-02 產出之 render_appeal_print／write_appeal_print（回傳 (pdf_path, warnings)）與壓縮基準模板 *_print_base.odt（+sha256）
provides:
  - config/facility.json（院所層欄位，D-04）
  - settings.FACILITY_CONFIG_PATH（env 可覆寫）＋ load_facility_config()（缺檔 FileNotFoundError／缺必填欄 ValueError，fail-fast）
  - scripts/build_appeal_print.py CLI（appeal JSON ＋ 可選 case payload → 一案一 PDF，不觸 server.py）
  - README「紙本申復清單列印」使用說明章節
affects: [Phase 12＋（列印通道後續）、HIS 對接文件、操作手冊]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "config fail-fast 載入：FACILITY_CONFIG_PATH env 覆寫 ＋ load_facility_config() 缺檔/缺必填欄立刻拋錯（比照 load_llama_config）"
    - "CLI 逐行模式：argv 校驗 → 錯誤分層 return 1 → safe_filename 校驗後拒絕 → 成功後 warnings 以「警告：」列印"
    - "直接執行腳本之 sys.path 自癒：scripts/ 下腳本自行插入專案根（config 為根層級模組）"

key-files:
  created:
    - config/facility.json
    - scripts/build_appeal_print.py
  modified:
    - config/settings.py
    - tests/test_appeal_print.py
    - README.md
    - .planning/phases/11-paper-appeal-print/deferred-items.md

key-decisions:
  - "facility.json 單一院所物件（code/name 必填、address/physician_name 選填），值為測試用示例；FACILITY_CONFIG_PATH 比照 LLAMA_CONFIG_PATH 以 env 覆寫路徑（RESEARCH Q7 定案落地）"
  - "CLI 位置參數 1~3 個：長度 2 時第 2 個為 output_pdf_path（後向兼容 build_appeal_xml 習慣）、長度 3 時第 2 個為 case_payload_json_path、第 3 個為 output_pdf_path"
  - "warnings 呈現採 monkeypatch 隔離 write_appeal_print（fake_write 回傳 (fake.pdf, warnings)），soffice 缺席時照常驗證缺欄列印邏輯"

patterns-established:
  - "Pattern: scripts/ 下 CLI 需在 import config 前自行把專案根插入 sys.path（`python scripts/x.py` 時 sys.path[0]＝scripts/）"
  - "Pattern: CLI 成功輸出後先印「已成功輸出…」再逐條印「警告：{欄位名}」（T-11-03 只印欄位名不印值）"

requirements-completed: [REQ-paper-appeal-print]

# Metrics
duration: 60min
completed: 2026-08-08
---

# Phase 11 Plan 03: 紙本申復清單列印 CLI 與院所設定 Summary

**facility.json 院所層設定（D-04，fail-fast）＋ `scripts/build_appeal_print.py` CLI（appeal JSON→一案一 PDF，缺欄「警告：」誠實列印）＋ README 使用說明，收束紙本申復清單輸出通道**

## Performance

- **Duration:** 60 min
- **Started:** 2026-08-08T03:03:00Z（約）
- **Completed:** 2026-08-08T04:03:04Z
- **Tasks:** 3
- **Files modified:** 7（含 deferred-items.md）

## Accomplishments

- `config/facility.json`（D-04）＋ `settings.FACILITY_CONFIG_PATH`（env 可覆寫）＋ `load_facility_config()`：缺檔 `FileNotFoundError`、缺必填欄（code/name）`ValueError`、壞 JSON `ValueError`——fail-fast，不靜默空值（比照 `load_llama_config` 哲學）。
- `scripts/build_appeal_print.py` CLI：1~3 位置參數（長度 2 第 2 個＝輸出 PDF 路徑、長度 3 第 2 個＝case payload）、錯誤分層 return 1 不噴 traceback、stem 經 `safe_filename` 校驗後拒絕（`../` 拒且外部目錄未寫入，T-11-04）、缺欄 warnings 於成功訊息後逐條以「警告：」列印（T-11-03 只印欄位名）、不觸 server.py、模板 sha256 校驗由 write_appeal_print 內建（T-11-06）。
- README「紙本申復清單列印（Phase 11）」章節：用途／前置條件（soffice、facility.json、FACILITY_CONFIG_PATH）／三種指令範例／行為說明（三聯一次列印、>15 行分頁、缺欄留空不捏造、第二聯核定欄留空）／PHI 注意（P0-3）。
- 全套件回歸：沙箱環境 406 passed + 2 skipped + 2 環境性 failed（詳見 Deviations）；`tests/test_appeal_print.py` 34 個全組測試綠（mapping/odt/base/e2e/security/copies/config/cli），soffice 於沙箱可用故 e2e/CLI 完整流程實跑通過。

## Task Commits

> 註記：本執行沙箱 `.git` 為唯讀（git add/commit 會失敗），commit 由 orchestrator 依下述建議訊息建立（每個任務一筆，TDD 任務拆 test/feat）。

1. **Task 1: config/facility.json＋settings.py load_facility_config（D-04，fail-fast）**
   - 建議 commit（RED）：`test(11-03): add failing -k config tests for load_facility_config`
   - 建議 commit（GREEN）：`feat(11-03): add FACILITY_CONFIG_PATH/load_facility_config + config/facility.json`
2. **Task 2: scripts/build_appeal_print.py CLI 入口＋CLI 端到端測試**
   - 建議 commit：`feat(11-03): add build_appeal_print.py CLI with warnings presentation + -k cli tests`
3. **Task 3: README 使用說明＋全套件回歸驗證**
   - 建議 commit：`docs(11-03): add paper appeal print usage section to README`

## Files Created/Modified

- `config/facility.json` - 院所層固定欄位（code/name/address/physician_name，測試用示例，院所端日後自行編輯）
- `config/settings.py` - 新增 `FACILITY_CONFIG_PATH`（env 覆寫）＋ `REQUIRED_FACILITY_FIELDS` ＋ `load_facility_config()`（缺檔 FileNotFoundError、壞 JSON/非物件/缺必填欄 ValueError，fail-fast）
- `scripts/build_appeal_print.py` - CLI 入口（argv 校驗 1~3 參數、錯誤分層、safe_filename、OUTPUT_DIR/stem 預設、write_appeal_print 呼叫、warnings「警告：」列印；腳本自癒 sys.path）
- `tests/test_appeal_print.py` - 新增 `-k config` 4 測試（缺檔/缺必填欄/合法回傳/壞 JSON）＋ `-k cli` 8 測試（缺參數/缺檔/壞 JSON/不安全 stem 拒絕/warnings 呈現 fake_write 隔離/二參數 output 路徑/三參數 submission 透傳/soffice 完整流程 pypdf 頁數=3）
- `README.md` - 「🖨️ 紙本申復清單列印（Phase 11）」章節（由「規劃中」升級為使用說明）
- `.planning/phases/11-paper-appeal-print/deferred-items.md` - 環境限制記錄（data/ 唯讀致 2 個既有 server 上傳測試失敗）

## Decisions Made

- facility.json 採用單一院所物件（非院所代碼→資料 dict），必填欄位為 code/name（符合 RESEARCH Q7 與 plan 規格）。
- CLI 參數語意：長度 2 時第 2 個參數為 output_pdf_path（後向兼容 build_appeal_xml 習慣）；case payload 僅能於長度 3（第 2 個參數）提供。
- output_pdf_path 分解：output_dir＝dirname、stem＝basename 去 `.pdf` 並剝離「申復清單_」前綴；未指定時輸出至 settings.OUTPUT_DIR、stem＝`{case_seq}_{order_seq}`（缺失 fallback "unknown"，比照 write_appeal 模式）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 直接執行 CLI 時 `config` 模組無法解析**
- **Found during:** Task 2（CLI 建立後無參數驗收）
- **Issue:** `python scripts/build_appeal_print.py`（無參數）應印 usage 且 exit 1，但 import 階段即 `ModuleNotFoundError: No module named 'config'`——`python scripts/x.py` 時 sys.path[0]＝scripts/ 目錄，專案根（`config` 所在）不在 sys.path；`elc_audit_engine` 經 editable install 解析故不受影響。此問題同時存在於既有 `scripts/build_appeal_xml.py`（沙箱驗證同錯），惟該檔不屬本 plan 修改範圍。
- **Fix:** 於 `scripts/build_appeal_print.py` 在 import `config` 前自行把專案根插入 sys.path（比照 tests/conftest.py 模式）。
- **Files modified:** scripts/build_appeal_print.py
- **Verification:** `uv run python scripts/build_appeal_print.py` → 印 usage 且 exit=1；`-k cli` 8 passed。
- **Committed in:** Task 2 commit（GREEN 後同批）

**2. [Rule 1 - Bug] 完整流程 CLI 測試以二參數傳 case payload（測試腳本 bug）**
- **Found during:** Task 2（-k cli 首跑）
- **Issue:** 依 CLI 契約長度 2 的第 2 個參數是 output_pdf_path；測試誤將 case payload 當第 2 參數傳入，導致 `case_payload.json` 被當成輸出 stem（含 `.` 被 safe_filename 拒絕）而 return 1。
- **Fix:** 測試改以三參數（appeal、case payload、輸出 PDF 路徑）呼叫。
- **Files modified:** tests/test_appeal_print.py
- **Verification:** `-k cli` 8 passed。
- **Committed in:** Task 2 commit

---

**Total deviations:** 2 auto-fixed（皆 Rule 1 型；1 個真實 bug、1 個測試腳本 bug）
**Impact on plan:** 皆屬本 plan 任務直接引起的正確性問題，已修復；無 scope creep。

## Issues Encountered

- **沙箱環境限制（非本 plan 回歸）**：執行沙箱對 `data/` 為唯讀文件系統，`tests/test_server_case_store_integration.py` 的 `test_import_sampling_cases_persists_to_casestore` 與 `test_duplicate_import_reports_conflicts` 因 `server._save_upload` 寫 `data/uploads/raw/*.csv` 失敗（`OSError: [Errno 30] Read-only file system`）。已確認與本 plan 改動無關（基線數字佐證：沙箱非 appeal_print 套件 372 passed + 2 skipped + 2 failed（環境性）恰對應 orchestrator 正常環境基線 374 passed + 2 skipped）。詳見 `.planning/phases/11-paper-appeal-print/deferred-items.md`。
- **pytest cache 唯讀**：`.pytest_cache` 亦為唯讀，測試以 `-p no:cacheprovider` 執行（僅影響本沙箱執行方式，不影響測試結果）。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 11 三項 Success Criteria 全部可驗證：院所層欄位（D-04）fail-fast 提供、CLI 入口可用（Open Q#6 定案 CLI 先行）、README 使用說明完成。
- 完整「appeal JSON → 可列印 PDF」通道已可用。
- orchestrator 於可寫環境執行全套件回歸時預期 408 passed + 2 skipped（396 基線 ＋ 本 plan 新增 12 測試）。

---
*Phase: 11-paper-appeal-print*
*Completed: 2026-08-08*

## Self-Check: PASSED

- 建立/修改檔案全數存在：`config/facility.json`、`config/settings.py`、`scripts/build_appeal_print.py`、`tests/test_appeal_print.py`、`README.md`、`11-03-SUMMARY.md`、`deferred-items.md`（FOUND ×7）。
- `uv run pytest tests/test_appeal_print.py -k config -x` → 4 passed。
- `uv run pytest tests/test_appeal_print.py -k cli -x` → 8 passed。
- `uv run pytest tests/test_appeal_print.py -x`（全組）→ 34 passed（mapping/odt/base/e2e/security/copies/config/cli，soffice 可用故 e2e/CLI 完整流程實跑）。
- `uv run python scripts/build_appeal_print.py`（無參數）→ 印 usage 且 exit code 1。
- `uv run python -c "from config.settings import load_facility_config, FACILITY_CONFIG_PATH; print(FACILITY_CONFIG_PATH)"` → 預設路徑 config/facility.json，load_facility_config() 回傳含 code/name 之 dict。
- 既有套件分批回歸：372 passed + 2 skipped + 2 failed（後者為沙箱 data/ 唯讀之環境限制，見 deferred-items.md，非本 plan 回歸）。
- 註記：沙箱 `.git` 唯讀，未執行 git commit（orchestrator 依 SUMMARY「Task Commits」建議訊息建立 commit）。
