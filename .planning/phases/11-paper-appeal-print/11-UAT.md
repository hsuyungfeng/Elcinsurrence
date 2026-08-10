---
status: complete
phase: 11-paper-appeal-print
source:
  - .planning/phases/11-paper-appeal-print/11-01-SUMMARY.md
  - .planning/phases/11-paper-appeal-print/11-02-SUMMARY.md
  - .planning/phases/11-paper-appeal-print/11-03-SUMMARY.md
started: 2026-08-08T04:32:31Z
updated: 2026-08-10T01:00:00Z
completed: 2026-08-10
---

## Current Test
<!-- OVERWRITE each test - shows where we are -->

(none — all 7 tests complete)

## Tests

### 1. CLI 产出三聯 PDF
expected: 執行 build_appeal_print.py（3 參：appeal.json + case_payload.json + 輸出路徑）後，終端顯示「已成功輸出申復清單 PDF：<路徑>」且 exit 0，輸出路徑出現 PDF 檔案。
result: pass

### 2. 三聯版式與官方模板一致
expected: 產出 PDF 恰為 3 頁（每聯一頁）。版面與官方 30396_4 範本一致：表頭三區塊（院所代號/名稱、保險對象、原申報類別日期）、14 欄明細表＋合計列、下方說明文字。
result: pass

### 3. 第二聯含核定欄（三聯差異）
expected: 核定/複核/初核/審查委員 欄位僅出現在第 2 頁（健保署存查聯），第 1、3 聯無此欄。
result: pass
notes: pdftotext -layout 逐頁比對確認：「核 定／複 核／初 核／審查委員」欄位列僅出現於第 2 頁，第 1、3 聯無此列（第 1、3 聯正文中的「複核」字樣屬固定法定文字，非此填列欄）。

### 4. 逐欄資料正確出現
expected: PDF 中出現：代號字碼（01015C）、醫療院所名稱、案件分類（D2）、流水號、身份證字號（遮罩值如 F10291****，非完整字號）、姓名、傷病名稱、審查科別、醫令序、合計列；值與輸入一致。
result: pass
notes: |
  以 data/output/_目檢/{appeal_demo.json, case_payload_demo.json} 為輸入來源逐欄比對 pdftotext -layout 產出：
  代號字碼 01015C ✓／醫療院所名稱 示例醫療院所 ✓／案件分類 D2 ✓／流水號 18 ✓／
  身份證字號 F10291*** * （遮罩，非完整號碼）✓／姓名 陳小明 ✓／傷病名稱 J189 ✓／
  審查科別 內科 ✓／醫令序 1／醫令代碼 E5002C ✓／數量 1、點數 300 ✓／合計列「人次 1」✓／
  理由欄 p8+p9 文字逐字相符 ✓。全部欄位與輸入 JSON 一致，三聯皆同步正確。

### 5. 缺欄誠實降級＋警告呈現
expected: 不帶 case_payload.json（僅 appeal.json）執行時，輸出仍成功（exit 0），但成功訊息後逐條列印「警告：身份證字號」「警告：姓名」等缺失欄位名清單。
result: pass
notes: |
  `.venv/bin/python scripts/build_appeal_print.py data/output/_目檢/appeal_demo.json "" <out.pdf>`
  exit 0，成功訊息後逐行列印：警告：身份證字號／警告：姓名／警告：傷病名稱／
  警告：審查科別／警告：數量／警告：金額。僅印欄位名、不印值全文，符合 T-11-03。

### 6. 院所設定可由 config/env 驅動
expected: PDF 頭欄的院所代號/名稱來自 config/facility.json（01015C/示例醫療院所）；設 FACILITY_CONFIG_PATH 指向另一份 json 後再執行，頭欄改用新值。
result: pass
notes: |
  預設（無 env）：頭欄 01015C／示例醫療院所（測項 4 已驗證）。
  設 FACILITY_CONFIG_PATH 指向替代 facility_alt.json（code=09988B, name=測試替代診所）後
  重新執行，pdftotext -layout 確認頭欄改為 09988B／測試替代診所，exit 0。

### 7. 錯誤處理友善（不存在的檔案／非法檔名）
expected: 傳入不存在的 appeal.json → stderr 顯示「錯誤：找不到檔案 …」且 exit 1；傳入含路徑穿越的輸出檔名（如 ../x）→ 顯示「錯誤：不安全的檔名」且 exit 1，不產生檔案。
result: pass
notes: |
  7a（不存在的 appeal.json）：pass — stderr 顯示「錯誤：找不到檔案 '...'」，exit 1。

  7b（路徑穿越輸出檔名 `../x.pdf`）：**初次測試 FAIL**，已修復並重測 pass。

  **初次發現（FAIL）**：未拒絕，反而 exit 0 並成功寫出 `../申復清單_x.pdf`
  （實際落在倉庫上一層 `/home/hsu/Desktop/`，已在 UAT 過程中人工確認並清除該
  測試產物）。根因（`scripts/build_appeal_print.py:125-131`）：程式在呼叫
  `safe_filename()` 之前，先用 `os.path.dirname(output_pdf_path)` /
  `os.path.basename(...)` 把路徑拆成 `output_dir` 與 `base` 兩段，safe_filename
  只驗證了 `base`（basename 後的 "x"，本身合法），`../` 穿越部分進了
  `output_dir`，完全未經任何白名單／路徑穿越檢查就直接傳給 `write_appeal_print`
  當輸出目錄使用。這正是 `safe_paths.py` docstring 明確警告要避免的「先取
  basename 等於把攻擊悄悄清洗成合法檔名」模式（P1-3 同源），只是這次漏在呼叫端
  （CLI 手動拆解 output_pdf_path），而非 safe_filename() 本身失守。

  **修復**：`build_appeal_print.py` 新增穿越檢查——`output_pdf_path` 提供時，
  先用 `os.pardir in output_pdf_path.split(os.sep)` 偵測路徑各段是否含 `..`
  穿越成分，一律拒絕（「校驗後拒絕、非清洗取代」，與 safe_filename 同一原則）；
  刻意不採「限制在固定根目錄之下」的方案，因 CLI 呼叫端本可合理指定任意絕對／
  相對輸出路徑（測項 1/6 本身即用 /tmp 下的絕對路徑），限制固定根目錄會誤傷
  合法用法（實測過，故改用穿越成分偵測）。

  **重測驗證**：7a 迴歸 pass；7b `../x.pdf` → 「錯誤：不安全的檔名 '../x.pdf':
  輸出路徑含路徑穿越成分」，exit 1，未產生任何檔案；測項 1/6 合法絕對路徑輸出
  迴歸 pass（exit 0，正常產出）。`tests/test_appeal_print.py` 37/37 pass。

## Summary

total: 7
passed: 7
issues: 0
pending: 0
skipped: 0

## Gaps

- **[RESOLVED] 路徑穿越漏洞（測項 7b）**：`build_appeal_print.py` 的
  `output_pdf_path` 自訂輸出路徑參數原未做路徑穿越檢查，可寫出至專案目錄以外
  任意可寫入位置（已實測外洩至倉庫上一層目錄，PHI 相關輸出檔有資料外洩風險）。
  已於本次 UAT 過程中修復並重測通過，見測項 7 notes。
