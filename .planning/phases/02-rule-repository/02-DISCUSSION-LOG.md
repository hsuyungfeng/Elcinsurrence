# Phase 2: 規則庫建置 - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-30
**Phase:** 02-規則庫建置
**Areas discussed:** SQLite 欄位範圍, PageIndex 涵蓋範圍, rule_mapping 建置方式, ChromaDB 範圍, 對外介面設計, 20 醫令驗收清單來源

---

## SQLite 欄位範圍

| Option | Description | Selected |
|--------|-------------|----------|
| 只存核心比對欄位 | 代碼/名稱/支付或給付規定文字/生效起訖日期；其餘欄位不搬進 SQLite | ✓ |
| CSV 全欄位鏡射進 SQLite | 兩表照抄全部欄位，未來不用改 schema，但表變寬、含大量比對用不到的文字 | |

**User's choice：** 只存核心比對欄位（採用推薦）
**Notes：** 藥品項 CSV 實測有 22 欄（含 AI-note、連結、劑型、藥商等），確認多數欄位對比對器無用，核心欄位足夠支撐 REQ-rule-repository 的查詢驗收標準。

---

## PageIndex 涵蓋範圍

| Option | Description | Selected |
|--------|-------------|----------|
| 全部 .docx 都納入 PageIndex | 21 科別檔＋附表＋手術章節檔全部建索引 | ✓ |
| 先只納入科別審查注意事項，手術章節/附表另案處理 | 因文件結構明顯不同（章節式法規 vs 科別條列式），怕用同一套解析邏輯出錯 | |

**User's choice：** 全部 .docx 都納入 PageIndex（採用推薦）
**Notes：** scout codebase 時發現實際目錄下除 21 份科別檔外，還有「西醫基層-附表.docx」(400K) 與「2-2-7手術-113.12.01.docx」(416K)，後者為章節式法規、結構明顯不同於科別條列檔——已記錄為規劃階段需評估的解析策略差異點，但範圍仍是全部涵蓋。

---

## rule_mapping 預編譯快取的建置方式

| Option | Description | Selected |
|--------|-------------|----------|
| LLM 輔助建置＋人工抽驗 | llama.cpp 讀 PageIndex 條文樹生成建議對應，一次性批次建置；查詢階段零 LLM | ✓ |
| 規則式關鍵字比對建置 | 用代碼/名稱做關鍵字/正則搜尋自動建立初版對照，不呼叫 LLM，準確率可能較低但完全確定性 | |

**User's choice：** LLM 輔助建置＋人工抽驗（採用推薦）
**Notes：** 明確界定 LLM 只用在「建置」這個一次性步驟，查詢路徑（供 Phase 3-5 使用）必須完全零 LLM，符合 D6 的離線查詢承諾。

---

## ChromaDB 輔助層範圍

| Option | Description | Selected |
|--------|-------------|----------|
| Phase 2 不建 ChromaDB，留待後續 | REQ-rule-repository 3 項驗收標準都不含 ChromaDB，留給 Phase 5 真正需要時再加 | |
| Phase 2 順便建立 ChromaDB 基礎架構 | 現在就把條文全文 embedding 進 ChromaDB，避免 Phase 5 回頭改規則庫 schema | ✓ |

**User's choice：** Phase 2 順便建立 ChromaDB 基礎架構（**非推薦選項** — 使用者主動選擇提前建置）
**Notes：** 已在 CONTEXT.md 明確標註此項不算入本階段核心驗收範圍，規劃階段須確保 ChromaDB 建置不排擠三項核心驗收標準（SQLite/PageIndex/rule_mapping）的完成度；必要時可延後或獨立拆分。

---

## rule_repository 對外介面設計

| Option | Description | Selected |
|--------|-------------|----------|
| 單一查詢函式：醫令代碼→結構化結果 | 一個入口點封裝三層細節，下游不需知道內部是資料庫還是快取 | ✓ |
| 分層暴露：SQLite/PageIndex/rule_mapping 各自 API | 上層可選擇性查詢深度，控制權更細但需要理解三層差異 | |

**User's choice：** 單一查詢函式（採用推薦）
**Notes：** 此決策影響 Phase 3-5 所有後續整合方式，已記錄為規劃階段應優先鎖定的函式簽章。

---

## 20 個常見醫令代碼驗收清單來源

| Option | Description | Selected |
|--------|-------------|----------|
| Claude 從 CSV 挑選代表性高頻項目，使用者核對 | 從兩份 CSV 中依「支付規定/給付規定文字非空且具體」原則挑選涵蓋多類型的候選清單草案 | ✓ |
| 使用者提供實際臨床常用的 20 個醫令代碼清單 | 使用者依實際看診經驗提供高頻代碼，比隨機挑選更貼近真實使用情境 | |

**User's choice：** Claude 從 CSV 挑選代表性高頻項目，使用者核對（採用推薦）
**Notes：** CONTEXT.md 中已附上候選範例（06012C、06013C、05316C 等），並註明這是草案，規劃/執行階段需與使用者確認最終 20 項清單，同時納入 progress.md/電子抽審.md 已提及的 01015C、64140C。

---

## Claude's Discretion

- 20 個驗收醫令代碼的最終清單（草案已提供，待使用者確認）
- PageIndex 對不同文件結構（科別條列式 vs 手術章節式）的前處理/解析策略細節
- SQLite schema 的確切欄位名稱與型別

## Deferred Ideas

- ChromaDB 完整運用場景（自由文字/類似案例查詢的實際邏輯）延後至 Phase 5（三方比對器）
- 手術章節式文件與科別條列式文件解析策略差異，若複雜度顯著提高可考慮拆分任務（仍屬 Phase 2 範圍）
