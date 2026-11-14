# Phase 32 Plan 20 Summary: E1/E2/E6 工作台醫師模式、步驟化引導與空白狀態

## 1. 任務概述
- **E1 醫師模式 / 進階模式 (Doctor Mode)**: 在網頁工作台右上角提供模式切換 Toggle（預設為醫師模式），隱藏 60 多顆低頻/工程按鈕（標記為 `.advanced-only`，例如清空清單、進階規則同步等），提供清爽無干擾的診療體驗。
- **E2 步驟化進度導引 (Stepper)**: 於工作台頂部建立 `workflow-stepper`，清楚顯示「① 上傳申報檔 → ② 智慧檢查 → ③ 下載送審檔」，當前步驟醒目高亮，已完成步驟標記綠色打勾。
- **E6 空白狀態引導 (Empty State)**: 當尚無任何申報或案件資料時，顯示友善的置中空白引導卡片「目前尚無申報資料，請先上傳本月申報檔」，並提供醒目直覺的「點我上傳申報檔」動作按鈕。

## 2. 成果與驗證
- **修改檔案**:
  - `static/index.html` (加入 `#btnToggleDoctorMode`、`#workflow-stepper`、`#empty-state-guide`，將除錯/低頻按鈕標記為 `advanced-only`)
  - `static/css/workbench.css` (實作 `.doctor-mode .advanced-only { display: none !important; }`，步驟條與空白狀態樣式)
  - `static/js/workbench.js` (實作 `initDoctorMode`, `setDoctorMode`, `toggleDoctorMode`, `updateWorkflowStep`, `renderEmptyState`，並掛入 `ACTIONS`)
  - `tests/test_workbench_static.py` (新增 E1/E2/E6 驗證：`test_doctor_mode_elements`, `test_stepper_and_empty_state`, `test_doctor_mode_js_logic`)
- **測試結果**:
  - `tests/test_workbench_static.py` 13 passed，0 failed。
  - `node --check static/js/workbench.js` PASS。

## 3. 威脅模型處置
- T-32-20-01: 醫師模式切換開關屬純前端視圖收斂降噪，不涉及後端特權提升；核心 API 端點均具備嚴格的本機/信任網段防護。
