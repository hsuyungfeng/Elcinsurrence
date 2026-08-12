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

### Phase 10: VPN／實機串接（Blocked — 外部依賴門控）

- [ ] Phase 10: VPN／實機串接（0/1 plans）— 雲端病歷 Provider、NHI_EIIAPI wrapper、Local Gateway 七元件。阻塞於外部依賴，不計入 v1.0 範圍。

### v1.1 紙本→數位化整合三項輸出

- [x] Phase 12: 影像佐證上傳與關聯驅動（0/1 plans）— 接收 procedure/sono/X-ray 影像上傳，依案件流水號命名關聯，`has_attachment` 改由「是否有實際上傳檔案」真實驅動 `p7=Y/N`。 (completed 2026-08-11)
- [x] Phase 13: 核減明細原格式列印（3/3 plans）— 系統處理完核減資料後，印出跟官方核減清單原始紙本一致的版面（RCPI2021R01/RCPI2001R01/RCPI2012R01 式樣）。 (completed 2026-08-11)
- [x] Phase 14: 審核軌跡＋病歷摘要＋申復理由＋影像佐證包列印（0/1 plans）— 整合軌跡 JSON、補強 Markdown 報告、申復理由與影像佐證圖片，合成可列印佐證包 PDF。 (completed 2026-08-11)

## Phase Details

### Phase 12: 影像佐證上傳與關聯驅動
**Goal**: 接收診所上傳之佐證影像（超音波/X光/處置照片等），依案件與醫令流水號做命名關聯存檔，並將 `generators/appeal.py` 的 `has_attachment` / `p7` 由手動旗標改為由「是否有實體佐證檔案存在」真實驅動。
**Depends on**: Phase 7, Phase 9
**Requirements**: REQ-attachment-upload
**Success Criteria** (what must be TRUE):
  1. API/CLI 可接收 PNG/JPEG/HEIC/PDF 影像佐證上傳，校驗路徑安全後存入指定附件目錄，並與案件流水號與醫令連動。
  2. `render_appeal_json` 與申復 XML 中的 `p7`（`has_attachment`）依實體附件存在與否真實填寫 `Y`/`N`。
  3. 未上傳影像時誠實降級為 `N`，上傳非支援格式時明確拒絕。

### Phase 13: 核減明細原格式列印
**Goal**: 系統匯入並解析健保核減資料後，可輸出與官方原始紙本核減明細（RCPI2021R01 / RCPI2001R01 / RCPI2012R01 式樣）一致的 PDF 檔案供診所留底或紙本對帳。
**Depends on**: Phase 3, Phase 11
**Requirements**: REQ-deduction-print
**Success Criteria** (what must be TRUE):
  1. PDF 版面與官方核減明細紙本表格格式一致（含表頭院所資訊、抽審案號、醫令明細、不予核銷金額與核減代碼/理由敘述）。
  2. 比照 Phase 11 的 ODT 模板填值與 soffice 轉檔模式，獨立維護核減明細專屬 ODT 模板。
  3. 資料缺欄時誠實標記並列印警告訊息。

### Phase 14: 審核軌跡＋病歷摘要＋申復理由＋影像佐證包列印
**Goal**: 將審核軌跡 JSON (`tracking.json`)、病歷補強 Markdown 報告、申復理由草稿以及上傳之影像佐證照片，合成為一份結構完整的「可列印佐證包 PDF」，供診所列印後隨同紙本申復清單合訂寄出。
**Depends on**: Phase 6, Phase 7, Phase 11, Phase 12
**Requirements**: REQ-evidence-packet-print
**Success Criteria** (what must be TRUE):
  1. 產出包含摘要封面、審核軌跡與決策歷史、申復理由全文、以及多頁佐證影像圖表附錄的完整 PDF 包。
  2. 圖片自動縮放排版適配 A4 頁面，損毀或格式不符影像自動註記並降級跳過。
  3. 支援單一 CLI 指令或 API 端點一鍵生成案件完整佐證包。

## Progress

| Phase | Plans Complete | Status | Completed |
| ----- | -------------- | ------ | --------- |
| 1. 專案骨架 | 1/1 | Complete | 2026-07-29 |
| 2. 規則庫建置 | 6/6 | Complete | 2026-07-31 |
| 3. 解析器 | 1/1 | Complete | 2026-08-03 |
| 4. 病歷彙整器 | 1/1 | Complete | 2026-08-03 |
| 5. 三方比對器 | 1/1 | Complete | 2026-08-03 |
| 6. 輸出一（病歷補強報告） | 1/1 | Complete | 2026-08-03 |
| 7. 輸出二（申復理由草稿） | 1/1 | Complete | 2026-08-03 |
| 8. 端到端測試 | 1/1 | Complete | 2026-08-03 |
| 9. HIS 服務化（本機可驗證） | 4/4 | Complete | 2026-08-07 |
| 09.1. Address tech debt | 3/3 | Complete | 2026-08-08 |
| 10. VPN／實機串接 | 0/1 | Blocked（外部依賴） | - |
| 11. 紙本申復清單列印 | 3/3 | Complete | 2026-08-08 |
| 11.1. Close milestone audit gaps | 2/2 | Complete | 2026-08-10 |
| 12. 影像佐證上傳與關聯驅動 | 1/1 | Complete   | 2026-08-11 |
| 13. 核減明細原格式列印 | 3/3 | Complete   | 2026-08-11 |
| 14. 審核軌跡＋佐證包列印 | 3/3 | Complete   | 2026-08-11 |

## Out of Roadmap Scope

The following material from 電子抽審.md is background/context only and is NOT part of any phase's engineering scope:
- FHIR/HL7 mapping tables (constraints.md C12)
- DICOM/PDF/XML file packaging and sTypeCode upload protocol details (constraints.md C9, C10)
- 院所行政前置申請作業 (VPN 權限開通、紙本替代方案申請) — operational/administrative, not engineering
- UML/ER research appendix material — background reference for eventual Phase 9 design
