# 32-04-SUMMARY: 校正精靈點選欄位與無 JSON 改進 (B7)

## 執行成果摘要
- 依據 Plan 32-04（需求 B7），完成了 Windows HIS 校正精靈的去 JSON 化與點選控制項機制：
  1. 實作純函式模組 `deploy/windows_agent/pick_control.py`：
     - `element_at_point`：支援多種 bounds 格式，挑選包覆點且面積最小的目標元素。
     - `selector_from_element`：轉換 UI 元素為乾淨選擇器（優先採 `automation_id`，次選 `name` + `control_type`）。
     - `pick_selector`：優先尋找已取得鍵盤焦點（focused）之元素；次選以座標點定位之控制項。
     - `default_point_fn`：跨平台安全（非 win32 平臺回傳 None，Linux 可安全 import）。
  2. 重構 `deploy/windows_agent/calibration_view.py`：
     - 徹底移除 `askstring`、`import json` 與任何 JSON 輸入提示。
     - 實作模組層級純函式 `describe_item` 與 `handle_pick_result`。
     - 「修正」按鈕改為「我來點選欄位」，引導使用者 5 秒內點選 HIS 欄位，由程式自動擷取選擇器。
     - 擷取失敗時自動標記跳過並跳出提示「找不到這個欄位，請聯絡安裝人員。其他欄位仍可繼續設定。」，程式不中斷。
  3. 新增單元測試：
     - `tests/test_pick_control.py`（4 passed）
     - `tests/test_calibration_view_no_json.py`（4 passed）
     - `tests/test_calibration_wizard.py`（8 passed 全部維持綠燈）

## 驗證輸出
```
============================== 16 passed in 1.13s ==============================
```

## 產出狀態
- Plan 32-04 完成。
