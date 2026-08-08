---
phase: 11-paper-appeal-print
verified: 2026-08-08T04:21:06Z
status: passed
score: 3/3
overrides_applied: 0
---

# Phase 11: 紙本申復清單列印 Verification Report

**Phase Goal:** 依官方三聯式「門診醫療費用點數申復清單」版式（105.04.01 修訂版，`officialdocument/電子申復文件格式/30396_*`）產出可列印 PDF，供尚未串接 HIS 或選擇紙本作業的院所使用——`AppealDraft`（Phase 7 產出）新增一條 PDF 排版輸出通道，與既有 Markdown／JSON／申復 XML 並行，不互相取代
**Verified:** 2026-08-08T04:21:06Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | **SC1** PDF 版面與官方三聯式範本逐欄核對一致（14 主表資料欄＋7 頭表欄＋合計列＋第二聯核定欄，缺一不可） | ✓ VERIFIED | 官方 30396_1 ODT 直接解包實證（9 tables＝3 聯×3；主表 18 rows＝row0 大標題＋row1 表頭＋row2~16 資料行＋row17 合計列；資料行 15 cells；頭表 17 cells）；`-k mapping`×7＋`-k odt`×5 斷言 14 鍵逐欄對應與 cell 注入位置；手工 PDF 文本層驗證 15 個關鍵欄位值（01015C/測試醫療院所/內科/送核/110年8月3日/D2/18/F10291\*\*\*\*/陳小明/J189/E5002C/300/1/理由/合計）全數出現；e2e 3 頁 PDF；bbox 收斂（行高 26.4pt/頁底 779.3pt 對齊 Golden 27pt/779pt，11-02-SUMMARY） |
| 2 | **SC2** 由既有 AppealDraft 資料直接生成 PDF，不需另建資料模型 | ✓ VERIFIED | 手工資料流實證：`AppealDraft` → `render_appeal_json`（鍵含 case_class/case_seq/order_seq/order_code/p1_order_seq/p2_order_code/p8_reason1/p9_reason2/fee_year_month）→ `render_appeal_print(payload, facility, submission)` → 30,831 bytes filled ODT、warnings=[]。render 由 payload dict 驅動，無新資料模型；CLI 完整流程（appeal JSON＋case payload）exit 0 產出 3 頁 PDF |
| 3 | **SC3** 三聯版式差異正確反映（第二聯（健保署存查聯）多出「中央健康保險署填列」核定/複核/初核/審查委員欄，留空供健保署複核） | ✓ VERIFIED | 官方模板實證：第二聯說明表 row1＝`["核定","複核","初核","審查委員"]`、第一聯＝`["","","",""]`、第三聯＝2 空 cells——差異由模板本身承載（D-03 以官方模板第二聯為準）；`-k copies`×3 於 ODT XML 層斷言第二聯 row1 恰為 4 標題＋row2/row3 留空＋第一/三聯無；手工 PDF 層交叉驗證：以「初核」「審查委員」為區分鍵，僅第 2 頁含核定欄（第 1/3 頁不含；「核定」「複核」字樣在三聯均有屬說明文字 notes，非欄位） |

**Score:** 3/3 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `src/elc_audit_engine/generators/appeal_print/field_mapping.py` | build_rows（14 資料欄）＋build_header（7 頭表欄）＋paginate（15 行/頁）；缺欄誠實降級不捏造 | ✓ VERIFIED | `-k mapping`×7 全綠；無 `import settings`、無字串插值；id_number 遮罩照印＋未遮罩防呆 warning（should-fix 8e8924d） |
| `src/elc_audit_engine/generators/appeal_print/odt_fill.py` | fill_template（ET 文本節點注入＋zip 重打包＋分頁）＋verify_template_hash＋AppealPrintFillError（錯誤不含值全文） | ✓ VERIFIED | `-k odt`×5 全綠（14 欄注入/cell[13] 留空/16 行分頁/XML 轉義/zip mimetype STORED）；sha256 負向測試（should-fix） |
| `src/elc_audit_engine/generators/appeal_print/template.py` | build_print_base 壓縮基準模板（每聯一頁收斂） | ✓ VERIFIED | `-k base`×5 全綠；資產與 sidecar 實測 hash `dbd51c1e173ceda53fcd28df6a220a967515988318b796437be946cd99a83137` 一致 |
| `officialdocument/電子申復文件格式/30396_1_..._print_base.odt`＋`.sha256` | 壓縮基準模板（git 版控資產）＋校驗基準 | ✓ VERIFIED | 實測存在；sha256sum 與 sidecar 完全一致 |
| `src/elc_audit_engine/generators/appeal_print/__init__.py` | render_appeal_print（純函式 bytes＋warnings）／write_appeal_print（safe_filename＋makedirs＋verify_template_hash＋soffice） | ✓ VERIFIED | `-k e2e`×2、`-k security`×3 全綠；CLI smoke 實跑 exit 0 |
| `src/elc_audit_engine/generators/__init__.py` | 對外匯出 render/write_appeal_print（含 __all__） | ✓ VERIFIED | grep 確認 `.appeal_print import render_appeal_print, write_appeal_print`＋__all__ 含兩者 |
| `config/settings.py`＋`config/facility.json` | FACILITY_CONFIG_PATH（env 覆寫）＋load_facility_config（fail-fast） | ✓ VERIFIED | `-k config`×4 全綠（缺檔 FileNotFoundError／缺必填欄 ValueError／壞 JSON ValueError） |
| `scripts/build_appeal_print.py` | CLI 入口（1~3 參數、錯誤分層 return 1、safe_filename、warnings「警告：」） | ✓ VERIFIED | `-k cli`×8 全綠＋手工 CLI 完整流程 exit 0／3 頁 PDF |
| `tests/test_appeal_print.py`＋`tests/conftest.py` | 37 測試＋facility_config/sample_appeal_draft fixtures | ✓ VERIFIED | 37 passed；fixtures 於 conftest 確認 |
| `README.md` | 紙本申復清單列印使用說明章節 | ✓ VERIFIED | 章節存在（用途/前置條件/三種指令/行為說明/PHI 注意） |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `AppealDraft`（Phase 7） | `render_appeal_print` | `render_appeal_json` 產出 payload dict → build_header/build_rows/paginate | WIRED | 手工資料流實證；payload 鍵與 field_mapping 消費鍵一一對應（SC2） |
| `render_appeal_print` | `fill_template` | header_fields＋pages 傳參 | WIRED | `-k odt`/e2e 覆蓋 |
| `write_appeal_print` | soffice → PDF | `subprocess.run`（`-env:UserInstallation` headless 慣例，比照 doc_converter） | WIRED | CLI smoke/e2e 實跑 3 頁 |
| `write_appeal_print` | `verify_template_hash` | `_load_expected_sha256` sidecar 動態定位（T-11-06） | WIRED | 資產 hash 實測一致；缺 sidecar 拒絕（should-fix 負向測試） |
| CLI `scripts/build_appeal_print.py` | `write_appeal_print` | `settings.load_facility_config()`＋submission 透傳 | WIRED | `-k cli`×8；三參數透傳實證 |
| 輸出 PDF | `data/output/*` | `settings.OUTPUT_DIR` | WIRED | `.gitignore` 實證 `data/output/*` 已忽略（PHI 防外洩） |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `render_appeal_print` | payload dict | `render_appeal_json(draft)` 真實 AppealDraft | Yes（手工資料流：case_class/case_seq/order_code/reason 等真實鍵值流入） | ✓ FLOWING |
| `field_mapping.build_rows` | 14 欄 row dict | payload＋facility＋submission（患者層 join key case_class+case_seq、orders 依 seq） | Yes（ID 遮罩照印/姓名/傷病名稱/數量/金額真實流入；缺欄誠實留空＋warnings） | ✓ FLOWING |
| `odt_fill.fill_template` | header_fields＋pages | build_header/build_rows 產出 | Yes（ODT XML 層 cell 文本＝來源值，copies/odt 測試斷言） | ✓ FLOWING |
| PDF 文本層 | 15 個欄位值 | 注入的 ODT → soffice 渲染 | Yes（手工 pypdf 提取：全欄位值出現，無 missing keys） | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Phase 11 全組測試 | `uv run pytest tests/test_appeal_print.py -x -q` | 37 passed | PASS |
| SC3 ODT XML 層（copies） | `uv run pytest tests/test_appeal_print.py -k copies -v` | 3 passed | PASS |
| 欄位組裝＋注入 | `uv run pytest tests/test_appeal_print.py -k "odt or mapping" -v` | 14 passed | PASS |
| e2e/base/security | `uv run pytest tests/test_appeal_print.py -k "e2e or base or security" -v` | 10 passed（soffice 實跑） | PASS |
| config/cli | `uv run pytest tests/test_appeal_print.py -k "config or cli" -v` | 12 passed | PASS |
| SC2 真實資料流 | `uv run python` 內嵌：AppealDraft→JSON→render_appeal_print | 30,831 bytes filled ODT、warnings=[] | PASS |
| CLI 完整流程 | `python scripts/build_appeal_print.py appeal.json case_payload.json out/appeal.pdf` | exit 0、`申復清單_appeal.pdf` 存在、3 頁 | PASS |
| SC1 PDF 文本層全欄位 | pypdf 提取 15 欄位值 | 無 missing keys | PASS |
| SC3 PDF 層三聯差異 | pypdf 每頁提取＋「初核/審查委員」區分鍵 | 僅第 2 頁含核定欄；第 1/3 頁無 | PASS |
| 官方模板結構契約 | 直接解包 30396_1 ODT（ET 解析） | 9 tables；主表 18 rows；資料行 15 cells；頭表 17 cells；第二聯 row1＝核定欄 | PASS |
| 資產完整性 | `sha256sum *_print_base.odt` vs sidecar | `dbd51c1e…83137` 一致 | PASS |
| 相關既有套件（無回歸） | test_appeal/test_appeal_xml/test_safe_paths/test_config/test_doc_converter | 69 passed | PASS |
| 其他子集（無回歸） | record_aggregator/comparator/parsers/case_store/rule_repository 等 | 138＋77＋80 passed、2 skipped | PASS |
| server/e2e/llama 子集 | test_server_case_store_integration/e2e_pipeline/llama_smoke | 19 passed、2 failed（環境性 Errno 30，data/ 唯讀，已記錄於 deferred-items.md，與本 phase 無關） | PASS（環境限制） |

### Probe Execution

本 phase 依 RESEARCH Validation Architecture 以 pytest `-k` 分組為探針，無獨立 shell probe 腳本；上表全部為真實執行結果（非 SUMMARY PASS 計數轉述）。

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| REQ-paper-appeal-print | ROADMAP SC1/SC2/SC3＋REQUIREMENTS.md | PDF 排版輸出通道，直接消費 AppealDraft 不重建資料模型，版面與官方三聯式範本逐欄一致，三聯版式差異（第二聯核定欄）正確反映 | ✓ VERIFIED | 37 tests＋手工資料流＋PDF 文本層/三聯交叉驗證（見 Goal Achievement） |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `.planning/phases/11-paper-appeal-print/11-02-PLAN.md` | 26 | frontmatter 聲稱 `template.py` exports `BASE_TEMPLATE_SHA256_PATH`，實作改以 `__init__.py::_load_expected_sha256` 動態定位 sidecar（無此常數） | WARNING（非 blocker） | 功能目標（T-11-06 模板 sha256 校驗）已達成且被測試覆蓋（資產 hash 一致＋缺 sidecar 拒絕）；屬計畫措辭與實作偏差，不影響 SC/驗收標準 |
| `src/elc_audit_engine/generators/appeal_print/field_mapping.py` | 179-184 | 「內容」欄的 `f"{order_code} {order_name}"` 拼接分支（submission.orders 含 name 時）無直接單測 | WARNING（低風險） | 測試僅斷言 content＝order_code（orders 無 name 鍵）；拼接邏輯簡單且不影響 SC1 欄位對應契約，屬測試覆蓋面觀察 |

### Human Verification Required

無必需項目——所有 Success Criteria 的內容/順序/佈局已由官方模板原樣套用（D-02）＋bbox 量測對齊 Golden（26.4pt/779.3pt vs 27pt/779pt）＋PDF 文本層全欄位＋頁數/三聯差異交叉驗證機器化完成。**建議（非 gate）**：正式啟用前，使用者可將產出 PDF 與官方 `30396_4` 目視比對一次（框線來自官方模板，預期無差異）。

---

## VERIFICATION COMPLETE

| Requirement | Verification | Verified? |
| ----------- | ------------ | --------- |
| SC1 PDF 版面與官方三聯式範本逐欄核對一致 | 官方模板結構解包實證（9 tables/18 rows/15 cells/17 cells）+ `-k mapping`×7＋`-k odt`×5＋e2e 3 頁＋手工 PDF 文本層 15 欄位值全數出現＋bbox 對齊 Golden（26.4pt/779.3pt） | ✅ VERIFIED |
| SC2 由既有 AppealDraft 資料直接生成 PDF，不需另建資料模型 | 手工資料流 AppealDraft→render_appeal_json→render_appeal_print（payload dict 驅動，無新模型）+ CLI 完整流程 exit 0 產出 3 頁 PDF | ✅ VERIFIED |
| SC3 三聯版式差異（第二聯核定/複核/初核/審查委員欄，留空供健保署複核）正確反映 | 官方模板實證第二聯 row1＝核定欄 + `-k copies`×3 ODT XML 層斷言（第二聯有/第一三聯無/留空）+ 手工 PDF 層交叉驗證（區分鍵「初核/審查委員」僅第 2 頁） | ✅ VERIFIED |

**Score:** 3/3 must-haves verified
**所有必須項目通過。Phase goal 已達成。**

## Blocked Requirements

無——無 FAILED 或 UNCERTAIN 必須項目。

## Auto-Consistency

- SUMMARY 聲稱（11-01/02/03）的測試數與實際一致：11-01 稱 11 passed（mapping×6＋odt×5）——現實際 37 測試為 3 plan 累積；11-02 稱 22 passed；11-03 稱 34 passed；orchestrator code-review should-fix（8e8924d）＋3 測試＝37。**各 plan 的測試數皆與對應時點的實際相符，無矛盾。**
- 模板 sha256：SUMMARY 聲稱 `dbd51c1e173ceda53fcd28df6a220a967515988318b796437be946cd99a83137`；實測 sha256sum＝同值、sidecar 一致。
- 最後 commit `8e8924d`（fix(11): code review should-fixes）與環境事實一致；環境性失敗（data/ 唯讀 Errno 30）與 11-03-SUMMARY 及 deferred-items.md 記載完全一致（2 個 server_case_store 整合測試）。

## Self-Check

- [x] 先前 VERIFICATION.md 檢查（Step 0）：無既有報告（本報告為 initial）
- [x] Must-haves 建立：ROADMAP SC1/SC2/SC3（roadmap_truths）＋3 份 PLAN frontmatter truths 交叉核對，無縮減
- [x] 三層驗證（exists/substantive/wired）＋Level 4 資料流：全 artifacts VERIFIED、WIRED、FLOWING
- [x] Key links 全數 WIRED（AppealDraft→render→fill→soffice→PDF；CLI→write；hash 校驗接線）
- [x] 對抗性抽查：直接解包官方模板、PDF 文本層全欄位、SC3 PDF 層三聯差異、資產 hash、CLI 真實流程
- [x] 相關套件無回歸（69＋138＋77＋80 passed、2 skipped）；環境性 2 failed 與本 phase 無關
- [x] Anti-patterns 掃描：2 個 WARNING（PLAN exports 措辭偏差、name 拼接分支未直接單測），均非 blocker
- [x] Human verification：無必需項目（視覺目檢列為建議）
- [x] status 判定：passed（score 3/3，無 gaps、無 deferred、無 human gate 項目）
- [x] VERIFICATION.md 已建立

## 11 - Review and Phase Complete (Exit Criteria)

**VERIFIED** — Phase 11（紙本申復清單列印）三項 Success Criteria 全數達成：
1. **SC1** 版面逐欄一致（內容/順序/佈局機器驗證完整：官方模板實證＋注入契約＋PDF 文本層＋bbox 對齊）。
2. **SC2** 直接消費 AppealDraft（payload dict 驅動、無新資料模型），排版層與 Phase 7 資料層職責分離。
3. **SC3** 三聯差異以官方模板第二聯為準（核定/複核/初核/審查委員欄在第二聯，留空供健保署複核；ODT XML 層＋PDF 層雙重驗證）。

產出通道完整可用：`scripts/build_appeal_print.py` CLI（appeal JSON → 一案一 3 頁 PDF，三聯一次列印、>15 行分頁、缺欄誠實留空＋警告、第二聯核定欄留空、PHI 防線全接）。37 個 appeal_print 測試全綠，相關既有套件無回歸。可進入下一階段。

---

_Verified: 2026-08-08T04:21:06Z_
_Verifier: Claude (gsd-verifier)_
