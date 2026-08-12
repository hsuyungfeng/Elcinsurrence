# Roadmap: elc-audit-engine（電子抽審自動化引擎）

source: progress.md §四 (LOCKED roadmap), elaborated by docs/plans/2026-07-29-elc-audit-engine-design.md §9

## Overview

電子抽審自動化引擎：解析申報 XML／核減明細／SOAP 病歷 → 規則庫（SQLite）＋三方比對（醫令↔規則↔病歷）→ 輸出病歷補強報告、申復理由草稿、紙本申復清單 PDF、HIS 服務化 Flask API。

## Milestones

- ✅ **v1.0 elc-audit-engine MVP** — Phases 1-9, 09.1, 11, 11.1（shipped 2026-08-10；Phase 10 VPN 實機串接外部依賴阻塞，不計入範圍）
- ✅ **v1.1 紙本→數位化整合三項輸出** — Phases 12, 13, 14（shipped 2026-08-11）

## Phases

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
