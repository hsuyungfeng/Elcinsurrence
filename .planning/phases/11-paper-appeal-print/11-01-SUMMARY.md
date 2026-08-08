---
phase: 11-paper-appeal-print
plan: 01
subsystem: output-generation
tags: [odt, zipfile, xml-elementtree, pypdf, appeal-print, field-mapping, pagination]

# Dependency graph
requires:
  - phase: 07-output-appeal-draft
    provides: AppealDraft/render_appeal_json（p1-p9 醫令段欄位與 sections）
  - phase: 04-record-aggregator
    provides: DeductionRecord.id_number（遮罩後 4 碼，PHI）、SubmissionCase（d1/d2/d8/d19/d49）
  - phase: 08-e2e-testing
    provides: 既有測試基線（-k "not appeal_print" 不回歸）
provides:
  - field_mapping.build_rows/build_header/paginate 純函式（官方 14 主表資料欄＋7 頭表欄逐欄對應）
  - odt_fill.fill_template/verify_template_hash（ET 文本節點注入＋zip 重打包＋超行分頁 D-06）
  - Wave 0 測試脚手架（tests/test_appeal_print.py 11 測試、conftest facility_config/sample_appeal_draft、pypdf dev dep）
  - D-03 三聯版式差異與資料來源策略之使用者確認（D-03 以官方模板第二聯為準）
affects:
  - 11-02 列印編排（write_appeal_print/print_base.sha256 接線、佈局壓縮參數）
  - 11-03 CLI 入口與 config（facility.json/FACILITY_CONFIG_PATH/load_facility_config）
  - 11-04 PDF 轉檔與逐欄核對

# Tech tracking
tech-stack:
  added: [pypdf (dev dep, PDF 驗證測試用)]
  patterns:
    - "ET 文本節點注入（p.text = value，自動轉義）取代字串插值——T-11-01 安全紀律"
    - "官方 ODT 逐 cell 索引注入（實測契約：cell[0..12]+cell[14]＝14 資料欄，cell[13] 單價續列留空）"
    - "zip 重打包 mimetype 首條目 ZIP_STORED、其餘 ZIP_DEFLATED（RESEARCH Pitfall 3）"
    - "缺欄誠實降級：submission 缺席/鍵值空 → \"\"＋warnings 累積欄位名，不猜測補全（T-11-05）"
    - "22 命名空間逐一 register_namespace，避免 ns0/ns1（RESEARCH Pitfall 4）"

key-files:
  created:
    - src/elc_audit_engine/generators/appeal_print/__init__.py（套件入口）
    - src/elc_audit_engine/generators/appeal_print/field_mapping.py（build_rows/build_header/paginate）
    - src/elc_audit_engine/generators/appeal_print/odt_fill.py（fill_template/verify_template_hash/AppealPrintFillError）
    - tests/test_appeal_print.py（-k mapping×6＋-k odt×5，requires_soffice skip 標記）
  modified:
    - tests/conftest.py（facility_config、sample_appeal_draft fixtures）
    - pyproject.toml（uv add --dev pypdf）
    - uv.lock（pypdf 依賴鎖定）

key-decisions:
  - "D-03 三聯版式差異（2026-08-08 使用者裁示）：以官方模板第二聯為準（「中央健康保險署填列」核定|複核|初核|審查委員 空白欄在第二聯，留空供健保署複核）；ROADMAP SC3 與 REQUIREMENTS 驗收標準 3 措辭由 orchestrator 更新為「第二聯」（commit ba1f211）"
  - "資料來源策略（2026-08-08 使用者確認）：身份證字號由 submission.id_number 照印遮罩值（缺席→留空＋warning，禁止重建完整字號 T-11-05）；姓名/傷病名稱/審查科別/數量/金額由呼叫端另供 submission dict（join key＝case_class d1＋case_seq d2），缺欄誠實留空＋warning"
  - "健保署填列欄（審核意見/補付數量/單價/補付金額）系統一律留空，不計算補付金額、不捏造（以官方 PDF 30396_4 合計列樣式為準）"

patterns-established:
  - "欄位組裝純函式：payload/submission/facility 分層參數推導，模組不 import settings、不觸 I/O（D-05）"
  - "先紅後綠 TDD：mapping 測試（Task 1）與 odt 測試（Task 2）分階段驗證，Wave 收束 -k \"mapping or odt\""
  - "官方模板為 git-tracked 資產＋verify_template_hash sha256 防竄改（T-11-06，11-02 接線）"

requirements-completed: [REQ-paper-appeal-print]

# Metrics
duration: 65min
completed: 2026-08-08
---

# Phase 11 Plan 01: 紙本申復清單欄位組裝層＋ODT 注入層 Summary

**欄位組裝層（field_mapping，14 資料欄契約）＋ODT 注入層（odt_fill，ET 文本節點注入/zip 重打包/分頁）＋Wave 0 測試脚手架，並完成 D-03 三聯版式差異與資料來源策略兩項使用者裁示**

## Performance

- **Duration:** 65 min
- **Started:** 2026-08-08
- **Completed:** 2026-08-08
- **Tasks:** 3（Task 1/2 由 orchestrator 於先前 session 執行並 commit；本 session 為 checkpoint 決策收束＋SUMMARY 產出）
- **Files modified:** 8（3 建立＋2 修改＋3 依賴/鎖定）

## Accomplishments

- **Task 1（欄位組裝層）**：`field_mapping.py` 提供 `build_rows`（官方 14 主表資料欄 ← AppealDraft/CaseStore payload/facility/submission 逐欄對應，含「傷病名稱」欄）、`build_header`（頭表 7 欄：代號字碼/院所名稱/審查科別/原申報類別/原申報日期/年度/月份）、`paginate`（15 行/頁固定容量，D-06）。模組 docstring 記載欄位來源決策（patient_name=None 實測、join key d1+d2、id_number 遮罩照印不重建、primary_diagnosis 傷病名稱來源）；無 `import settings`、無字串插值。
- **Task 1（Wave 0 脚手架）**：`tests/test_appeal_print.py` 建立（Module 級 `requires_soffice` skip 標記，比照 test_doc_converter.py）；`tests/conftest.py` 新增 `facility_config`（monkeypatch `settings.FACILITY_CONFIG_PATH`）與 `sample_appeal_draft` 兩 fixture；`uv add --dev pypdf`。
- **Task 2（ODT 注入層）**：`odt_fill.py` 提供 `fill_template`（22 命名空間逐一註冊避免 ns0/ns1、`set_cell_text` 以 `p.text = value` 寫入自動轉義、mimetype 首條目 ZIP_STORED、超行分頁複製聯組＋soft-page-break、合計列/說明表僅末頁）與 `verify_template_hash`（sha256 防竄改，11-02 接線）；自訂 `AppealPrintFillError` 錯誤訊息只記欄位名/階段不含值全文（T-11-03）。
- **Task 3（checkpoint:decision）**：D-03 三聯版式差異與資料來源策略兩項使用者裁示完成並記錄（見下）。

## Task Commits

本 plan 的程式/測試/deps 提交由 orchestrator 執行（executor 沙箱 `.git` 唯讀），共 5 個：

1. **Task 0（依賴）**: `7d973a5` (chore(11-01): add pypdf dev dependency — pyproject.toml, uv.lock)
2. **Task 1（Wave 0 脚手架＋mapping 測試）**: `2f0b97c` (test(11-01): add wave-0 appeal_print scaffolding + mapping tests — tests/conftest.py, src/elc_audit_engine/generators/appeal_print/__init__.py, tests/test_appeal_print.py)
3. **Task 1（field_mapping）**: `e3ea649` (feat(11-01): implement field_mapping build_rows/build_header/paginate)
4. **Task 2（odt_fill）**: `07d54f8` (feat(11-01): implement odt_fill fill_template + verify_template_hash)
5. **Task 3（決策措辭，orchestrator-owned）**: `ba1f211` (docs(11): D-03 user decision — 核定欄以官方模板第二聯為準)

## Files Created/Modified

- `src/elc_audit_engine/generators/appeal_print/__init__.py` - 套件入口（wave-0 scaffolding）
- `src/elc_audit_engine/generators/appeal_print/field_mapping.py` - 14 主表資料欄＋7 頭表欄逐欄對應純函式（build_rows/build_header/paginate），缺欄誠實降級（warnings 累積、永不捏造）
- `src/elc_audit_engine/generators/appeal_print/odt_fill.py` - ET 文本節點注入 content.xml＋zip 重打包＋超行分頁（fill_template/verify_template_hash/AppealPrintFillError）
- `tests/test_appeal_print.py` - Wave 0 測試脚手架（-k mapping×6、-k odt×5、requires_soffice skip）
- `tests/conftest.py` - 新增 facility_config、sample_appeal_draft 兩 fixture
- `pyproject.toml` / `uv.lock` - pypdf dev dep

## Decisions Made

1. **D-03 三聯版式差異（使用者裁示，2026-08-08）**：以官方模板第二聯為準——「中央健康保險署填列」的「核定|複核|初核|審查委員」空白欄在**第二聯**（健保署存查聯）說明表 row1（官方 30396_1/30396_3 ODT 與 30396_2/30396_4 PDF 交叉比對 VERIFIED），第一/三聯說明表無此欄。系統不填該欄（留空供健保署複核），三聯結構差異由模板本身承載，注入邏輯不改動說明表。**orchestrator 已將 ROADMAP Success Criteria 3 與 REQUIREMENTS 驗收標準 3 的措辭更新為「第二聯」（commit `ba1f211`）。**
2. **資料來源策略（使用者確認，2026-08-08）**：身份證字號由 submission dict 的 `id_number` 鍵照印遮罩值（呼叫端自 `DeductionRecord.id_number` 傳入，缺席即留空＋warning，禁止重建完整字號 T-11-05）；姓名/傷病名稱/審查科別/數量/金額由呼叫端另供 submission dict（join key＝case_class d1＋case_seq d2，來自申報 XML 匯入）填寫、join 不到誠實留空＋warning。`field_mapping.py` 已按此策略實作並通過測試——使用者確認了已實作之策略，無需修改 field_mapping/odt_fill 行為。
3. 健保署填列欄（審核意見/補付數量/單價/補付金額）系統一律留空，不計算補付金額、不捏造（以官方 PDF 30396_4 合計列樣式為準）。

## Deviations from Plan

**None — plan executed as written.**

唯一環境限制註記：executor 沙箱的 `.git` 唯讀，因此本 plan 的 5 個 commit 全部由 orchestrator 執行（見 Task Commits）。非內容偏差——程式/測試/deps 與驗收標準一致。

### Auto-fixed Issues

無。

---

**Total deviations:** 0 auto-fixed
**Impact on plan:** 無偏差，計畫照文執行。

## Known Stubs

無。全部 14 資料欄與 7 頭表欄皆有明確來源或誠實留空降級；`pypdf` 為 dev dep 尚未有使用它的測試（11-02/11-03 的 PDF 逐欄核對才使用），屬依序交付而非 stub。

## Threat Flags

無新增攻擊面。本 plan 全部產物為 CLI/library 純函式模組與測試，**未新增任何網路端點/認證路徑**；產出 ODT 由 fill_template 寫入呼叫端指定路徑（測試走 pytest tmp_path，正式產出經 data/output 且已 gitignore，T-11-02）。threat_model 的 T-11-01~T-11-07 皆按 mitigation 實作或由 11-02/11-03 接線（verify_template_hash、safe_filename、write_appeal_print）。

## Issues Encountered

None。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **11-02**：`write_appeal_print` 可接線 `fill_template`（print_base.sha256 接 `verify_template_hash`）；佈局壓縮參數（RESEARCH Q3/A1）與合計列/說明表僅末頁語義已就緒；-k copies/security/e2e 測試依序添加。
- **11-03**：CLI 入口接 `build_rows/build_header/paginate`＋`fill_template`；`facility_config` fixture 已先行，`FACILITY_CONFIG_PATH`/`load_facility_config` 待建。
- **11-04**：PDF 轉檔（soffice headless）與逐欄核對需 pypdf（已入 dev deps）。

---
*Phase: 11-paper-appeal-print*
*Completed: 2026-08-08*

## Self-Check: PASSED

執行於 2026-08-08（executor 沙箱環境）：

- [x] 測試：`uv run pytest tests/test_appeal_print.py -k "mapping or odt"` → **11 passed**（1.40s）
- [x] 收集：`pytest --collect-only tests/test_appeal_print.py` → **11 tests collected**（mapping×6＋odt×5）
- [x] 文件存在：
  - `src/elc_audit_engine/generators/appeal_print/field_mapping.py`
  - `src/elc_audit_engine/generators/appeal_print/odt_fill.py`
  - `src/elc_audit_engine/generators/appeal_print/__init__.py`
  - `tests/test_appeal_print.py`
  - `.planning/phases/11-paper-appeal-print/11-01-SUMMARY.md`
  - conftest fixtures：`facility_config`、`sample_appeal_draft`（grep 確認於 tests/conftest.py）
- [x] Commits 存在（git log --oneline --all）：
  - `7d973a5` chore(11-01): add pypdf dev dependency
  - `2f0b97c` test(11-01): add wave-0 appeal_print scaffolding + mapping tests
  - `e3ea649` feat(11-01): implement field_mapping build_rows/build_header/paginate
  - `07d54f8` feat(11-01): implement odt_fill fill_template + verify_template_hash
  - `ba1f211` docs(11): D-03 user decision — 核定欄以官方模板第二聯為準
