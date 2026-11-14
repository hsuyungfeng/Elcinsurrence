# Phase 32 Plan 21 Summary: E5/E7 破壞性按鈕隔離與三段式白話錯誤提示

## 1. 任務概述
- **E5 破壞性按鈕隔離至下拉選單**:
  - 將主畫面直接暴露的清空抽樣清單、清空申復清單、清空申報批次等高風險按鈕收納入「⋯ 更多」下拉選單（`#moreActionsMenu`）。
  - 實作二次確認對話框（`#confirm-destructive-modal`），明確告知「此動作將清除畫面上的暫存資料，您已匯出的送審檔案不受影響」，防範日常手滑誤觸。
- **E7 三段式白話錯誤訊息**:
  - 實作前端三段式錯誤訊息元件（`#structured-error-modal`）與 `showStructuredError({ event, dataSafety, nextAction, rawError })`：
    - ① 狀況說明（白話告知發生什麼事）
    - ② 資料狀態（強調「您的病歷與送審檔案已經完整儲存在主機中，請放心」消除醫師焦慮）
    - ③ 建議動作（提供具體可行的下一步，例如等待 30 秒後重試或查看系統狀態）
  - 提供一鍵「複製診斷資訊」次要動作，方便工程人員排錯，介面不展示生硬 traceback 或 raw code。

## 2. 成果與驗證
- **修改檔案**:
  - `static/index.html` (新增 `⋯ 更多` 下拉選單、`#confirm-destructive-modal` 與 `#structured-error-modal`)
  - `static/css/workbench.css` (實作下拉選單、危險動作樣式、對話框與三段式卡片樣式)
  - `static/js/workbench.js` (實作 `toggleMoreMenu`, `openDestructiveModal`, `executeDestructiveConfirm`, `showStructuredError`, `copyDiagnosticInfo`，並在 `ACTIONS` 註冊)
  - `tests/test_workbench_static.py` (新增 E5/E7 驗證：`test_destructive_buttons_isolated`, `test_structured_error_function`)
- **測試結果**:
  - `tests/test_workbench_static.py` 15 passed，0 failed。
  - `node --check static/js/workbench.js` PASS。

## 3. 威脅模型處置
- T-32-21-01 (Information Disclosure): 前端錯誤提示嚴格白話化過濾，禁止直接輸出後端例外堆疊或內部路徑，敏感除錯資訊僅在醫師點選「複製診斷資訊」時取得非敏感摘要。
