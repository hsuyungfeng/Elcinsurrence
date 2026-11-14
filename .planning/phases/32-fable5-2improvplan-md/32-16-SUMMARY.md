# Phase 32 Plan 16 Summary: E8 工作台檔案拆分與 CSP 強化

## 1. 任務概述
- **目標**: 將 4129 行之單檔 `static/index.html` 拆分為 HTML（818行）、外部樣式 `static/css/workbench.css`（630行）、外部腳本 `static/js/workbench.js`（2780+行）。
- **事件委派**: 移除 `static/index.html` 全部 89 個 inline `on*` 事件屬性，以 `data-action`、`data-change-action`、`data-input-action` 與 document 層級委派取代，並建立 `ACTIONS` 白名單映射。
- **CSP 強化**: 將 `script-src 'self' 'unsafe-inline'` 收緊為 `script-src 'self'`；`style-src` 因仍有 292 處 inline style 屬性暫保留 `'unsafe-inline'`（待 32-18 / E3 處理）。
- **附加清理**: 同步將 `static/clients.html` 之 inline `<script>` 抽取至 `static/js/clients.js`，避免 CSP 阻擋。
- **首次設定導向**: `workbench.js` 初始化時查詢 `/api/setup/state`，若 `needs_setup === true` 則導向 `/setup`（對接 32-13）。

## 2. 成果與驗證
- **新增檔案**:
  - `static/css/workbench.css` (630 行)
  - `static/js/workbench.js` (2780+ 行)
  - `static/js/clients.js` (245 行)
  - `tests/workbench_source.py` (提供 `read_workbench_source()` 供測試共用)
  - `tests/test_workbench_static.py` (6 個測試項目全綠)
- **修改檔案**:
  - `static/index.html` (無 `<style>`、無 inline `<script>`、無 `on*` 事件屬性)
  - `static/clients.html` (引用外部 `clients.js`)
  - `src/elc_audit_engine/api/security.py` (CSP 移除 `script-src 'unsafe-inline'`)
  - `tests/test_monthly_report_ux.py`, `tests/test_stage2_3_buttons.py`, `tests/test_ingest.py` (改用 `read_workbench_source`)
- **語法與測試驗證**:
  - `node --check static/js/workbench.js` PASS
  - `node --check static/js/clients.js` PASS
  - `! grep -nE ' on[a-z]+="' static/index.html` PASS (0 inline handlers)
  - `tests/test_workbench_static.py` + `tests/test_stage2_3_buttons.py` 9 passed

## 3. 威脅模型處置
- T-32-16-01 (CSP script-src): 移除 `unsafe-inline`，徹底阻斷 DOM/反射 XSS 執行任意 inline script。
- T-32-16-02 (ACTIONS 白名單): 委派只透過靜態白名單呼叫，禁止 `window[action]` 動態調用。
- T-32-16-03 (style-src): 暫保留 `unsafe-inline`，由 32-18 接續收斂。
