# PROJECT.md — elc-audit-engine

## What This Is

`elc-audit-engine` is a local-first engine that automates two stages of Taiwan's National Health Insurance (健保) electronic audit (電子抽審) workflow for a medical clinic:

1. **病歷補強 (pre-submission record reinforcement)** — before a case is submitted for audit, identify which medical orders (醫令) lack adequate documentary support against the payment rules, and generate candidate reinforcement narratives for physician review.
2. **申復生成 (post-denial appeal generation)** — after a case is denied (核減), generate a draft appeal (p8/p9 fields, ≤2000 Chinese characters) citing the relevant rule text and supporting medical record evidence.

Both stages share a single comparison pipeline (order ↔ rule ↔ record three-way matcher); only the output differs.

**v1.0 擴充（2026-08-10 shipped）：** 新增紙本申復清單輸出通道（官方三聯式 PDF，`build_appeal_print.py` CLI＋`render_appeal_print` 純函式）、HIS 服務化（Flask API：案件匯入/預審/申復生成/狀態機＋任務佇列）、以及 Phase 4 病歷時間軸的生產路徑接入（`LocalFileProvider`＋`RECORDS_DIR`，兩端點不再以 `timeline=None` 降級）。

**v1.1 擴充（2026-08-11 shipped）：** 新增三項紙本→數位化輸出/輸入通道——影像佐證上傳（`attachment_store.py`，驅動 `has_attachment`/`p7` 真實旗標）、核減明細原格式列印（`generators/deduction_print/`）、審核軌跡＋佐證包合成列印（`generators/evidence_packet/`）。milestone 收尾稽核發現並修復一處跨 phase 串接缺陷（見下方 Key Decisions）。

source: progress.md D3；v1.0-MILESTONE-AUDIT.md（2026-08-10）；v1.1-MILESTONE-AUDIT.md（2026-08-12）

## Why

Today the audit/appeal process is entirely manual and paper-based: print the audit notice, manually pull paper charts, photocopy records/labs/imaging, hand-assemble a submission packet, mail it, wait, and — if denied — hand-write an appeal and mail it again. This project automates the record-reinforcement and appeal-drafting steps using a local LLM, without requiring the clinic's cloud HIS integration to exist yet.

source: 電子抽審.md §一 (As-Is流程圖)

## Two-Phase Roadmap (LOCKED)

- **Phase 1** — an independent, decoupled engine: core comparison/generation logic separated from data source. Runs entirely local, file-in/file-out. This is the phase covered by the roadmap below (M1-M8).
- **Phase 2** — package the Phase 1 engine as a `doctor-toolbox` HIS module: cloud medical-record Provider via `doctor-toolbox`, Flask API-ification for HIS calls, and integration with the Local Agent / `NHI_EIIAPI` upload flow described in 電子抽審.md.

**v1.0 進度（2026-08-10）：** Phase 1 的服務化部分（Flask API、Provider 接線）已於 milestone v1.0 完成；Phase 2 剩餘的 VPN／實機串接（雲端 Provider、NHI_EIIAPI wrapper、Local Gateway 七元件）因外部依賴阻塞，不計入 v1.0 範圍。

source: progress.md D1 (LOCKED)；v1.0-MILESTONE-AUDIT.md

## Core Architecture (LOCKED)

```text
   輸入層                     共用比對引擎 (Core)                  輸出層
─────────────      ┌──────────────────────────────────┐    ─────────────
申報XML(抽審案件)──►│ ① 解析器: XML/核減檔/SOAP          │──► 病歷補強報告.md
核減清單檔      ──►│ ② 病歷彙整器: 近半年雲端病歷整合     │    · 醫令支持度缺口
                   │    (就診紀錄/檢驗/檢查/影像清單)     │    · 半年病史摘要
雲端病歷(半年) ──►│ ③ 規則庫: PageIndex+預編譯快取      │    · 附件建議清單
  Provider介面     │    +支付規定SQLite+ChromaDB輔助     │
                   │ ④ 比對器: 醫令↔規則↔病歷 三方比對   │──► 申復理由草稿
過去申復案例    ──►│ ⑤ 生成器: llama.cpp :8080          │    p8/p9 ≤2000字
                   └──────────────────────────────────┘    +申復XML欄位
```

source: progress.md §二 (LOCKED)

## Key Locked Decisions (see `.planning/intel/decisions.md` for full detail)

| # | Decision |
|---|---|
| D1 | Two-phase roadmap: standalone engine (Phase 1) → doctor-toolbox HIS module (Phase 2) |
| D2 | LLM engine: llama.cpp server (localhost:8080), Ornith-1.0-9B Q6_K_XL, n_ctx 32768, OpenAI-compatible API. Patient data never leaves the machine. |
| D3 | Reinforcement + appeal generation share one comparison pipeline; only output differs |
| D4 | Tech stack reuse from `~/Desktop/DrtoolboxLocalServer`: Python + uv, Flask, python-docx, pandas, pageindex, SQLite |
| D5 | Reinforcement report integrates ~6 months of cloud medical records via a Provider interface; local-file Provider substitutes when cloud is unavailable |
| D6 | Rule retrieval: PageIndex (primary, clause-tree navigation) + rule_mapping precompiled cache (order↔clause, zero-LLM lookup); ChromaDB is auxiliary only |
| D7 | Comparator judges per checklist item (支持/部分支持/無記載 + quoted source text); three-tier order support level: 充分/薄弱/裸奔 |
| D8 | Gaps generate 1-3 candidate reinforcement narratives for physician pick-list; must be grounded in existing record clues, never fabricated |
| D9 | Physician review: line-by-line (採用/編輯後採用/略過/標記不符事實) + final full-draft edit pass; full audit trail JSON retained |
| D10 | Appeal structure: 4 assembled sections (案情摘要/醫療必要性/規則依據/病歷佐證), independently generated, trimmed ④→② first if >2000 chars, P6 hard-coded to 0 when not appealing |
| D11 | Layered failure degradation (LLM timeout → manual-review flag, doesn't block case) + 5-tier test strategy |
| D12 | Self-learning feedback loop: adoption-rate + hallucination-flag + appeal-outcome signals feed prompt/LoRA improvement; two-tier privacy (record data stays local; rule_mapping/argument skeletons/stats may be shared cross-clinic via doctor-toolbox) |
| D13 | (v1.1) Evidence-packet attachment lookup must key off `case.case_seq`, not `case_id` — the two are distinct, independently-populated columns in `CaseRecord`, and `attachment_store` writes exclusively to the `case_seq` keyspace. Found via milestone audit cross-phase integration check, fixed same-day (`3f7f097`). ✓ Good — codified as regression test. |

source: progress.md §一 (D1-D12, LOCKED); v1.1-MILESTONE-AUDIT.md (D13)

## Rule Repository Layering (LOCKED)

1. **結構化層 (SQLite)** — `payment_rules` ← 醫療服務給付項目 CSV; `drug_rules` ← 藥品項查詢項目檔 CSV
2. **條文層 (PageIndex)** — corpus: `officialdocument/審查注意事項/*.doc(x)`; `rule_mapping` precompiled cache: (醫令代碼, 科別, 文件版本) → [條文位置, 條文全文]
3. **輔助層 (ChromaDB)** — free-text / similar-case queries only

source: progress.md §三 (LOCKED); elaborated by docs/plans/2026-07-29-elc-audit-engine-design.md §3.1-3.3

## Stakeholders / Users

- **Physician (醫師)** — reviews and approves/edits every generated reinforcement candidate and appeal draft; ultimate responsibility holder (D9)
- **Clinic operator (院所)** — owns the `doctor-toolbox` / `DrtoolboxLocalServer` ecosystem this project extends (Phase 2)

## Out of Scope (Phase 1)

- Cloud HIS integration, Flask API exposure, Local Agent / `NHI_EIIAPI` VPN upload bridge — all deferred to Phase 2 (see REQ-phase2-his-integration)
- FHIR/HL7 mapping, DICOM/PDF packaging, sTypeCode upload protocol — background reference only (電子抽審.md), not Phase 1 engineering scope

source: constraints.md C9, C10, C12; context.md (Phase 2 topics)

## Source Documents

| Doc | Type | Precedence | Status |
|---|---|---|---|
| `progress.md` | ADR | 0 | LOCKED — 12 decisions authoritative |
| `docs/plans/2026-07-29-elc-audit-engine-design.md` | SPEC | 1 | Elaborates ADR, no contradictions |
| `電子抽審.md` | DOC | 2 | Background/context + field-level schema detail |

Full traceability: `.planning/intel/decisions.md`, `.planning/intel/requirements.md`, `.planning/intel/constraints.md`, `.planning/intel/context.md`

## Validated Requirements

**v1.0 shipped，2026-08-10：**

- ✓ **REQ-project-skeleton** — uv 專案＋config＋目錄結構（01-01-VERIFICATION passed）
- ✓ **REQ-rule-repository** — CSV→SQLite＋審查注意事項樹狀索引＋rule_mapping 預編譯（3/3 驗收，20 碼人工核對 20/20）
- ✓ **REQ-parsers** — 申報 XML／核減清單／SOAP 三解析器（真實檔回放 633 案／0 拒收）
- ✓ **REQ-record-aggregator** — RecordProvider ABC＋LocalFileProvider＋半年病史時間軸（v1.0 重新達成：已接入 Flask API 生產路徑，11.1-VERIFICATION 12/12）
- ✓ **REQ-three-way-comparator** — 醫令↔規則↔病歷三方比對（139 passed）
- ✓ **REQ-output-reinforcement-report** — 病歷補強報告.md（152 passed）
- ✓ **REQ-output-appeal-draft** — 申復理由草稿＋申復 XML（`render_appeal_json` 契約穩定）
- ⚠️ **REQ-e2e-testing** — 五層 1-4 完整；第 5 層真實樣本回放受限於 ground truth 數據缺口（partial）
- ⚠️ **REQ-phase2-his-integration** — 服務化部分 satisfied（Flask API）；VPN 實機串接外部依賴阻塞（partial，milestone 範圍外）
- ✓ **REQ-paper-appeal-print** — 紙本申復清單三聯 PDF（VERIFICATION 3/3＋UAT 7/7）

**v1.1 shipped，2026-08-11：**

- ✓ **REQ-attachment-upload** — 影像佐證上傳（`attachment_store.py`，Magic Bytes＋路徑安全＋HEIC 支援），`has_attachment`/`p7` 由實體檔案真實驅動（v1.1-MILESTONE-AUDIT 驗證端到端）
- ✓ **REQ-deduction-print** — 核減明細原格式 PDF 列印（ODT 動態列展開＋soffice 轉檔），CLI＋API 雙通道
- ✓ **REQ-evidence-packet-print** — 審核軌跡＋佐證包合成 PDF；milestone 稽核發現 `case_id`/`case_seq` 混用缺陷並同日修復（commit `3f7f097`），修復後驗證 satisfied

## Context（v1.1 after）

- **Codebase:** ~10,071+ 行 Python（v1.0 基線）＋ v1.1 新增 `attachment_store.py`、`generators/deduction_print/`、`generators/evidence_packet/`（61 files changed, +4624/-120 since v1.0 tag）；Flask API 新增 5 個 route
- **Tech stack:** Python 3.12 + uv、Flask、SQLite、python-docx、ChromaDB（auxiliary RAG）、pypdf、llama.cpp（local LLM，localhost:8080）、pillow-heif（HEIC 支援）
- **Test baseline:** 460 passed / 2 skipped（v1.1 收尾，含 2 個新增 case_seq/case_id 迴歸測試）
- **Shipped 2026-08-11 (v1.1):** 3 phases，7 plans，13 tasks，36 commits
- **Known debt:**
  - rule_mapping 46% 無匹配率（recall 限制，deferred，v1.0 遺留）
  - e2e 第 5 層真實樣本待取得（v1.0 遺留）
  - Phase 9 未做 rate limiting／API key 輪替（v1.0 遺留）
  - 紙本抽審名冊 OCR 路徑（`sampling.py`/`table_ocr.py`）缺真實樣本驗證（v1.0 遺留）
  - `RCPI2012R01_核減明細表_print_base.odt` 為手工建立的最小 ODT scaffold，非官方原始表單——待取得官方表單後替換並重算 SHA256（v1.1 已知，non-blocking）
  - Phase 12 `12-VALIDATION.md` 簽核清單過期（仍顯示 draft/pending），與 SUMMARY.md 記錄的實際完成狀態不符——建議執行 `/gsd-validate-phase 12` 補簽

## Next Milestone Goals

v1.1 已完整交付，暫無下一 milestone 規劃。啟動下一輪請執行 `/gsd-new-milestone`（會重新進行 questioning → research → requirements → roadmap）。

候選方向（未經需求訪談驗證，僅為觀察）：
- Phase 12 VALIDATION.md 簽核補正（低成本，可獨立完成）
- `RCPI2012R01` 官方 ODT 模板取得與替換
- 紙本抽審名冊 OCR 真實樣本驗證（v1.0 遺留 known debt）
- Phase 10 VPN／實機串接（若 doctor-toolbox 存取權與 NHI_EIIAPI 實機環境到位）

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition**（via `/gsd-transition`）:
1. Requirements invalidated？→ Move to Out of Scope with reason
2. Requirements validated？→ Move to Validated with phase reference
3. New requirements emerged？→ Add to Active
4. Decisions to log？→ Add to Key Decisions
5. "What This Is" still accurate？→ Update if drifted

**After each milestone**（via `/gsd-complete-milestone`）:
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-08-12 — v1.1 milestone shipped and archived*
