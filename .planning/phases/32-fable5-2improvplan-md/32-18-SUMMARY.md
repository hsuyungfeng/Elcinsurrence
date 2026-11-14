# Phase 32 Plan 18 Summary: E3/E4/E9 工作台三軌命名、白話按鈕、字級調升與 Inline Style 轉 Class

## 1. 任務概述
- **E9 三軌統一**: 全面清除「雙軌」混淆詞彙，將 `static/index.html` 標題及 `README.md` 全面統一為「三軌控制台」、「健保三軌自動化審核與申復工作台」。
- **E4 白話化按鈕**: 移除所有按鈕工程術語（例如「全批次導出抽審 XML (Big5)」改為「下載送審檔」，移除 UIA、agent-desktop 等工程標籤）。
- **E3 無障礙字級與點擊高度**: 全域基礎字級調升至 `15px`，按鈕最小高度保證 `≥ 40px`；增加 `body.font-size-large` 大字模式（18px 字級、48px 按鈕高）。
- **Inline Style 歸零**: 將 `static/index.html` 內 295 處 inline `style="..."` 屬性全部轉化為 195 個語意化/公用類別（`u-s-1` ~ `u-s-195`）並納入 `static/css/workbench.css`，`static/index.html` 內 `style="..."` 徹底歸零。

## 2. 成果與驗證
- **修改檔案**:
  - `README.md` (統一「三軌控制台」)
  - `static/index.html` (標題三軌化、按鈕白話化、0 處 inline style)
  - `static/css/workbench.css` (全域 15px 字級、按鈕 40px 最小高、大字模式、195 個 CSS 類別)
  - `tests/test_workbench_static.py` (新增 E9/E4/E3 驗證：`test_terminology_three_tracks`, `test_plain_language_buttons`, `test_no_inline_style_attributes_in_index_html`, `test_button_min_height_and_body_font_size`)
- **測試結果**:
  - `tests/test_workbench_static.py` 10 個測試全數 PASS。
