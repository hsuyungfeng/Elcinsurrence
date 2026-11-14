# 32-07-SUMMARY: 健康檢查院所資訊擴充與 UDP 探索應答實作 (C4, C2)

## 執行成果摘要
- 依據 Plan 32-07（需求 C4、C2 及使用者裁示 D-32-12），完成伺服器端探索與健康檢查資訊擴充：
  1. 健康檢查端點擴充（C4）：
     - 修改 `src/elc_audit_engine/api/routes/misc.py`：`/api/health` 回傳 JSON 新增 `facility_code`、`facility_name`、`version`。
     - 嚴格過濾個資與管理敏感欄位（絕不含 `address`、`physician_name` 或病歷資料）。
     - 伺服器在院所設定缺失或資料庫未就緒時回傳空字串並維持 200 HTTP 狀態；非信任網段來源一律由 security 層阻絕（403）。
  2. UDP 廣播探索應答模組實作（C2，依 D-32-12 僅用 UDP）：
     - 實作 `src/elc_audit_engine/discovery_responder.py`：定義 `DISCOVERY_SERVICE`（`elc-audit-engine`）、`DISCOVERY_PORT`（預設 5002）與 `DISCOVERY_MAGIC`（`b"ELC_DISCOVER_SERVER_V1"`）。
     - `build_discovery_reply` 建構 5 鍵探索回應（`service`、`url`、`facility_code`、`facility_name`、`version`）。
     - `handle_datagram` 進行多層防護：封包長度 > 64 bytes 忽略、魔術字串不符忽略、非信任來源（含未信任私有網段與外部公網）忽略、回應大小限制於 512 bytes 內。
     - `start_responder` 啟動背景常駐 Daemon 執行緒處理探索廣播，並支援 `stop_event` 優雅停止。
  3. Gunicorn 啟動鉤子掛接：
     - 修改 `deploy/gunicorn.conf.py`：於 `when_ready(server)` 鉤子中自動呼叫 `start_responder`，由 Master 行程單一啟動，Worker 重啟不重複綁定埠號；支援以 `ELC_DISCOVERY_ENABLED=0` 關閉。
  4. 測試驗證：
     - 解除 `tests/test_discovery_responder.py` 的 strict xfail，新增 datagram 驗證、動態埠 E2E 探索收發、Gunicorn 鉤子測試。
     - 新增 `tests/test_health_facility.py` 驗證 C4 健康檢查規格。
     - 全部 42 個相關測試全數通過（42 passed in 9.80s）。

## 驗證輸出
```
============================== 42 passed in 9.80s ==============================
```

## 產出狀態
- Plan 32-07 完成。
