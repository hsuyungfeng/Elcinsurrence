# Roadmap: elc-audit-engine（電子抽審自動化引擎）

source: progress.md §四 (LOCKED roadmap), elaborated by docs/plans/2026-07-29-elc-audit-engine-design.md §9

## Overview

電子抽審自動化引擎：解析申報 XML／核減明細／SOAP 病歷 → 規則庫（SQLite）＋三方比對（醫令↔規則↔病歷）→ 輸出病歷補強報告、申復理由草稿、紙本申復清單 PDF、HIS 服務化 Flask API。

## Milestones

- ✅ **v1.0 elc-audit-engine MVP** — Phases 1-9, 09.1, 11, 11.1（shipped 2026-08-10；Phase 10 VPN 實機串接外部依賴阻塞，不計入範圍）
- ✅ **v1.1 紙本→數位化整合三項輸出** — Phases 12, 13, 14（shipped 2026-08-11）
- 🔄 **v1.2 三軌自動化審核與申復工作台** — Phase 15（規劃中）

## Phases

<details>
<summary>🔄 v1.2 三軌自動化審核與申復工作台（Phase 15）</summary>

- [x] Phase 15: 當月申報檔預審與三軌工作台（5/5 plans）— completed 2026-10-30
- [x] Phase 16: 事前預審抽樣清單與多源審查工作台（3/3 plans）— completed 2026-10-31
  - 16-01: 抽樣演算法（20 隨機 + 10 最高點數立意抽查）與批次抽樣 API
  - 16-02: 多源證據輸入（檢驗、雲端病歷、影像附件）與 HTML 視覺化預覽卡片
  - 16-03: 健保局電子抽審 XML 導出（Big5/outpatient）、前端 UI 整合與 E2E 驗證
- [x] Phase 17: 二階抽審核實工作台與身分證佐證庫（Evidence Vault）（3/3 plans）— completed 2026-10-31
  - 17-01: 佐證庫檔案系統規範與 Vault Service 實作（身分證-YYMM 結構化自動歸檔、讀取與安全防護）
  - 17-02: 前端第二階介面升級（身分證佐證庫多源掛載、影像畫廊、錄音播放器、報告檢視）
  - 17-03: 以 MONTHLY-202307.zip 進行二階核實全流程走通與 E2E 整合驗收
- [x] Phase 18: 簡潔範例病歷預生成與抽審事前自動化審查升級（3/3 plans）— completed 2026-10-31
  - 18-01: 精簡範例病歷批次預生成（500-1000字元）並存入資料庫
  - 18-02: 統一第 2、3 階審查報告格式（比照 MONTHLY-202307 月審風格）
  - 18-03: 重新設計自動化抽樣事前預審閉環與工作台
- [x] Phase 19: Case Report 視覺化審查報告升級 (借鑑 answer-me-with-html 理念)（2/2 plans）— completed 2026-11-02
  - 19-01: 重構 unified_review_report 視覺排版（SOAP 與佐證庫圖文並列、次要區塊折疊）
  - 19-02: 路由整合與預審預覽端點閉環走通驗收
- [x] Phase 20: 3 階多案件聚合預審報告、申復範例連動與雙軌審查導出（3/3 plans）— completed 2026-11-02
  - 20-01: 多案件聚合可收合 HTML 預審報告引擎（支援 2、3 階）
  - 20-02: 第 3 階申復自第 2 階隨機抽選 5 案連動與草稿生成
  - 20-03: 第 2 階雙軌審查（全自動批次審查 vs 逐筆人工審查）與全量匯整導出 (HTML & XML)
- [ ] Phase 21: 健保電子抽審檔案打包器、批次申復 XML (t38/t39) 與 Local Agent 橋接介面（0/3 plans）
  - 21-01: 健保標準檔案打包器（Evidence Packager）與單案送審匯出端點
  - 21-02: 批次電子申復 XML 生成（t38/t39 彙總、P6 強制為 0 與全形防護）
  - 21-03: 雲端與地端 Local Agent 橋接 API（Bridge API for NHI_EIIAPI）

</details>

<details>
<summary>✅ v1.0 elc-audit-engine MVP（Phases 1-9, 09.1, 11, 11.1）— SHIPPED 2026-08-10</summary>

- [x] Phase 1: 專案骨架（1/1 plans）— completed 2026-07-29
- [x] Phase 2: 規則庫建置（6/6 plans）— completed 2026-07-31
- [x] Phase 3: 解析器（1/1 plans）— completed 2026-08-03
- [x] Phase 4: 病歷彙整器（1/1 plans）— completed 2026-08-03
- [x] Phase 5: 三方比對器（1/1 plans）— completed 2026-08-03
- [x] Phase 6: 輸出一（病歷補強報告）（1/1 plans）— completed 2026-08-03
- [x] Phase 7: 輸出二（申復理由草稿）（1/1 plans）— completed 2026-08-03
- [x] Phase 8: 端到端測試（1/1 plans）— completed 2026-08-03
- [x] Phase 9: HIS 服務化（本機可驗證）（4/4 plans）— completed 2026-08-07
- [x] Phase 09.1: Address tech debt（INSERTED，3/3 plans）— completed 2026-08-08
- [ ] Phase 10: VPN／實機串接（0/1 plans）— Blocked（外部依賴：doctor-toolbox 存取權、NHI_EIIAPI Windows+VPN+SAM 實機、Local Gateway 七元件）
- [x] Phase 11: 紙本申復清單列印（3/3 plans）— completed 2026-08-08（UAT 7/7 2026-08-10）
- [x] Phase 11.1: Close milestone audit gaps（INSERTED，2/2 plans）— completed 2026-08-10

</details>

<details>
<summary>✅ v1.1 紙本→數位化整合三項輸出（Phases 12-14）— SHIPPED 2026-08-11</summary>

- [x] Phase 12: 影像佐證上傳與關聯驅動（1/1 plans）— completed 2026-08-11
- [x] Phase 13: 核減明細原格式列印（3/3 plans）— completed 2026-08-11
- [x] Phase 14: 審核軌跡＋病歷摘要＋申復理由＋影像佐證包列印（3/3 plans）— completed 2026-08-11（audit gap found + fixed 2026-08-12）

Full phase details, success criteria, and requirements: [`milestones/v1.1-ROADMAP.md`](milestones/v1.1-ROADMAP.md)

</details>

### Phase 10: VPN／實機串接（Blocked — 外部依賴門控）

- [ ] Phase 10: VPN／實機串接（0/1 plans）— 雲端病歷 Provider、NHI_EIIAPI wrapper、Local Gateway 七元件。阻塞於外部依賴，不計入 v1.0 範圍。

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
| ----- | --------- | -------------- | ------ | --------- |
| 1. 專案骨架 | v1.0 | 1/1 | Complete | 2026-07-29 |
| 2. 規則庫建置 | v1.0 | 6/6 | Complete | 2026-07-31 |
| 3. 解析器 | v1.0 | 1/1 | Complete | 2026-08-03 |
| 4. 病歷彙整器 | v1.0 | 1/1 | Complete | 2026-08-03 |
| 5. 三方比對器 | v1.0 | 1/1 | Complete | 2026-08-03 |
| 6. 輸出一（病歷補強報告） | v1.0 | 1/1 | Complete | 2026-08-03 |
| 7. 輸出二（申復理由草稿） | v1.0 | 1/1 | Complete | 2026-08-03 |
| 8. 端到端測試 | v1.0 | 1/1 | Complete | 2026-08-03 |
| 9. HIS 服務化（本機可驗證） | v1.0 | 4/4 | Complete | 2026-08-07 |
| 09.1. Address tech debt | v1.0 | 3/3 | Complete | 2026-08-08 |
| 10. VPN／實機串接 | — | 0/1 | Blocked（外部依賴） | - |
| 11. 紙本申復清單列印 | v1.0 | 3/3 | Complete | 2026-08-08 |
| 11.1. Close milestone audit gaps | v1.0 | 2/2 | Complete | 2026-08-10 |
| 12. 影像佐證上傳與關聯驅動 | v1.1 | 1/1 | Complete | 2026-08-11 |
| 13. 核減明細原格式列印 | v1.1 | 3/3 | Complete | 2026-08-11 |
| 14. 審核軌跡＋佐證包列印 | v1.1 | 3/3 | Complete | 2026-08-11 |

## Out of Roadmap Scope

The following material from 電子抽審.md is background/context only and is NOT part of any phase's engineering scope:
- FHIR/HL7 mapping tables (constraints.md C12)
- DICOM/PDF/XML file packaging and sTypeCode upload protocol details (constraints.md C9, C10)
- 院所行政前置申請作業 (VPN 權限開通、紙本替代方案申請) — operational/administrative, not engineering
- UML/ER research appendix material — background reference for eventual Phase 9 design
