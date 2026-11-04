# Phase 23 Plan 01 Summary: 工作台視覺佈局極大化與沉浸式操作優化

## 執行成果概述

依據使用者需求指令：
`1. add F11 全螢幕按鍵與再按一次返回`
`2. 最小化利用組件浮動字幕`
`3. 宽度缩成一半。如此极大化右側的作业位置。1.2.3.階 界面大小相同`

已完成 `static/index.html` 核心前端重構與規格統一，全數自動化測試 100% 通過（包含 CSP 離線隱私規範、無外鏈資源、無 innerHTML 注入點等回歸斷言）。

---

### 1. 核心實作亮點

1. **F11 全螢幕按鍵與雙向切換**：
   - 頂部導覽列（`<header>`）右側新增沉浸式「⛶ 全螢幕」按鈕（`.fullscreen-btn`）。
   - 支援滑鼠點擊切換與全域 `F11` 快捷鍵監聽（按 F11 進入全螢幕，再按一次 F11 或 Esc 即恢復原視窗）。
   - 監聽 `fullscreenchange` / `webkitfullscreenchange` 事件，即時動態切換按鈕狀態與圖示（「⛶ 全螢幕」↔「🗗 視窗」）。

2. **左側側欄寬度縮半（280px -> 140px），極大化右側作業空間**：
   - CSS 變數 `--sidebar-width: 140px;`，左側寬度縮小一半，右側主要工作台（主診斷、SOAP、影像佐證庫、審核報告）可用空間增加 140px。
   - 側欄頂部按鈕重構為迷你圖示工具列（`➕` 鍵入、`📂` 匯入、`🧹` 清快取），在 140px 內緊湊排列無爆版。

3. **側欄組件最小化與安全 DOM 浮動字幕（Tooltip）**：
   - 機構檔案與月份狀態改為迷你一行膠囊列（`🏥 機構代號` / `📅 月份 免驗證`）。
   - 原先霸佔大垂直高度的自訂 API 金鑰與規則庫管理，改為迷你快捷標籤（`🔑 金鑰` / `📚 規則`），點擊按需展開浮動面板，平時將 90% 以上垂直空間保留給案件清單捲動。
   - 建立全域浮動字幕組件（`.floating-tooltip`），滑鼠懸停於案件項目時，浮動展示：病患姓名、身分證／病歷號、醫令代碼、完整醫令名稱、主診斷代碼、支持度判定、申報／核減點數。
   - 嚴格遵守 `test_frontend_case_list_does_not_use_innerhtml_templating` 安全規範，浮動字幕全數採用 DOM API（`createElement` + `textContent`），杜絕 XSS 風險。

4. **1. 2. 3. 階界面規格全面一致**：
   - 第 1 階當月預審（`workflow3View`）、第 2 階抽樣事前預審（`workflow1View`）、第 3 階核減事後申復（`workflow2View`）頂部統一採用 `.workflow-topbar`（高度與 padding 規格一致）。
   - 主體全部包裹在 `.view-scroll-content`，三軌切換時外框與容器尺寸無跳動、對齊穩固。

---

### 2. 驗證與測試結果

- `tests/test_ingest.py`：26/26 passed（前端無外鏈、無危險 innerHTML、契約一致性通過）。
- `tests/test_boundary_safety.py` & `tests/test_services_refactor.py`：35/35 passed。
- `ruff check .`：All checks passed。
