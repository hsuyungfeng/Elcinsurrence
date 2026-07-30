# Phase 2: 規則庫建置 - Context

**Gathered:** 2026-07-30
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 2 建置三層規則庫，供 Phase 3-5（解析器、病歷彙整器、三方比對器）離線查詢：

1. **結構化層（SQLite）** — `payment_rules`（醫療服務給付項目 CSV）+ `drug_rules`（藥品項查詢項目檔 CSV）
2. **條文層（PageIndex）** — `officialdocument/審查注意事項/` 全部 .doc/.docx 樹狀索引
3. **rule_mapping 預編譯快取** — 醫令代碼 → 條文位置/全文，零 LLM 離線查詢
4. **對外查詢介面** — 供下游 phase 呼叫的單一入口函式

ChromaDB 輔助層（自由文字/類似案例查詢）基礎架構也在本階段順便建立（見下方決策），但不在本階段驗收範圍內。

</domain>

<decisions>
## Implementation Decisions

### SQLite 欄位範圍
- **D-01:** `payment_rules`（來自「醫療服務給付項目...CSV」）與 `drug_rules`（來自「藥品項查詢項目檔...CSV」）只存比對器實際會用到的核心欄位：代碼、中文名稱、支付規定／給付規定文字、生效起訖日期。
- **D-02:** 不搬遷 CSV 其餘欄位（如藥品項的 AI-note、連結、劑型、藥商、ATC 代碼等 22 欄中的非核心欄位）。若未來需要，回頭查原始 CSV 或另建輔助表，不現在擴充 schema。
- 來源 CSV 欄位確認（scout codebase 時實際讀取）：
  - `醫療服務給付項目251027準確板_已優化填入支付規定.csv` → 7 欄：診療項目代碼／健保支付點數／生效起日／生效迄日／英文項目名稱／中文項目名稱／支付規定
  - `藥品項查詢項目檔260605 AI 摘要支付價大於0.csv` → 22 欄，核心取用：藥品代號／藥品中文名稱／給付規定／有效起日／有效迄日

### PageIndex 涵蓋範圍
- **D-03:** `officialdocument/審查注意事項/` 底下**全部** .docx 檔案都納入 PageIndex 樹狀索引，包含：
  - 21 份科別/一般原則審查注意事項檔案
  - 1 份 400K 的「西醫基層醫療費用審查注意事項-附表.docx」
  - 1 份 416K 的「2-2-7第二部第二章第七節手術-113.12.01.docx」（章節式健保手術規定，文件結構與科別檔案不同）
- 不同文件類型（科別條列式 vs 章節式法規）若解析結構差異過大，規劃階段需評估是否需要不同的 PageIndex 建置策略/前處理，但範圍上兩者都必須涵蓋（符合 REQ-rule-repository「涵蓋全部 .doc/.docx 文件」驗收標準）。

### rule_mapping 建置方式
- **D-04:** LLM 輔助建置：用 llama.cpp 讀取 PageIndex 條文樹，針對每個醫令代碼建議可能對應的條文位置，一次性批次生成 rule_mapping 快取。
- **D-05:** 建置完成後，查詢階段（供 Phase 3-5 使用）完全零 LLM — 只走快取查表。LLM 只在「建置」這個一次性步驟使用，不在線上查詢路徑。
- **D-06:** 20 個常見醫令代碼的人工核對驗收清單：Claude 從兩份 CSV 中挑選具代表性、涵蓋不同類型（檢查/處置/治療/藥品/手術等）的高頻項目作為候選清單草案，執行階段交由使用者最終核對每項對應的條文位置是否正確。
  - 草案挑選原則：優先選擇「支付規定」/「給付規定」欄位非空、內容具體（非純數字或 null）的項目，確保驗收時有實質條文內容可核對。
  - 範例候選（非最終清單，規劃/執行階段應正式列出 20 項）：06012C（尿一般檢查）、06013C（尿生化檢查）、05316C（PCA 病患自控式止痛）、05401C-05406C（精神復健/居家治療系列，可挑 1-2 項代表）等，並需搭配 progress.md/電子抽審.md 中已提及的 01015C、64140C。

### 對外介面設計
- **D-07:** rule_repository 模組對下游只曝露**單一查詢函式**：輸入醫令代碼，回傳一個結構化結果（dataclass 或等效型別），內含：支付規定文字（SQLite 來源）、對應條文位置與全文（PageIndex/rule_mapping 來源）。
- **D-08:** 三層（SQLite/PageIndex/rule_mapping）的內部組合、快取命中判斷、零 LLM 保證，都封裝在這個函式內部；下游（Phase 3-5 的解析器、比對器）不需要知道內部是資料庫查詢還是快取查表。
- 這個介面決策會影響所有後續 phase 的整合方式，規劃階段應優先鎖定此函式簽章。

### ChromaDB 基礎架構（順便建立，非本階段驗收項）
- **D-09:** Phase 2 順便將 PageIndex 條文全文做 embedding 存入 ChromaDB，建立基礎架構完整性，避免 Phase 5 比對器需要自由文字查詢時回頭修改規則庫 schema。
- **注意：** 此項不在 REQ-rule-repository 的 3 項驗收標準內（SQLite 查詢、PageIndex 涵蓋、rule_mapping 命中率）——規劃階段應將 ChromaDB 建置列為附加/低優先任務，不可排擠三項核心驗收標準的完成度。若時間/複雜度超出預期，可將 ChromaDB 部分拆到獨立任務或延後，但不應阻塞核心驗收。

### Claude's Discretion
- 20 個驗收醫令代碼的最終清單（D-06 草案將在規劃或執行階段與使用者確認最終版本）
- PageIndex 對不同文件結構（科別條列式 vs 手術章節式）的前處理/解析策略細節
- SQLite schema 的確切欄位名稱與型別

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 規則庫分層與檢索策略（LOCKED）
- `.planning/intel/decisions.md` §D6 — 規則庫檢索策略：PageIndex 為主＋rule_mapping 預編譯快取（零 LLM 查詢）＋ChromaDB 輔助
- `docs/plans/2026-07-29-elc-audit-engine-design.md` §3.1-3.3 — D6 的詳細技術elaboration（規則庫分層架構圖）

### 需求與驗收標準
- `.planning/REQUIREMENTS.md` REQ-rule-repository — Phase 2 完整驗收標準（SQLite 可查詢／PageIndex 涵蓋全部文件／rule_mapping 命中率抽驗 20 項）

### 錯誤處理（規則庫查無醫令時）
- `.planning/intel/constraints.md` §C5 — 錯誤處理故障表：「規則庫查無醫令→入未知醫令清單→即時PageIndex導航→仍無→標查無規則依據」（此邏輯屬 Phase 3/5 整合行為，但 rule_repository 介面需支援回傳「查無結果」狀態供上游處理）

### 技術棧慣例
- `.planning/intel/decisions.md` §D4 — 技術棧沿用 DrtoolboxLocalServer（Python+uv、SQLite、pageindex 套件）
- `.planning/phases/01-project-skeleton/01-01-SUMMARY.md` — Phase 1 已建立的 `config/settings.py`（含 `RULE_SOURCE_DIR`、`DB_DIR` 環境變數）與 `src/elc_audit_engine/rule_repository/` 空殼套件，Phase 2 直接在此套件內實作

### 來源資料（實際檔案，非文件引用）
- `officialdocument/審查注意事項/醫療服務給付項目251027準確板_已優化填入支付規定.csv` — payment_rules 來源，7 欄，約 4700 行
- `officialdocument/審查注意事項/藥品項查詢項目檔260605 AI 摘要支付價大於0.csv` — drug_rules 來源，22 欄，約 3.8 萬行（規劃階段需評估大檔案的載入/索引效能）
- `officialdocument/審查注意事項/*.docx` — 21 份科別審查注意事項 + 附表 + 手術章節規定，PageIndex 來源

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `config/settings.py`（Phase 1 已建立）— 已定義 `RULE_SOURCE_DIR`（指向 `officialdocument/審查注意事項/`）、`DB_DIR`（指向 `data/db/`）、`RAG_DIR`（指向 `data/rag/`，可作為 ChromaDB 儲存位置）。Phase 2 直接複用這些設定，不需重新定義路徑。
- `src/elc_audit_engine/rule_repository/__init__.py` — 目前為空殼（僅 docstring），Phase 2 在此套件內實作三層規則庫與查詢介面。
- `data/db/`、`data/rag/` 目錄已存在（Phase 1 建立，含 `.gitkeep`），可直接用於 SQLite 檔案與 ChromaDB persistent storage。

### Established Patterns
- Phase 1 的 `config/llama_config.json` 已鎖定 llama.cpp 連線設定（Ornith-1.0-9B, n_ctx 32768, localhost:8080），D-04 的 LLM 輔助 rule_mapping 建置應複用此設定載入方式（`config.settings.load_llama_config()`）。
- Phase 1 測試慣例：pytest + `[dependency-groups] dev`（PEP 735），Phase 2 測試（含 20 醫令核對）應延續此慣例。

### Integration Points
- 下游 Phase 3（解析器）解析出醫令代碼後，會呼叫 D-07 定義的單一查詢函式取得規則內容。
- 下游 Phase 5（三方比對器）需要規則文字＋來源引用，供 LLM 判定支持度時「引用原文」（見 constraints.md C1）。

</code_context>

<specifics>
## Specific Ideas

無特定 UI/格式偏好——本階段純後端資料層，無使用者可見輸出。20 個驗收醫令代碼由 Claude 草擬候選、使用者最終核對（見 D-06）。

</specifics>

<deferred>
## Deferred Ideas

- ChromaDB 完整運用（自由文字/類似案例查詢的實際使用場景）延後至 Phase 5（三方比對器）— Phase 2 只建立基礎架構（D-09），不實作查詢邏輯。
- 手術章節式文件（2-2-7...docx）與科別條列式文件的解析策略差異，若規劃階段發現複雜度顯著提高，可考慮是否值得拆分成更細的任務，但仍屬 Phase 2 範圍內。

None — 討論全程未出現超出本階段範圍（新能力）的提議。

</deferred>

---

*Phase: 2-規則庫建置*
*Context gathered: 2026-07-30*
