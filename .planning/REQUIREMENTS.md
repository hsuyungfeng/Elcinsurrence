# REQUIREMENTS.md — elc-audit-engine

Derived from the SPEC's milestone breakdown (`docs/plans/2026-07-29-elc-audit-engine-design.md` §9), cross-validated against the LOCKED ADR roadmap (`progress.md` §四). Both sources are in full agreement — no competing acceptance-criteria variants were found for any requirement.

No dedicated PRD was present in this ingest set (ADR + SPEC + DOC only). Requirement scope and acceptance criteria are therefore reconstructed from ADR+SPEC milestone descriptions rather than a standalone PRD.

---

## REQ-project-skeleton

- **Source:** progress.md §四 M1; docs/plans/2026-07-29-elc-audit-engine-design.md §9 M1
- **Description:** 專案骨架：uv 專案初始化、config、目錄結構
- **Acceptance criteria:**
  - uv 專案可初始化並執行
  - config 結構就緒
  - 目錄結構符合技術棧慣例（沿用 DrtoolboxLocalServer 佈局，見 D4）
- **Scope:** Phase 1
- **Status:** NOT STARTED — next actionable milestone

## REQ-rule-repository

- **Source:** progress.md §四 M2; docs/plans/2026-07-29-elc-audit-engine-design.md §9 M2
- **Description:** 規則庫建置：CSV→SQLite（payment_rules/drug_rules）、審查注意事項→PageIndex、rule_mapping 預編譯
- **Acceptance criteria:**
  - [x] SQLite payment_rules/drug_rules 可查詢 — 完成於 02-02-PLAN.md（2,669 payment_rules + 11,273 drug_rules 列，`data/db/rules.sqlite3`）
  - [x] PageIndex 樹狀索引涵蓋 officialdocument/審查注意事項/ 全部文件 — 完成於 Plan 02-03（自建 python-docx+regex+JSON 索引，非 pageindex 雲端套件；32 檔案、1633 節點）
  - [x] rule_mapping 預編譯快取命中率可驗收（抽20個常見醫令如01015C、64140C人工核對，見 constraints.md C6）— 建置完成於 02-04-PLAN.md（13,942/13,942 碼全數處理：6,802 CSV 重用＋558 LLM 比對＋6,582 誠實無匹配）；20 碼人工核對於 02-05-PLAN.md 完成，使用者確認全數 20/20 正確
- **Scope:** Phase 1
- **Status:** COMPLETE — 3 of 3 acceptance criteria complete (02-02, 02-03, 02-04/02-05)

## REQ-parsers

- **Source:** progress.md §四 M3; docs/plans/2026-07-29-elc-audit-engine-design.md §9 M3
- **Description:** 解析器：申報XML（tdata/ddata/pdata）、核減清單、SOAP文字
- **Acceptance criteria:**
  - 可解析申報XML的tdata/ddata/pdata欄位（欄位詳細定義見 constraints.md C11）
  - 欄位缺漏分級處理（致命 vs 可容忍，見 constraints.md C5）
  - SOAP文字可分段定位(S/O/A/P)
- **Scope:** Phase 1

## REQ-record-aggregator

- **Source:** progress.md §四 M4; docs/plans/2026-07-29-elc-audit-engine-design.md §9 M4
- **Description:** 病歷彙整器：Provider介面＋本地檔案Provider（半年病史時間軸）
- **Acceptance criteria:**
  - Provider介面抽象化雲端/本地資料來源
  - 本地檔案Provider可運作（Phase 1 頂替雲端）
  - 產出近半年病史時間軸（就診紀錄/檢驗/檢查/影像清單）
- **Status:** SATISFIED — Phase 11.1（2026-08-10）重新達成：`LocalFileProvider` 已接入 `/api/sampling/audit` 與 `/api/appeal/generate` 生產路徑（`RECORDS_DIR`＋`build_timeline`，取代寫死的 `timeline=None`）；unconfigured/no_record_no/absent 三態誠實降級＋前端可見呈現。v1.0-MILESTONE-AUDIT.md 第 2 輪判定 unsatisfied 已閉合（11.1-VERIFICATION.md 12/12）。
- **Scope:** Phase 1（+ Phase 11.1 整合閉合）

## REQ-three-way-comparator

- **Source:** progress.md §四 M5; docs/plans/2026-07-29-elc-audit-engine-design.md §9 M5
- **Description:** 三方比對器：醫令↔規則↔病歷 支持度判定（含候選補強生成）
- **Acceptance criteria:**
  - 逐檢核項判定支持/部分支持/無記載＋引用原文（見 constraints.md C1）
  - 醫令支持度三級分類（充分/薄弱/裸奔）
  - 缺口生成1~3條候選補強敘述並符合約束（見 constraints.md C2）
- **Scope:** Phase 1

## REQ-output-reinforcement-report

- **Source:** progress.md §四 M6; docs/plans/2026-07-29-elc-audit-engine-design.md §9 M6
- **Description:** 輸出一：病歷補強報告.md 生成（checkbox 逐條審格式）
- **Acceptance criteria:**
  - Markdown checkbox 檢核表格式
  - 含醫令支持度缺口、半年病史摘要、候選補強敘述（逐條點選）
  - 醫師可勾選/編輯後存檔
- **Scope:** Phase 1

## REQ-output-appeal-draft

- **Source:** progress.md §四 M7; docs/plans/2026-07-29-elc-audit-engine-design.md §9 M7
- **Description:** 輸出二：申復理由草稿（p8/p9 ≤2000字）＋申復XML欄位
- **Acceptance criteria:**
  - 四段組裝式結構（案情摘要/醫療必要性/規則依據/病歷佐證，見 decisions.md D10）
  - 字數控制器裁剪規則（見 constraints.md C4）
  - P6強制填0硬檢查（見 constraints.md C3, C8）
  - 每筆核減醫令獨立生成
  - 輸出 `申復草稿_{案件流水號}.md` ＋ `appeal_{流水號}.json`（見 constraints.md C7）
- **Scope:** Phase 1

## REQ-e2e-testing

- **Source:** progress.md §四 M8; docs/plans/2026-07-29-elc-audit-engine-design.md §9 M8
- **Description:** 端到端測試：規格造測試資料→待真實樣本進來替換驗證
- **Acceptance criteria:**
  - 五層測試策略全數涵蓋（單元/規則庫驗收/LLM判定金標準30組/端到端3案例/真實樣本回放，見 constraints.md C6）
- **Scope:** Phase 1

## REQ-phase2-his-integration (placeholder, low detail)

- **Source:** progress.md §四 Phase 2; docs/plans/2026-07-29-elc-audit-engine-design.md §9 Phase2 note
- **Description:** 雲端病歷Provider接doctor-toolbox（cloud_sync/his_connection模式）；Flask API化供HIS呼叫；與Local Agent/NHI_EIIAPI上傳流程銜接
- **Acceptance criteria:** not yet detailed — later phase, lightweight placeholder only
- **Scope:** Phase 2
- **Supporting context (informational only, not requirements-level detail):** 電子抽審.md §一~§四, §四 sTypeCode API 參數 (constraints.md C10), 檔案格式/命名規範 (constraints.md C9), FHIR/HL7 mapping (constraints.md C12)

## REQ-paper-appeal-print

- **Source:** 2026-08-08 使用者裁示（檢討電子 vs 紙本兩種抽審申復流程覆蓋現況時發現的缺口）；官方範本 `officialdocument/電子申復文件格式/30396_*`（105.04.01 修訂版）
- **Description:** 紙本抽審與申復流程的辨識輸入（PDF/JPEG/BMP OCR）與內部資料處理（`CaseStore`／`AppealDraft`）已與電子流程共用引擎（Phase 3/7/9），但輸出端只有 Markdown／JSON／申復 XML，缺少可列印的紙本申復清單。本需求新增 PDF 排版輸出通道，供未串接 HIS 或選擇紙本作業的院所使用。
- **Acceptance criteria:**
  - PDF 版面與官方三聯式「門診醫療費用點數申復清單」範本逐欄核對一致（見 Phase 11 Success Criteria 完整欄位清單）
  - 直接消費既有 `AppealDraft` 資料，不重建資料模型
  - 三聯版式差異（**第二聯**（健保署存查聯）「中央健康保險署填列」核定/複核/初核/審查委員欄，留空供健保署複核）正確反映（2026-08-08 使用者裁示以官方模板第二聯為準）
- **Scope:** Phase 11
- **Supporting context (informational only):** `.odt` 可編輯範本可作為排版依據來源（ODF XML 可解析，延續 Phase 2 docx-tree 索引器的 LibreOffice/soffice 工具鏈慣例，避免引入新的重量級 PDF 套件）

---

## Notes

- No competing acceptance-criteria variants were found across sources for any requirement — the SPEC's milestone descriptions are elaborations of, not alternatives to, the LOCKED ADR roadmap.
- All non-functional constraints (error handling, hard-checks, testing tiers, file/XML formats) are catalogued separately in `.planning/intel/constraints.md` and referenced from the relevant requirement above rather than duplicated here.
