---
phase: 11-paper-appeal-print
plan: 02
subsystem: output-generation
tags: [odt, layout-compression, soffice, pypdf, template, render, write, three-copies]

# Dependency graph
requires:
  - phase: 11-paper-appeal-print
    plan: 01
    provides: field_mapping.build_rows/build_header/paginate、odt_fill.fill_template/verify_template_hash、AppealPrintFillError、Wave-0 測試脚手架（-k mapping/-k odt）
  - phase: 07-output-appeal-draft
    provides: AppealDraft/render_appeal_json（render_appeal_print 直接消費的 payload）
  - phase: 04-record-aggregator
    provides: submission 層患者欄位（id_number/patient_name/primary_diagnosis/clinic/orders）
provides:
  - template.py build_print_base：官方 ODT → 每聯一頁壓縮基準模板（_print_base.odt＋sha256，git 版控資產）
  - render_appeal_print（純函式，回傳 filled ODT bytes＋warnings）／write_appeal_print（薄包裝，safe_filename＋makedirs＋soffice 轉 PDF，回傳 pdf_path＋warnings）自 generators/__init__.py 對外匯出
  - -k base／-k e2e／-k security／-k copies 測試（22 測試全綠；e2e 頁數＝3×N、A2 fallback、三聯版式差異、注入/檔名穿越防線）
affects:
  - 11-03 CLI 入口（消費 render/write＋facility config）
  - 11-04 PDF 轉檔與逐欄核對（pypdf 已實跑）

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "一次性布局壓縮基準模板：官方 ODT →（build_print_base）→ *_print_base.odt 入 git，render 時不重複調參"
    - "ODF 佈局網格（style:layout-grid-mode=line＋snap-to-layout-grid）是官方 ODT 直轉 PDF 9 頁的主因——關閉網格即回收大量空隙"
    - "text:soft-page-break 為軟分頁符，內容壓短後不強制分頁——以每聯標題段 fo:break-before=page 補償維持「每聯一頁」"
    - "soffice 輸出檔名＝輸入檔名去副檔名＋.pdf：filled ODT 檔名須與目標 PDF 同名"

key-files:
  created:
    - src/elc_audit_engine/generators/appeal_print/template.py（build_print_base）
    - officialdocument/電子申復文件格式/30396_1_1050105-1門診診療費用申復清單_print_base.odt（壓縮基準模板，git 入庫）
    - officialdocument/電子申復文件格式/30396_1_1050105-1門診診療費用申復清單_print_base.sha256（模板 sha256，T-11-06 校驗基準）
  modified:
    - src/elc_audit_engine/generators/appeal_print/__init__.py（render_appeal_print/write_appeal_print）
    - src/elc_audit_engine/generators/__init__.py（對外匯出 render/write）
    - tests/test_appeal_print.py（-k base×4、-k e2e×2、-k security×2、-k copies×3）

key-decisions:
  - "收斂參數（v4）：關閉佈局網格＋資料行 line-height/min-height 0.18in＋邊距 0.5/0.1in＋標題 120%＋每聯標題 break-before=page＋說明表不調整——收斂後 3 頁、資料行 26.4pt、頁底 779.3pt（對齊官方 30396_4 的 27pt/779pt）"
  - "e2e 文本斷言採去空白後子串比對：官方頭表標題為直排文字，pdftotext 會拆行（如「代號\n字碼」）——以 re.sub 去空白後斷言「代號字碼」等鍵"
  - "write_appeal_print 的 filled ODT 檔名＝申復清單_{stem}.odt（與目標 PDF 同名），soffice 轉檔輸出才能正確命名"

patterns-established:
  - "壓縮基準模板是唯一 git 入庫的產出（officialdocument/ 未 ignore），render 時以 *_print_base.sha256 校驗（A5/T-11-06）"
  - "render 純函式以 tempfile.TemporaryDirectory 組 filled ODT bytes（無專案目錄副作用）；write 薄包裝負責 safe_filename＋makedirs＋soffice"

requirements-completed: [REQ-paper-appeal-print]

# Metrics
duration: 16min
completed: 2026-08-08
---

# Phase 11 Plan 02: 紙本申復清單壓縮基準模板＋render/write 輸出通道 Summary

**以 build_print_base 一次性把官方 ODT 壓縮成每聯一頁的基準模板（6 輪收斂：關佈局網格＋0.18in 資料行＋每聯 break-before=page → 3 頁、行高 26.4pt 對齊官方 PDF），並以 render_appeal_print 純函式＋write_appeal_print 薄包裝自 generators 對外匯出，e2e/copies/security 測試全綠（22 測試）**

## Performance

- **Duration:** 16 min
- **Started:** 2026-08-08T03:29:00Z
- **Completed:** 2026-08-08T03:45:42Z
- **Tasks:** 3
- **Files modified:** 7（3 建立＋4 修改；內含 2 個 git 入庫版控資產）

## Accomplishments

- **Task 1（壓縮基準模板＋收斂）**：`template.py::build_print_base(src_odt, out_odt, *, sha256_out)` 以 stdlib zipfile＋ET 壓縮官方 ODT。**6 輪收斂實驗**（v0~v5，soffice 轉 PDF＋pypdf 數頁＋pdftotext -bbox 量測）後以 **v4 參數收斂：3 頁（每聯一頁）、資料行高 26.4pt、頁底 779.3pt——與官方 `30396_4` Golden（27pt/779pt）幾乎一致**。產出 `*_print_base.odt`＋`*_print_base.sha256`（`dbd51c1e…83137`）入 git。`-k base` 4 測試綠（含 @requires_soffice 實跑頁數=3）。
- **Task 2（render/write＋e2e/security）**：`render_appeal_print`（純函式，`tempfile.TemporaryDirectory` 組 bytes，**無專案目錄副作用**）＋`write_appeal_print`（safe_filename＋makedirs＋`verify_template_hash`（讀 `*_print_base.sha256`）＋soffice 轉 PDF，回傳 `(pdf_path, warnings)`）；自 `generators/__init__.py` 匯出。e2e 測試實測：單醫令 3 頁、15 行 3 頁、16 行分頁 6 頁；關鍵文本（代號字碼/測試醫療院所/01015C/E5002C/D2/18）於 PDF 文本層驗證（A2 fallback：pypdf→pdftotext 實測 pdftotext 採行）；security 測試：`../`/`..`/`a/b` 檔名穿越被拒且外部目錄未寫入、`<script>`/`&` 注入不破壞 ODT 且轉檔成功。
- **Task 3（copies 三聯版式差異）**：`-k copies` 3 測試（ODT XML 層斷言，不觸 soffice）：第二聯說明表 row1 恰為「核定|複核|初核|審查委員」、第一/三聯無（系統不填，留空供健保署複核）；合計列 cell[0]「合計」/cell[2]＝人次/補付欄空；資料列 cell[4] 傷病名稱與 build_rows 鍵值一致（14 鍵不逐欄錯位）。

## Task Commits

本 plan 的 commit 由 orchestrator 執行（executor 沙箱 `.git` 唯讀，無法 git add/commit；文件變更已全部就緒於工作樹）。建議依 Task 分組：

1. **Task 1**：`feat(11-02): build_print_base 壓縮基準模板（3 頁收斂）＋print_base 資產`
   - `src/elc_audit_engine/generators/appeal_print/template.py`
   - `officialdocument/電子申復文件格式/30396_1_1050105-1門診診療費用申復清單_print_base.odt`
   - `officialdocument/電子申復文件格式/30396_1_1050105-1門診診療費用申復清單_print_base.sha256`
   - `tests/test_appeal_print.py`（-k base×4）
2. **Task 2**：`feat(11-02): render_appeal_print/write_appeal_print＋generators 匯出＋e2e/security 測試`
   - `src/elc_audit_engine/generators/appeal_print/__init__.py`
   - `src/elc_audit_engine/generators/__init__.py`
   - `tests/test_appeal_print.py`（-k e2e×2、-k security×2）
3. **Task 3**：`test(11-02): copies 三聯版式差異測試（第二聯核定欄/合計列/傷病名稱）`
   - `tests/test_appeal_print.py`（-k copies×3）

## 收斂結果（Open Q#3 / A1）

**收斂成功**（10 輪上限內，實際 6 輪），未觸發「收斂失敗出口」。

| 輪 | 變更 | 頁數 | 資料行高 | 頁底 |
|----|------|------|----------|------|
| v0 | 關網格＋0.2in 行高＋邊距 0.5/0.1in | 3 | — | 聯間錯位（soft-page-break 不分頁） |
| v1 | 僅關網格 | 3 | — | 聯間錯位 |
| v2 | 關網格＋每聯 break-before=page | 6 | — | 每聯 2 頁（行高未壓） |
| v3 | 同 v2＋資料行 0.2in＋標題 120% | 3 | 29.3pt | 799.3pt（微溢出） |
| **v4（採用）** | **資料行 0.18in** | **3** | **26.4pt** | **779.3pt** |
| v5 | 資料行 0.16in | 3 | 23.5pt | 735.8pt（備選） |

**最終參數（v4）**：邊距 left/right `0.5in`、top/bottom `0.1in`；`layout-grid-mode=none`＋默認段落 `snap-to-layout-grid=false`；資料行 line-height＋min-row-height `0.18in`；主表 row0 `0.35in`；頭表 `0.45in`；合計列 `0.2in`；標題 line-height `120%`；每聯標題段 `fo:break-before="page"`；說明表不調整。全部記錄於 `template.py` 模組 docstring。

**根因**：官方 ODT 直轉 PDF 9 頁的主因是**佈局網格**（`layout-grid-mode=line` 45 線＋`snap-to-layout-grid`）使空行/文字行吸附到網格高度；其次是資料行 line-height 0.3333in 與軟分頁符不分頁。

**頁數判準**：空模板 3 頁、注入 15 行 3 頁、16 行 6 頁（D-06 分頁與壓縮相容）；每聯合計列與說明表同頁。

**模板 sha256**：`dbd51c1e173ceda53fcd28df6a220a967515988318b796437be946cd99a83137`

## Files Created/Modified

- `src/elc_audit_engine/generators/appeal_print/template.py` - build_print_base（一次性布局壓縮；docstring 記錄 6 輪收斂參數與判準）
- `officialdocument/電子申復文件格式/30396_1_1050105-1門診診療費用申復清單_print_base.odt` - 壓縮基準模板（每聯一頁，git 版控資產）
- `officialdocument/電子申復文件格式/30396_1_1050105-1門診診療費用申復清單_print_base.sha256` - 模板 sha256（verify_template_hash 校驗基準）
- `src/elc_audit_engine/generators/appeal_print/__init__.py` - render_appeal_print（純函式 bytes＋warnings）/write_appeal_print（薄包裝 pdf_path＋warnings）
- `src/elc_audit_engine/generators/__init__.py` - 對外匯出 render_appeal_print/write_appeal_print（含 __all__）
- `tests/test_appeal_print.py` - -k base×4（含 @requires_soffice 頁數=3）、-k e2e×2（15/16 行 3/6 頁）、-k security×2（穿越/注入）、-k copies×3（三聯差異）

## Decisions Made

1. **收斂參數 v4**（見上表）：關閉佈局網格是 9→3 頁的關鍵單一變因；資料行 0.18in 讓行高 26.4pt 對齊官方 Golden 27pt 且頁底 779.3pt 對齊 779pt。
2. **e2e 文本斷言採「去空白後子串比對」**：官方頭表標題為直排文字（pdftotext 拆成「代號\n字碼」），斷言前以 `re.sub(r"\s+","",text)` 壓平。測試註記實際採用路徑＝pdftotext（pypdf 提取含該文本但拆行位置不同，A2 fallback 生效）。
3. **filled ODT 檔名＝目標 PDF 同名**（`申復清單_{stem}.odt`）：soffice 輸出檔名＝輸入去副檔名＋.pdf，不同名會導致輸出檔不存在而誤判失敗（Rule 1 修復）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] write_appeal_print 轉檔輸出檔名不匹配**
- **Found during:** Task 2（e2e Test 1）
- **Issue:** filled ODT 暫存檔名為 `申復清單_filled.odt`，soffice 輸出 `申復清單_filled.pdf`，與目標 `申復清單_{stem}.pdf` 不同名 → 誤判「輸出檔不存在」raise AppealPrintFillError
- **Fix:** 暫存 filled ODT 改名為 `申復清單_{stem}.odt`（與目標 PDF 同名）
- **Files modified:** src/elc_audit_engine/generators/appeal_print/__init__.py
- **Verification:** -k e2e 實跑通過
- **Committed in:** 建議 Task 2 commit

**2. [Rule 1 - Bug] e2e 文本斷言因直排文字拆行失敗**
- **Found during:** Task 2（e2e Test 1）
- **Issue:** 官方頭表標題為直排文字，pdftotext 拆成多行（「代號\n字碼」），連續子串「代號字碼」斷言失敗
- **Fix:** 斷言前以 `re.sub(r"\s+","",text)` 壓平後比對
- **Files modified:** tests/test_appeal_print.py
- **Verification:** -k e2e 實跑通過
- **Committed in:** 建議 Task 2 commit

---

**Total deviations:** 2 auto-fixed（皆 Rule 1 bug，屬 Task 2 直接相關）
**Impact on plan:** 必要修正，無 scope creep。收斂過程無偏差（v4 於 6 輪內收斂，未觸發失敗出口）。

## Issues Encountered

- **沙箱 .git 唯讀**（環境限制）：executor 無法 git add/commit，本 plan 的 3 個 Task commit 需由 orchestrator 依上方「Task Commits」執行（非內容偏差，比照 11-01）。
- **沙箱 data/uploads 唯讀**（環境限制，非回歸）：`tests/test_server_case_store_integration.py` 2 個測試（`test_import_sampling_cases_persists_to_casestore`/`test_duplicate_import_reports_conflicts`）因寫入 `data/uploads/raw/*.csv` 失敗（Errno 30 Read-only file system）而失敗——與本 plan 無關（未觸碰 server/case_store），屬沙箱唯讀掛載限制。
- 既有套件其餘 372 tests 全綠（+2 skipped）：`-k "not appeal_print"` 分 3 批執行，受影響子集（test_appeal/test_appeal_xml/test_config/test_doc_converter/test_safe_paths 69 passed）全綠。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **11-03**：CLI 入口可接 `render_appeal_print`/`write_appeal_print`（回傳 `(pdf_path|bytes, warnings)` 契約已定）＋`FACILITY_CONFIG_PATH`/`load_facility_config()`；`facility_config` fixture 已先行。
- **11-04**：PDF 轉檔與逐欄核對可用 pypdf（頁數/文本層已實跑驗證）；視覺逐欄比對（Manual-Only）需以本 plan 產出之 3 頁 PDF 對齊官方 30396_4。
- 三聯版式差異（第二聯核定欄）與資料來源策略（submission join）已由 11-01 使用者裁示並於本 plan 以 ODT XML 層測試固鎖。

---
*Phase: 11-paper-appeal-print*
*Completed: 2026-08-08*

## Self-Check: PASSED

執行於 2026-08-08（executor 沙箱環境）：

- [x] `uv run pytest tests/test_appeal_print.py -x` → **22 passed**（mapping×6＋odt×5＋base×4＋e2e×2＋security×2＋copies×3；soffice 可用，e2e/base 實跑通過）
- [x] `uv run pytest tests/test_appeal_print.py -k base -x` → 4 passed
- [x] `uv run pytest tests/test_appeal_print.py -k "e2e or security" -x` → 4 passed
- [x] `uv run pytest tests/test_appeal_print.py -k copies -x` → 3 passed
- [x] `uv run python -c "from elc_audit_engine.generators import render_appeal_print, write_appeal_print"` → 成功
- [x] 既有套件不回歸：-k "not appeal_print" 分 3 批 → 372 passed＋2 skipped（另 2 個 server_case_store 整合測試因沙箱 data/uploads 唯讀失敗，與本 plan 無關）
- [x] 文件存在：
  - `src/elc_audit_engine/generators/appeal_print/template.py`
  - `src/elc_audit_engine/generators/appeal_print/__init__.py`
  - `src/elc_audit_engine/generators/__init__.py`
  - `officialdocument/電子申復文件格式/30396_1_1050105-1門診診療費用申復清單_print_base.odt`
  - `officialdocument/電子申復文件格式/30396_1_1050105-1門診診療費用申復清單_print_base.sha256`
  - `tests/test_appeal_print.py`
  - `.planning/phases/11-paper-appeal-print/11-02-SUMMARY.md`
- [x] 收斂判準：空模板 3 頁、注入 15 行 3 頁、16 行 6 頁（D-06）；每聯合計列與說明表同頁
- [x] 版控：`git status` 顯示 `*_print_base.odt`/`*_print_base.sha256` 可追蹤（`git check-ignore` exit=1，未被忽略）；模板 sha256 `dbd51c1e173ceda53fcd28df6a220a967515988318b796437be946cd99a83137`
