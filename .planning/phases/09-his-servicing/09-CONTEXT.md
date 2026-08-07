# Phase 9: HIS 服務化（本機可驗證範圍） - Context

**Gathered:** 2026-08-05
**Status:** Ready for planning
**Source:** /gsd-plan-phase 9 內嵌決策收集（使用者裁示）

<domain>
## Phase Boundary

把 Phase 1-8 的核心引擎包成 **HIS 可呼叫的服務**。範圍界定在**本機即可驗證完成**的部分：認證授權、案件狀態機、任務佇列、申復 XML 產出。

**明確不在本範圍**（已於 2026-08-05 拆為 Phase 10，阻塞於外部依賴）：
- 雲端病歷 Provider 接 doctor-toolbox（需存取權）
- NHI_EIIAPI wrapper（需 Windows＋VPN＋SAM 實機）
- Local Gateway 七元件

**拆分理由**：含阻塞項的 phase 永遠無法通過 verify，會汙染 phase 完成訊號。

### 已落地待追認的既有實作

本 phase 需把下列**已 commit 但未納 phase 管理**的工作對映進 PLAN（標記已完成）：

| 範圍 | Commit | 內容 |
|---|---|---|
| Flask API 接真實引擎 | `b80cd08` | `/api/sampling/audit` → `run_presubmission_check`；`/api/appeal/generate` → `build_appeal_draft`；安全預設（綁 127.0.0.1／debug=False／錯誤脫敏／入參校驗） |
| 批次匯入 | `56d9902` | `ingest/` 模組（media/sampling/ocr_rows）＋ `/api/sampling/import`、`/api/appeal/import`；落盤 `data/uploads/*.json` |
| 紙本表格結構化 | `8c38a19` | `ingest/table_ocr.py` PP-StructureV3（可選依賴＋自動降級回 tesseract） |
| 安全清尾 | `f6ac775` | P1-5 前端 XSS＋CSP／P1-2 prompt 定界／P1-3 路徑穿越 |

</domain>

<decisions>
## Implementation Decisions

### 認證授權（首項工作，使用者裁示 2026-08-05）

- **機制＝API key（服務間認證）**，不做 JWT／mTLS。理由：呼叫方是 HIS 服務而非瀏覽器使用者，無需 session／登入頁。
- key 以 **constant-time 比對**（`hmac.compare_digest`），不可用 `==`（時序側通道）。
- key **存環境變數／設定檔，不進版控**。格式支援多個呼叫方識別（如 `ELC_API_KEYS="his1:key1,his2:key2"`），以便審計日誌能記錄「是誰呼叫」。
- **搭配存取審計日誌**：調閱病歷資料必須可追蹤（呼叫方識別、時間、端點、狀態碼）。
- 審計日誌**不得記錄 PHI 本體**（不記 SOAP 全文、病歷號、姓名）——只記識別碼層級的存取事實。與 P0-3／PHI 防護一致。
- 既有 `/` 靜態頁與健康檢查類端點不應被 API key 擋死（前端需可載入）；**病歷資料端點一律需認證**。

### 案件狀態機（使用者裁示 2026-08-05）

- **狀態機＋SQLite 持久化**，取代目前 `data/uploads/*.json` 的無狀態落盤。
- SQLite 為既有技術棧（規則庫 `data/db/rules.sqlite3` 已用），**零新依賴**——符合 D2 個資不出本機。
- 狀態集合：`imported → parsed → reviewing → reviewed → appealed → submitted`，另有 `failed` 旁支。
- **非法轉換必須拋例外，不得靜默允許**（例：`submitted → imported` 不可）。與 P1-1／P0-2／P1-3 同源原則：**系統故障必須與業務結論可區分，不得靜默產生看似正常的結果**。
- 需保留**轉換歷史**（`case_transitions`），不只當前狀態——申復流程需可追溯。
- **任務佇列先做同步版**（狀態欄位即佇列），**不引入 Celery／Redis**。理由：目前單機部署，新增 broker 服務與 D2 雲端免議相比偏重。

### Package Builder（申復 XML）

- `appeal_{流水號}.json` 已含 p1-p9 醫令段欄位（Phase 7 產出），本 phase 將其**序列化為申復 XML**。
- 依 `officialdocument/電子申復文件格式/` 的**輸出**格式規格（注意：這些規格書是申復輸出格式，**不得**用來建模核減輸入檔——見 D-14a/D-14d 教訓）。
- 已知待補欄位：p3 改支序號／p4 成數／p5 數量目前為 null（待真實改支檔與院所填報）；t38/t39 總計與 A001 綜整屬本層。

### 剩餘範圍裁示（2026-08-07，接續 09-RESEARCH.md 的 Open Questions）

- **edata（申復醫令統扣明細段）不納入本次範圍**：目前案件皆為單筆醫令申復（非統扣類），本次只做 `tdata`＋`ddata`＋`pdata`。若之後真的出現統扣類案件（案件分類為 `0`），再開新任務補上。
- **tdata 加總欄位（t6-t39）先做最小可行版本**：單一案件情境下大部分加總欄位可依官方規則省略（無資料不輸出標籤）。完整「案件分類→t欄位」對照表與多案件批次彙整邏輯，留待有真實批次申復需求時再擴充，不在本次任務範圍。
- **重複匯入同一批案件（case_id 衝突）一律拒絕並回報衝突**：`DuplicateCaseError` 直接讓該筆匯入失敗並回報使用者，不做靜默覆寫。與專案一貫「系統故障需可見」原則一致。
- **申復 XML 產出方式：先做背景腳本，不做 API 端點**：`scripts/build_appeal_xml.py` 之類，輸入 `appeal_{流水號}.json` 或案件資料、輸出 XML 檔案到本機路徑。不涉及新端點、認證豁免清單審查、zip 打包等額外複雜度，先驗證欄位對映與 Big5 編碼正確性。

### Claude's Discretion

- 認證的實作形式（decorator vs before_request）、key 載入與快取細節
- SQLite schema 具體欄位、索引、migration 方式
- 狀態機的實作形式（顯式轉換表 vs 列舉方法）
- 審計日誌的輸出目標（檔案 vs SQLite 表）與輪替策略
- 測試的組織方式與替身注入點

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 專案狀態與規劃
- `.planning/ROADMAP.md` — Phase 9／Phase 10 定義與拆分理由
- `.planning/STATE.md` — 完整專案脈絡、歷次修復教訓、carry-forward 事項
- `.planning/REQUIREMENTS.md` — REQ-phase2-his-integration
- `.planning/.continue-here.md` — **BLOCKING CONSTRAINTS 與 Critical Anti-Patterns（失敗換來的教訓，開工前必讀）**

### 全項目審查與剩餘技術債
- `deepflash4improve.md` §7.2/§7.3 — P0/P1/P2 清單與架構差距矩陣
- `deepflash4improve.md` §7.5/§7.6 — 已完成修復紀錄（P0-1/P0-2/P1-1；P1-2/P1-3/P1-5）
- **仍未處理**：P1-4（CSV 內容 hash＋ChromaDB 版本綁定）、全部 P2

### 現行實作（本 phase 要延伸的對象）
- `server.py` — 現行 Flask 端點、安全標頭（`@app.after_request`）、入參校驗、統一錯誤脫敏
- `src/elc_audit_engine/pipeline.py` — **兩個入口**：`run_presubmission_check`（Review Service，唯讀）／`run_case_pipeline`（Appeal Service，寫檔）。服務化拆分直接沿用此切分。
- `src/elc_audit_engine/ingest/` — 匯入模組（media／sampling／ocr_rows／table_ocr）
- `src/elc_audit_engine/safe_paths.py` — `safe_filename()` 路徑防線（新端點若組檔名必須用）
- `src/elc_audit_engine/prompt_safety.py` — `fence()` prompt 定界（新 LLM 呼叫必須用）
- `src/elc_audit_engine/generators/appeal.py` — `appeal_{流水號}.json` 契約（p1-p9）
- `README.md`「核心 REST API 規格」＋「批次匯入」 — 現行 API 契約

### 規格文件
- `officialdocument/電子申復文件格式/` — 申復**輸出**格式規格（Package Builder 依據；**不得**用於建模輸入檔）
- `電子抽審.md` §四 — sTypeCode API 參數（Phase 10 用，本 phase 僅參考）

</canonical_refs>

<specifics>
## Specific Ideas

- 認證要能區分呼叫方身分（`his1:key1` 形式），因為審計日誌需記錄「誰調閱了病歷」——單一共用 key 會讓審計失去意義。
- 狀態機的 `failed` 旁支需記錄失敗原因，且要能與「業務結論」區分（延續 P1-1 教訓：LLM 逾時 ≠ 病歷裸奔）。
- 既有 `data/uploads/*.json` 有重啟自動載入行為，移轉到 SQLite 時需考慮既有資料的相容或遷移。
- 測試須維持**零 LLM 依賴**（現行 277 passed / 1 skipped 的基線特性），新端點測試以替身注入。

</specifics>

<deferred>
## Deferred Ideas

- 雲端病歷 Provider 接 doctor-toolbox → Phase 10（需存取權）
- NHI_EIIAPI wrapper、Local Gateway 七元件 → Phase 10（需 Windows＋VPN＋SAM 實機）
- Celery／Redis 非同步佇列 → 待實際併發壓力出現再評估
- JWT／使用者級身分（讓 D9 審核軌跡記錄「哪位醫師審的」）→ 待前端需要區分使用者時
- P1-4 CSV 內容 hash＋ChromaDB 版本綁定 → 獨立安全項，可隨時插入
- P2 全部（見 deepflash4improve §7.2）

</deferred>

---

*Phase: 09-his-servicing*
*Context gathered: 2026-08-05 via /gsd-plan-phase 內嵌決策收集*
