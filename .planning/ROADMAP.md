# Roadmap: elc-audit-engine（電子抽審自動化引擎）

source: progress.md §四 (LOCKED roadmap), elaborated by docs/plans/2026-07-29-elc-audit-engine-design.md §9

## Overview

建立病歷補強（送審前）與申復生成（核減後）的自動化系統，共用同一條「醫令↔規則↔病歷」三方比對引擎。GSD Phase 1-8 對應 progress.md 的 M1-M8（原設計文件的「Phase 1 — 獨立引擎」milestone 順序，現改為 GSD 逐一規劃/執行的 Phase），全部完成後即為可獨立運作（file-in/file-out）的核心引擎。GSD Phase 9 為後續的 HIS 整合（原設計文件的「Phase 2」），待核心引擎完成並有真實使用回饋後才展開細部規劃。

## Phases

**Phase Numbering:**
- Integer phases (1-9): Planned milestone work, 對應 progress.md M1-M8 + Phase 2 佔位
- Decimal phases (x.1, x.2): Urgent insertions (marked with INSERTED) — 目前無

- [ ] **Phase 1: 專案骨架** - uv 專案初始化、config、目錄結構
- [ ] **Phase 2: 規則庫建置** - CSV→SQLite、審查注意事項→PageIndex、rule_mapping 預編譯
- [ ] **Phase 3: 解析器** - 申報XML（tdata/ddata/pdata）、核減清單、SOAP文字
- [ ] **Phase 4: 病歷彙整器** - Provider介面＋本地檔案Provider、半年病史時間軸
- [ ] **Phase 5: 三方比對器** - 醫令↔規則↔病歷 支持度判定＋候選補強生成
- [ ] **Phase 6: 輸出一（病歷補強報告）** - 病歷補強報告.md 生成
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
- [ ] 01-01-PLAN.md — uv 專案骨架、config 載入機制（llama.cpp 連線設定）、src/elc_audit_engine 套件結構、config 測試骨架

### Phase 2: 規則庫建置
**Goal**: SQLite 結構化規則層（payment_rules/drug_rules）與 PageIndex 條文層＋rule_mapping 預編譯快取皆就緒，可離線查詢零 LLM 呼叫
**Depends on**: Phase 1
**Requirements**: REQ-rule-repository
**Success Criteria** (what must be TRUE):
  1. SQLite `payment_rules`／`drug_rules` 可由醫令代碼／藥品代碼查詢
  2. PageIndex 樹狀索引涵蓋 `officialdocument/審查注意事項/` 全部 .doc/.docx 文件
  3. `rule_mapping` 預編譯快取（醫令代碼,科別,文件版本→條文位置/全文）建置完成，抽 20 個常見醫令（如 01015C、64140C）人工核對命中率可驗收
**Plans**: TBD

Plans:
- [ ] 02-01: TBD

### Phase 3: 解析器
**Goal**: 可解析申報XML（tdata/ddata/pdata）、核減清單、SOAP病歷文字
**Depends on**: Phase 1
**Requirements**: REQ-parsers
**Success Criteria** (what must be TRUE):
  1. 申報XML tdata/ddata/pdata 欄位可正確解析
  2. 欄位缺漏依致命／可容忍分級處理
  3. SOAP文字可分段定位（S/O/A/P）
**Plans**: TBD

Plans:
- [ ] 03-01: TBD

### Phase 4: 病歷彙整器
**Goal**: Provider 介面抽象化雲端/本地資料來源，本地檔案 Provider 可運作並產出近半年病史時間軸
**Depends on**: Phase 1
**Requirements**: REQ-record-aggregator
**Success Criteria** (what must be TRUE):
  1. Provider 介面定義完成，支援雲端與本地兩種實作切換
  2. 本地檔案 Provider 可運作（Phase 1 頂替雲端病歷）
  3. 可產出近半年病史時間軸（就診紀錄/檢驗/檢查/影像清單）
**Plans**: TBD

Plans:
- [ ] 04-01: TBD

### Phase 5: 三方比對器
**Goal**: 醫令↔規則↔病歷三方比對，逐檢核項判定支持度並生成候選補強敘述
**Depends on**: Phase 2, Phase 3, Phase 4
**Requirements**: REQ-three-way-comparator
**Success Criteria** (what must be TRUE):
  1. 逐檢核項判定支持/部分支持/無記載，並引用病歷原文
  2. 醫令支持度輸出三級分類（充分/薄弱/裸奔）
  3. 缺口項目生成 1~3 條候選補強敘述，僅基於既有病史線索擴寫（不憑空編造），每條附規則出處
**Plans**: TBD

Plans:
- [ ] 05-01: TBD

### Phase 6: 輸出一（病歷補強報告）
**Goal**: 生成病歷補強報告.md，供醫師逐條審核
**Depends on**: Phase 5
**Requirements**: REQ-output-reinforcement-report
**Success Criteria** (what must be TRUE):
  1. 輸出 Markdown checkbox 逐條審格式
  2. 內容含醫令支持度缺口、半年病史摘要、候選補強敘述（逐條點選）
  3. 醫師可勾選/編輯後存檔，並留下審核軌跡
**Plans**: TBD

Plans:
- [ ] 06-01: TBD

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
| 1. 專案骨架 | 0/1 | Planned & Verified | - |
| 2. 規則庫建置 | 0/TBD | Not started | - |
| 3. 解析器 | 0/TBD | Not started | - |
| 4. 病歷彙整器 | 0/TBD | Not started | - |
| 5. 三方比對器 | 0/TBD | Not started | - |
| 6. 輸出一（病歷補強報告） | 0/TBD | Not started | - |
| 7. 輸出二（申復理由草稿） | 0/TBD | Not started | - |
| 8. 端到端測試 | 0/TBD | Not started | - |
| 9. doctor-toolbox HIS 整合（佔位） | 0/TBD | Not started | - |

## Out of Roadmap Scope

The following material from 電子抽審.md is background/context only and is NOT part of any phase's engineering scope:
- FHIR/HL7 mapping tables (constraints.md C12)
- DICOM/PDF/XML file packaging and sTypeCode upload protocol details (constraints.md C9, C10)
- 院所行政前置申請作業 (VPN 權限開通、紙本替代方案申請) — operational/administrative, not engineering
- UML/ER research appendix material — background reference for eventual Phase 9 design
