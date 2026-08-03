# Roadmap: elc-audit-engine（電子抽審自動化引擎）

source: progress.md §四 (LOCKED roadmap), elaborated by docs/plans/2026-07-29-elc-audit-engine-design.md §9

## Overview

建立病歷補強（送審前）與申復生成（核減後）的自動化系統，共用同一條「醫令↔規則↔病歷」三方比對引擎。GSD Phase 1-8 對應 progress.md 的 M1-M8（原設計文件的「Phase 1 — 獨立引擎」milestone 順序，現改為 GSD 逐一規劃/執行的 Phase），全部完成後即為可獨立運作（file-in/file-out）的核心引擎。GSD Phase 9 為後續的 HIS 整合（原設計文件的「Phase 2」），待核心引擎完成並有真實使用回饋後才展開細部規劃。

## Phases

**Phase Numbering:**
- Integer phases (1-9): Planned milestone work, 對應 progress.md M1-M8 + Phase 2 佔位
- Decimal phases (x.1, x.2): Urgent insertions (marked with INSERTED) — 目前無

- [x] **Phase 1: 專案骨架** - uv 專案初始化、config、目錄結構
- [x] **Phase 2: 規則庫建置** - CSV→SQLite、審查注意事項→PageIndex、rule_mapping 預編譯
- [x] **Phase 3: 解析器** - 申報XML（tdata/ddata/pdata）、核減清單、SOAP文字
- [x] **Phase 4: 病歷彙整器** - Provider介面＋本地檔案Provider、半年病史時間軸
- [x] **Phase 5: 三方比對器** - 醫令↔規則↔病歷 支持度判定＋候選補強生成
- [x] **Phase 6: 輸出一（病歷補強報告）** - 病歷補強報告.md 生成
- [ ] **Phase 7: 輸出二（申復理由草稿）** - 申復理由草稿（p8/p9 ≤2000字）＋申復XML欄位
- [ ] **Phase 8: 端到端測試** - 規格造測試資料→待真實樣本進來替換驗證
- [ ] **Phase 9: doctor-toolbox HIS 整合（佔位）** - Phase 2（原設計文件命名）：雲端病歷 Provider、Flask API化、NHI_EIIAPI 銜接

## Phase Details

### Phase 1: 專案骨架
**Goal**: uv 專案可初始化並執行，config 結構就緒，目錄結構符合技術棧慣例（沿用 DrtoolboxLocalServer 佈局，見 D4）
**Depends on**: Nothing (first phase)
**Requirements**: REQ-project-skeleton
**Success Criteria** (what must be TRUE):
  1. `uv run` 可在專案根目錄成功執行（uv 專案已初始化，含 pyproject.toml）
  2. config 載入機制就緒（可讀取 llama.cpp server 位址等設定）
  3. 目錄結構已建立，且與 DrtoolboxLocalServer 既有慣例一致（Python+uv、Flask、python-docx、pandas、pageindex、SQLite 佈局）
**Plans**: 1 plan

Plans:
- [x] 01-01-PLAN.md — uv 專案骨架、config 載入機制（llama.cpp 連線設定）、src/elc_audit_engine 套件結構、config 測試骨架

### Phase 2: 規則庫建置
**Goal**: SQLite 結構化規則層（payment_rules/drug_rules）與自建 docx 樹狀條文索引（取代不可離線使用的 pageindex 雲端套件）＋rule_mapping 預編譯快取皆就緒，可離線查詢零 LLM 呼叫
**Depends on**: Phase 1
**Requirements**: REQ-rule-repository
**Success Criteria** (what must be TRUE):
  1. [x] SQLite `payment_rules`／`drug_rules` 可由醫令代碼／藥品代碼查詢 — 02-02 完成：2,669 payment_rules + 11,273 drug_rules 列
  2. [x] 自建樹狀條文索引涵蓋 `officialdocument/審查注意事項/` 全部 .doc/.docx 文件（含 11 份舊版 .doc 經 LibreOffice 轉檔）— 02-03 完成：32 份來源檔案（11 .doc + 21 .docx）全數處理，`data/db/docx_trees.json`（1633 節點）
  3. [x] `rule_mapping` 預編譯快取（醫令代碼→條文位置/全文）建置完成 — 02-04 完成批次建置（13,942/13,942 碼全數處理：6,802 CSV 重用快速路徑＋558 LLM 輔助比對＋6,582 誠實無匹配，非幻覺捏造）；20 碼人工核對清單（01015C 經查證不存在於任一 CSV，已於規劃階段替換）於 02-05 完成人工簽核，使用者確認 20/20 全數正確
**Plans**: 6 plans — **Phase COMPLETE (2026-07-31)**

Plans:
- [x] 02-01-PLAN.md — Wave 0：RuleResult 契約定義、20 碼驗收清單定案、失敗中測試骨架（SQLite/docx樹/rule_mapping/介面）
- [x] 02-02-PLAN.md — Wave 1：SQLite payment_rules/drug_rules 載入（民國/西元日期解析、參數化查詢）
- [x] 02-03-PLAN.md — Wave 1：LibreOffice .doc 轉檔＋自建 docx 樹狀條文索引（正則階層解析，取代 pageindex 雲端套件）
- [x] 02-04-PLAN.md — Wave 2：llama.cpp 輔助 rule_mapping 批次建置（含 CSV 支付規定重用快速路徑）
- [x] 02-05-PLAN.md — Wave 3：get_rule() 單一查詢介面 + 20 碼人工核對 checkpoint（使用者確認 20/20 正確）
- [x] 02-06-PLAN.md — Wave 2：ChromaDB embedding 基礎架構（D-09，非阻塞附加任務）

### Phase 3: 解析器
**Goal**: 可解析申報XML（tdata/ddata/pdata）、核減清單、SOAP病歷文字
**Depends on**: Phase 1
**Requirements**: REQ-parsers
**Success Criteria** (what must be TRUE):
  1. [x] 申報XML tdata/ddata/pdata 欄位可正確解析 — 03-01 完成：Big5 編碼偵測＋回退、tdata/dhead/dbody/pdata 全欄位保留，真實檔回放 633 案／2,624 醫令／0 拒收
  2. [x] 欄位缺漏依致命／可容忍分級處理 — 03-01 完成：三種致命（缺 d1/d2、缺 d3、無 pdata）進 rejected；d19 與高出現率欄位缺席僅警告（D-05/D-06/D-08）
  3. [x] SOAP文字可分段定位（S/O/A/P） — 03-01 完成：marker（high）→ keyword（low）兩層、317 關鍵詞移植、無命中歸 UNKNOWN
**Plans**: TBD

Plans:
- [x] 03-01-PLAN.md — Wave 1：三個解析器（申報 XML Big5/缺漏分級、核減明細 18 欄 reader 參數化、SOAP marker/keyword 兩層＋317 關鍵詞移植）＋ fixtures（TOTFA 抽 4 案／D-14d 官方 2 筆）＋ 46 測試；真實檔回放 633 案 0 拒收

### Phase 4: 病歷彙整器
**Goal**: Provider 介面抽象化雲端/本地資料來源，本地檔案 Provider 可運作並產出近半年病史時間軸
**Depends on**: Phase 1
**Requirements**: REQ-record-aggregator
**Success Criteria** (what must be TRUE):
  1. [x] Provider 介面定義完成，支援雲端與本地兩種實作切換 — 04-01 完成：RecordProvider ABC＋LocalFileProvider＋FakeCloudProvider 切換測試
  2. [x] 本地檔案 Provider 可運作（Phase 1 頂替雲端病歷） — 04-01 完成：讀 records.json 契約（ISO/8 碼日期），fixture 四類紀錄
  3. [x] 可產出近半年病史時間軸（就診紀錄/檢驗/檢查/影像清單） — 04-01 完成：build_timeline 時間窗過濾＋排序＋excluded 統計；病歷缺席降級（C5）
**Plans**: TBD

Plans:
- [x] 04-01-PLAN.md — Wave 1：RecordProvider ABC＋LocalFileProvider（records.json）＋build_timeline 半年時間軸＋降級語意（P0-2）＋14 測試；全套件 110 passed / 5 skipped

### Phase 5: 三方比對器
**Goal**: 醫令↔規則↔病歷三方比對，逐檢核項判定支持度並生成候選補強敘述
**Depends on**: Phase 2, Phase 3, Phase 4
**Requirements**: REQ-three-way-comparator
**Success Criteria** (what must be TRUE):
  1. [x] 逐檢核項判定支持/部分支持/無記載，並引用病歷原文 — 05-01 完成：LLMJudger（JSON 強制＋重試＋待人工降級），judgment.quote 引用原文；29 測試全綠
  2. [x] 醫令支持度輸出三級分類（充分/薄弱/裸奔） — 05-01 完成：classify_support 純函式（無 LLM 依賴），真實案件煙霧測試 4/11 有規則醫令正確分級
  3. [x] 缺口項目生成 1~3 條候選補強敘述，僅基於既有病史線索擴寫（不憑空編造），每條附規則出處 — 05-01 完成：LLMNarrativeGenerator（C2 約束：prompt_only 提示型、每條附 article_location）
**Plans**: TBD

Plans:
- [x] 05-01-PLAN.md — Wave 1：comparator 套件（models/evidence/support/judger/narratives/comparator）＋29 測試；真實 TOTFA 首案煙霧測試（未知醫令誠實標記）；全套件 139 passed / 5 skipped

### Phase 6: 輸出一（病歷補強報告）
**Goal**: 生成病歷補強報告.md，供醫師逐條審核
**Depends on**: Phase 5
**Requirements**: REQ-output-reinforcement-report
**Success Criteria** (what must be TRUE):
  1. [x] 輸出 Markdown checkbox 逐條審格式 — 06-01 完成：render_report 產出「- [ ] 敘述〔提示型〕（出處）」逐條 checkbox
  2. [x] 內容含醫令支持度缺口、半年病史摘要、候選補強敘述（逐條點選） — 06-01 完成：✅充分/⚠️薄弱/❌裸奔/❓查無規則徽章＋半年病史摘要區＋候選補強逐條
  3. [x] 醫師可勾選/編輯後存檔，並留下審核軌跡 — 06-01 完成：render_tracking 審核軌跡 JSON（四狀態＋原文＋編輯後文＋時間）；write_report 寫 .md＋.json
**Plans**: TBD

Plans:
- [x] 06-01-PLAN.md — Wave 1：generators（reinforcement_report/tracking）＋13 測試；真實 TOTFA 首案報告渲染（11 醫令區塊＋警告區）；全套件 152 passed / 5 skipped

### Phase 7: 輸出二（申復理由草稿）
**Goal**: 生成申復理由草稿（p8/p9 ≤2000字）與申復XML欄位
**Depends on**: Phase 5
**Requirements**: REQ-output-appeal-draft
**Success Criteria** (what must be TRUE):
  1. 四段組裝式結構完成（案情摘要/醫療必要性/規則依據/病歷佐證）
  2. 字數控制器依 ④→② 優先裁剪規則將全文控制在 2000 字內
  3. P6 不申覆強制填 0 通過程式硬檢查；每筆核減醫令獨立生成
  4. 輸出 `申復草稿_{案件流水號}.md` ＋ `appeal_{流水號}.json`
**Plans**: TBD

Plans:
- [ ] 07-01: TBD

### Phase 8: 端到端測試
**Goal**: 五層測試策略全數涵蓋並可執行，驗證核心引擎端到端運作
**Depends on**: Phase 6, Phase 7
**Requirements**: REQ-e2e-testing
**Success Criteria** (what must be TRUE):
  1. 單元測試涵蓋各 pure function 硬性檢查
  2. 規則庫驗收測試（rule_mapping 命中率）通過
  3. LLM 判定金標準 30 組測試建立並可回放
  4. 端到端 3 案例測試通過（規格造測試資料，介面保留真實樣本替換空間）
**Plans**: TBD

Plans:
- [ ] 08-01: TBD

### Phase 9: doctor-toolbox HIS 整合（佔位）
**Goal**: 將 Phase 1-8 核心引擎整合進 doctor-toolbox HIS 模組（原設計文件「Phase 2」）
**Depends on**: Phase 8
**Requirements**: REQ-phase2-his-integration
**Success Criteria** (what must be TRUE):
  1. 雲端病歷 Provider 接上 doctor-toolbox（cloud_sync/his_connection 模式），取代 Phase 4 本地檔案 Provider
  2. 核心引擎 Flask API 化，供 HIS 呼叫
  3. 與 Local Agent / NHI_EIIAPI VPN 上傳流程銜接
**Plans**: TBD — 尚未細部規劃，待 Phase 1-8 完成後展開

Plans:
- [ ] 09-01: TBD

## Progress

**Execution Order:**
Phases execute in dependency order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9
（2/3/4 皆僅依賴 1，可並行規劃；5 需等待 2、3、4 皆完成；6、7 皆依賴 5，可並行；8 需等待 6、7；9 最後）

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. 專案骨架 | 1/1 | Complete | 2026-07-29 |
| 2. 規則庫建置 | 6/6 | Complete | 2026-07-31 |
| 3. 解析器 | 1/1 | Complete | 2026-08-03 |
| 4. 病歷彙整器 | 1/1 | Complete | 2026-08-03 |
| 5. 三方比對器 | 1/1 | Complete | 2026-08-03 |
| 6. 輸出一（病歷補強報告） | 1/1 | Complete | 2026-08-03 |
| 7. 輸出二（申復理由草稿） | 0/TBD | Not started | - |
| 8. 端到端測試 | 0/TBD | Not started | - |
| 9. doctor-toolbox HIS 整合（佔位） | 0/TBD | Not started | - |

## Out of Roadmap Scope

The following material from 電子抽審.md is background/context only and is NOT part of any phase's engineering scope:
- FHIR/HL7 mapping tables (constraints.md C12)
- DICOM/PDF/XML file packaging and sTypeCode upload protocol details (constraints.md C9, C10)
- 院所行政前置申請作業 (VPN 權限開通、紙本替代方案申請) — operational/administrative, not engineering
- UML/ER research appendix material — background reference for eventual Phase 9 design
