# PROJECT.md — elc-audit-engine

## What This Is

`elc-audit-engine` is a local-first engine that automates two stages of Taiwan's National Health Insurance (健保) electronic audit (電子抽審) workflow for a medical clinic:

1. **病歷補強 (pre-submission record reinforcement)** — before a case is submitted for audit, identify which medical orders (醫令) lack adequate documentary support against the payment rules, and generate candidate reinforcement narratives for physician review.
2. **申復生成 (post-denial appeal generation)** — after a case is denied (核減), generate a draft appeal (p8/p9 fields, ≤2000 Chinese characters) citing the relevant rule text and supporting medical record evidence.

Both stages share a single comparison pipeline (order ↔ rule ↔ record three-way matcher); only the output differs.

**v1.0 擴充（2026-08-10 shipped）：** 新增紙本申復清單輸出通道（官方三聯式 PDF，`build_appeal_print.py` CLI＋`render_appeal_print` 純函式）、HIS 服務化（Flask API：案件匯入/預審/申復生成/狀態機＋任務佇列）、以及 Phase 4 病歷時間軸的生產路徑接入（`LocalFileProvider`＋`RECORDS_DIR`，兩端點不再以 `timeline=None` 降級）。

source: progress.md D3；v1.0-MILESTONE-AUDIT.md（2026-08-10）

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

source: progress.md §一 (D1-D12, LOCKED)

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

## Validated Requirements（v1.0 shipped，2026-08-10）

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

## Context（v1.0 after）

- **Codebase:** ~10,071 行 Python（src/ + server.py + scripts/）；Flask API（server.py 884 行）；測試基線 442 passed / 2 skipped（444 collected，2026-08-11 更新：P2-9 日期驗證修復＋4 新測試）
- **Tech stack:** Python 3.12 + uv、Flask、SQLite、python-docx、ChromaDB（auxiliary RAG）、pypdf、llama.cpp（local LLM，localhost:8080）、pillow-heif（2026-08-11 新增，供樣本影像轉換用）
- **Shipped 2026-08-10:** 13 phases（12 complete＋Phase 10 外部阻塞），25 plans，38 tasks，164 commits
- **Known debt:** rule_mapping 46% 無匹配率（recall 限制，deferred）；e2e 第 5 層真實樣本待取得；Phase 9 未做 rate limiting／API key 輪替；紙本抽審名冊 OCR 路徑（`sampling.py`/`table_ocr.py`）缺真實樣本驗證

## Current Milestone: v1.1 紙本→數位化整合三項輸出

**Goal：** 降低診所導入電子抽審與申復的門檻——補齊「影像佐證上傳」「核減明細原格式列印」「審核軌跡+病歷摘要+申復理由+影像佐證包列印」三項輸出/輸入通道，讓已習慣紙本作業的診所能漸進轉換到數位流程。

**Target features：**
- **影像佐證上傳**：接收 procedure/sono/X-ray 影像上傳，依案件流水號命名關聯，`has_attachment` 改由「是否有實際上傳檔案」真實驅動 `p7=Y/N`（現行為手動旗標，見 `generators/appeal.py`）。不做 OCR／不做結構化欄位擷取——影像是給人審查的視覺佐證，不是給系統解析文字。
- **核減明細原格式列印**：系統處理完核減資料後，印出跟官方核減清單原始紙本一致的版面（RCPI2021R01/RCPI2001R01/RCPI2012R01 那種計算式/逐案表格版式）。比照 Phase 11 的 ODT 填值模式（`generators/appeal_print/`），但需要全新模板——版型跟申復清單完全不同，不能重用既有模板。
- **審核軌跡+病歷摘要+申復理由+影像佐證包列印**：`generators/tracking.py`（審核軌跡 JSON）、`generators/reinforcement_report.py`（病歷補強 Markdown）目前都沒有列印排版格式。此項要把文字內容（軌跡/摘要/申復理由）與影像圖片合成一份可列印佐證包，可能跟 Phase 11 的三聯申復清單合訂寄出。

**Key context：**
- 三項工程量都各自接近或超過 Phase 11（3 個 plan）量級，彼此不共用太多程式碼，各自獨立 phase 規劃與執行。
- 已推翻「核減數據需要從紙本影像萃取結構化欄位」的假設——健保局已透過 VPN 提供 CSV（D-14c/D-14d），紙本照片多半只是診所留底，不是流程必要輸入。
- 官方 XML 的 `p7` 欄位本質是 Y/N 旗標，XML 與 PACS 影像本來就分開送審（`generators/appeal_xml.py` 已有 `p7` 欄位序列化邏輯）。
- 背景依據：`.planning/intel/paper-scan-samples.md`（2026-08-11 會話盤點的 7 張核減明細照片＋16 頁申復佐證 PDF 真實樣本分析，含 PHI，已 gitignore）。
- 不含本次範圍：紙本抽審名冊 OCR 驗證（`sampling.py`/`table_ocr.py` 現有程式碼缺真實樣本驗證，留待後續 milestone）。

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
*Last updated: 2026-08-11 — v1.1 milestone started*
