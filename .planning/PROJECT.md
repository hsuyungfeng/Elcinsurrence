# PROJECT.md — elc-audit-engine

## What This Is

`elc-audit-engine` is a local, file-in/file-out engine that automates two stages of Taiwan's National Health Insurance (健保) electronic audit (電子抽審) workflow for a medical clinic:

1. **病歷補強 (pre-submission record reinforcement)** — before a case is submitted for audit, identify which medical orders (醫令) lack adequate documentary support against the payment rules, and generate candidate reinforcement narratives for physician review.
2. **申復生成 (post-denial appeal generation)** — after a case is denied (核減), generate a draft appeal (p8/p9 fields, ≤2000 Chinese characters) citing the relevant rule text and supporting medical record evidence.

Both stages share a single comparison pipeline (order ↔ rule ↔ record three-way matcher); only the output differs.

source: progress.md D3

## Why

Today the audit/appeal process is entirely manual and paper-based: print the audit notice, manually pull paper charts, photocopy records/labs/imaging, hand-assemble a submission packet, mail it, wait, and — if denied — hand-write an appeal and mail it again. This project automates the record-reinforcement and appeal-drafting steps using a local LLM, without requiring the clinic's cloud HIS integration to exist yet.

source: 電子抽審.md §一 (As-Is流程圖)

## Two-Phase Roadmap (LOCKED)

- **Phase 1** — an independent, decoupled engine: core comparison/generation logic separated from data source. Runs entirely local, file-in/file-out. This is the phase covered by the roadmap below (M1-M8).
- **Phase 2** — package the Phase 1 engine as a `doctor-toolbox` HIS module: cloud medical-record Provider via `doctor-toolbox`, Flask API-ification for HIS calls, and integration with the Local Agent / `NHI_EIIAPI` upload flow described in 電子抽審.md.

source: progress.md D1 (LOCKED)

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
