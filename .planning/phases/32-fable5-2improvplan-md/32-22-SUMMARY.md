# Phase 32 Plan 22 Summary: E1–E9 整合驗證、CSP 嚴格合規與煙霧測試

## 1. 任務概述
- **E1–E9 整合驗證**: 全面檢驗醫師模式切換（E1）、步驟化進度條（E2）、無障礙字級/點擊區（E3）、白話按鈕文字（E4）、破壞性操作隔離（E5）、空白引導（E6）、三段式錯誤（E7）、檔案拆分（E8）、三軌統一（E9）。
- **CSP 嚴格合規**: 驗證所有 Web 端點（`/`, `/clients`, `/status`, `/setup`）的回應標頭 `script-src` 僅限 `'self'`，完全阻斷 `'unsafe-inline'`。
- **靜態資產健全**: 驗證所有 `static/*.html` 檔案均無 inline `<script>`、無 inline `on*` 事件屬性，且引用的外部 JS 與 CSS 檔案皆真實存在、非空且為無 BOM 之 UTF-8 編碼。
- **核心路徑煙霧測試**: 建立 `tests/test_workbench_e2e_smoke.py`，驗證四大作業容器、動態元件與 ACTIONS 白名單全部精確對應。

## 2. 成果與驗證
- **新增檔案**:
  - `tests/test_workbench_e2e_smoke.py` (包含 CSP、四大視圖容器、ACTIONS 繫結完整性、UTF-8 編碼等測試)
- **修改檔案**:
  - `tests/test_workbench_static.py` (新增全端點 CSP 嚴格性檢驗、全靜態引用檔案存在性檢驗)
- **測試結果**:
  - `tests/test_workbench_static.py` + `tests/test_workbench_e2e_smoke.py` 共 21 passed，0 failed。

## 3. 威脅模型處置
- T-32-22-01 (Tampering / XSS): 移除 `script-src 'unsafe-inline'` 並透過全端點自動化斷言守護，從根本防杜任何 DOM/反射型 XSS 注入執行任意腳本。
