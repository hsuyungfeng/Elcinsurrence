---
phase: 09-his-servicing
plan: 01
status: complete
completed: 2026-08-07
commits:
  - 25bf03a  # feat(09-01): API key 服務間認證模組（constant-time 比對＋多呼叫方識別）
  - e537c02  # feat(09-01): 存取審計日誌模組（JSON Lines，零 PHI）
  - a2022f8  # feat(09-01): server.py 掛上 API key 認證與存取審計
tests: 354 passed / 2 skipped（本 plan 新增 38：test_auth.py 30＋test_audit_log.py 8）
---

# 09-01 SUMMARY — 認證授權＋存取審計日誌

## 交付內容

為既有 Flask 服務加上 **API key 服務間認證** 與 **無 PHI 存取審計日誌**，
使病歷資料端點不再是「無認證即可存取」。原先綁 `127.0.0.1` 只是網路層
緩解，不構成認證。

### Task 1 — `src/elc_audit_engine/auth.py`（`25bf03a`）

- `load_api_keys()`：自 `ELC_API_KEYS` 解析 `caller:key` 逗號分隔表；
  格式錯誤或未設定拋 `AuthConfigError`。
- `resolve_caller()`：以 `hmac.compare_digest` 做 constant-time 比對，
  回傳呼叫方識別；失敗拋 `AuthenticationError`。多呼叫方（his1／his2）
  各自可辨，審計日誌才能歸屬到來源機構。
- `require_api_key` decorator 保留供未來 blueprint 使用。

### Task 2 — `src/elc_audit_engine/audit_log.py`（`e537c02`）

- `record_access()`：JSON Lines 追加寫入，六欄位（時間戳／呼叫方／
  方法／路徑／狀態碼／detail）。路徑取自 `AUDIT_LOG_PATH`，預設
  `data/audit/access.log`。
- **零 PHI 設計**：只記錄「誰在何時存取了哪個端點」，不記錄請求主體。
  SOAP 全文、病歷號、患者姓名一律不進日誌。

### Task 3 — `server.py` 接線＋README（`a2022f8`）

- **`before_request` 統一強制**，而非逐端點 decorator。理由寫入註解：
  新增端點時**預設受保護**，豁免需顯式列入 `_AUTH_EXEMPT_ENDPOINTS`
  （`index`／`health`／`static`）。反向設計（預設放行＋逐一加 decorator）
  的失敗模式是「忘記加 decorator 就等於裸奔」，且在 code review 難以察覺。
- `_init_api_keys()` 啟動期載入，`AuthConfigError` **直接重拋**（fail-fast）。
  設定缺失時繼續啟動＝無認證對外開放，比啟動失敗更危險。
  `ELC_ALLOW_NO_AUTH_FOR_TESTS` 旗標僅供測試，docstring 明文警告
  「正式環境設定此旗標等同於關閉認證」。
- `errorhandler(AuthenticationError)` 回 **401**，不回 404 或「查無資料」。
- `after_request` 寫審計；`OSError` 只記 application log，**不讓已完成的
  業務回應變成 500**，但也不靜默無痕。
- 新增 `GET /api/health`（豁免認證，不含案件資料）供 HIS 與監控探測。
- README 同步認證／審計契約，並以表格追認 `b80cd08`／`56d9902`／
  `8c38a19`／`f6ac775` 四筆既有實作納入 Phase 9 管理
  （滿足 Phase 9 Success Criteria 第 1 項）。

## must_haves 驗證

| Truth | 證據 |
|---|---|
| 未帶 key → 401 且主體無病歷欄位 | `test_auth.py` 斷言 body 不含 `order_code` |
| 錯誤 key → 401（與「查無資料」可區分） | 專屬 errorhandler 回 401 |
| 正確 key → 行為與加認證前一致 | `test_ingest.py` 既有 18 測試改帶 key 後全綠 |
| `/` 與 `/api/health` 免 key | 兩測試各斷言 200 |
| 每次受保護呼叫留一列審計 | `record_access` 替身斷言 `caller_id == "his2"` |
| 審計不含 SOAP／病歷號／姓名 | 帶 `SECRET_SOAP_MARKER` 呼叫後斷言日誌序列化不含該標記 |
| `ELC_API_KEYS` 未設定即啟動失敗 | `_init_api_keys` 重拋 `AuthConfigError` |

**認證先於業務邏輯**：未帶 key POST `/api/sampling/audit` 時，斷言
`run_presubmission_check` 替身**呼叫次數為 0**——認證不是回應階段的
過濾器，是進入業務邏輯前的閘門。

## 設計決策

- **`before_request` 而非 decorator**：安全預設優先於顯式性。豁免清單
  用 Flask **endpoint 名稱**而非 path，避免 path 改寫繞過。
- **`request.endpoint is None`（未匹配路由）直接放行**交給 Flask 回 404。
  在此攔截會讓「不存在的路徑」與「存在但未授權」都回 401，反而洩漏
  路由存在與否的資訊差；且 404 本就不觸及病歷資料。
- **審計失敗不阻斷業務**：已完成的預審結果不該因日誌寫檔失敗而丟棄，
  但失敗必須在 application log 留痕。
- **測試 key 進版控無風險**：`conftest.py` 以 `setdefault` 提供固定測試
  key（非真實憑證）。必要性在於 `server.py` import 期即 fail-fast，
  完全不設定會讓任何匯入 server 的測試檔在**收集階段**就中止。

## 與既有原則的一致性

認證失敗回 401 而非 404，與 **P0-2**（DB 故障 ≠ 查無規則）、**P1-1**
（待人工 ≠ 裸奔）同源：**系統／授權故障必須與業務結論可區分**。三者
是同一條規則在不同層的展開。

## 刻意未做

- **端點尚未接 `CaseStore`**：09-02 交付的 `case_store/` 仍未與 `server.py`
  接線，`data/uploads/*.json` 遷移亦未進行——留給 **09-03** 裁示。
- **未做 rate limiting／key 輪替**：本階段目標是「不再無認證」，
  非完整的服務間授權體系。
- **`require_api_key` decorator 目前未被使用**（`server.py` 走 before_request），
  刻意保留供未來 blueprint 拆分時使用。

## 下一步

**09-03：server.py 端點接 CaseStore＋`data/uploads/*.json` 遷移。**
