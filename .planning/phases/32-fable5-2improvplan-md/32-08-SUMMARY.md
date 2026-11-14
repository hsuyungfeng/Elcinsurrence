# 32-08-SUMMARY: 系統狀態監控與容量取樣預警實作 (D3, D5, D6)

## 執行成果摘要
- 依據 Plan 32-08（需求 D3、D5、D6 及裁示 D-32-13），完成主機端容量管理、系統狀態 API 與狀態頁面：
  1. 容量取樣與成長率預測模組（`src/elc_audit_engine/capacity.py`）：
     - 實作 `directory_size_bytes`：遞迴計算目錄實體大小，不跟隨符號連結。
     - 實作 `growth_bytes_per_day`：最小平方線性迴歸計算每日成長斜率（需至少 7 筆有效樣本）。
     - 實作 `days_until_full` 與 `classify_runway`：依 D-32-13 裁示，門檻設為黃燈 ≤180 天、紅燈 ≤90 天，可提前數個月預警（D-32-08）。
     - 實作 `record_daily_sample`：原子化寫入 JSON 取樣記錄，同日覆寫，上限 400 筆。
     - 模組嚴格恪遵 D-32-04 永久保存原則，程式碼不含任何刪除檔案指令（無 `unlink`、`rmtree`、`os.remove`）。
  2. 系統狀態與深度健康檢查 API（`src/elc_audit_engine/api/routes/status.py`）：
     - `GET /api/status`：一頁整合 6 項指標（審核引擎、本機 AI 模型、磁碟空間與成長預警、資料庫、備份、各診間連線），回傳紅黃綠燈與清晰中文白話說明。
     - `GET /api/health/deep`：當任一核心指標出現紅燈時回傳 503，其餘放行 200。
     - 當本機 LLM 停止時，LLM 檢查項顯示紅燈（「AI 審核暫停中，其餘功能正常」），但一般 `GET /api/health` 存活檢查仍維持 200，不中斷整體服務。
     - 全程嚴格保護個資，狀態回應絕不洩漏病歷或病人資訊。
  3. 系統狀態前端頁面：
     - 提供 `static/status.html` 與獨立外部腳本 `static/js/status.js`，每 30 秒輪詢更新狀態，符合 CSP 規範。
     - 提供 `GET /status` 路由直接瀏覽。
  4. 測試驗證：
     - 解除 `tests/test_capacity_forecast.py` 與 `tests/test_status_api.py` 的 xfail。
     - 全部 8 個單元與整合測試全數通過（8 passed in 8.52s）。

## 驗證輸出
```
============================== 8 passed in 8.52s ===============================
```

## 產出狀態
- Plan 32-08 完成。
