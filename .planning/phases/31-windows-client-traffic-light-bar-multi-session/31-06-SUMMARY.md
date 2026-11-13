# Plan 31-06 Summary: 快捷列按鈕狀態機、投影、狀態文字與位置計算 (Task 1 & Task 2)

## 成果摘要
- **模組交付**：
  1. `deploy/windows_agent/traffic_bar/__init__.py`：快捷列套件公開 API 匯出。
  2. `deploy/windows_agent/traffic_bar/bar_state.py`：純邏輯按鈕狀態機（`BarState`、`ENABLED`、`on_press`、`project`、`status_text`）。
     - 按鈕規則：紅只在 IDLE 可按；綠只在 RECORDING 可按；黃只在 CONFIRMED 或 ARCHIVE_FAILED 可按。
     - 投影規則：依 `pending_action`（防重擊）、連線狀態、活躍循環與 SoapVoice 狀態投影，支援中斷狀態判定與上傳中切換。
     - 隱私保護：狀態文字嚴格過濾病患隱私資料（PHI），僅顯示「已綁定病人」旗標、進度與時間。
  3. `deploy/windows_agent/traffic_bar/bar_position.py`：純邏輯視窗位置計算與邊界夾取。
     - `default_position`：右下角工作列上方。
     - `clamp_position`：多螢幕幾何判斷，支援子螢幕保留、邊緣夾回及脫逸回歸主螢幕預設位置。
- **測試驗證**：
  - `tests/test_bar_state.py` (5 passed)
  - `tests/test_bar_position.py` (4 passed)
  - `tests/test_traffic_bar_no_recording.py` (2 passed，AST 掃描 traffic_bar 無音訊庫依賴與 focus_force)
  - 全體 Phase 31 測試 42 passed (0.99s)。

## 偏離與路徑對應
- 無偏離。本計畫全數於 `Elcinsurrence` 倉庫實作，遵守無 git commit 規則。
