# Phase 2: 規則庫建置 - Research

**Researched:** 2026-07-30
**Domain:** Local structured-data + document-tree rule repository (SQLite + custom "PageIndex-style" docx tree index + LLM-assisted precompiled cache), fully offline
**Confidence:** MEDIUM (HIGH on verified codebase/data facts, LOW→escalated-to-flagged on the `pageindex` PyPI package — see Critical Finding below)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**SQLite 欄位範圍**
- **D-01:** `payment_rules`（來自「醫療服務給付項目...CSV」）與 `drug_rules`（來自「藥品項查詢項目檔...CSV」）只存比對器實際會用到的核心欄位：代碼、中文名稱、支付規定／給付規定文字、生效起訖日期。
- **D-02:** 不搬遷 CSV 其餘欄位（如藥品項的 AI-note、連結、劑型、藥商、ATC 代碼等 22 欄中的非核心欄位）。若未來需要，回頭查原始 CSV 或另建輔助表，不現在擴充 schema。
- 來源 CSV 欄位確認（scout codebase 時實際讀取）：
  - `醫療服務給付項目251027準確板_已優化填入支付規定.csv` → 7 欄：診療項目代碼／健保支付點數／生效起日／生效迄日／英文項目名稱／中文項目名稱／支付規定
  - `藥品項查詢項目檔260605 AI 摘要支付價大於0.csv` → 22 欄，核心取用：藥品代號／藥品中文名稱／給付規定／有效起日／有效迄日

**PageIndex 涵蓋範圍**
- **D-03:** `officialdocument/審查注意事項/` 底下**全部** .docx 檔案都納入 PageIndex 樹狀索引，包含：
  - 21 份科別/一般原則審查注意事項檔案
  - 1 份 400K 的「西醫基層醫療費用審查注意事項-附表.docx」
  - 1 份 416K 的「2-2-7第二部第二章第七節手術-113.12.01.docx」（章節式健保手術規定，文件結構與科別檔案不同）
- 不同文件類型（科別條列式 vs 章節式法規）若解析結構差異過大，規劃階段需評估是否需要不同的 PageIndex 建置策略/前處理，但範圍上兩者都必須涵蓋（符合 REQ-rule-repository「涵蓋全部 .doc/.docx 文件」驗收標準）。

**rule_mapping 建置方式**
- **D-04:** LLM 輔助建置：用 llama.cpp 讀取 PageIndex 條文樹，針對每個醫令代碼建議可能對應的條文位置，一次性批次生成 rule_mapping 快取。
- **D-05:** 建置完成後，查詢階段（供 Phase 3-5 使用）完全零 LLM — 只走快取查表。LLM 只在「建置」這個一次性步驟使用，不在線上查詢路徑。
- **D-06:** 20 個常見醫令代碼的人工核對驗收清單：Claude 從兩份 CSV 中挑選具代表性、涵蓋不同類型（檢查/處置/治療/藥品/手術等）的高頻項目作為候選清單草案，執行階段交由使用者最終核對每項對應的條文位置是否正確。
  - 草案挑選原則：優先選擇「支付規定」/「給付規定」欄位非空、內容具體（非純數字或 null）的項目，確保驗收時有實質條文內容可核對。
  - 範例候選（非最終清單，規劃/執行階段應正式列出 20 項）：06012C（尿一般檢查）、06013C（尿生化檢查）、05316C（PCA 病患自控式止痛）、05401C-05406C（精神復健/居家治療系列，可挑 1-2 項代表）等，並需搭配 progress.md/電子抽審.md 中已提及的 01015C、64140C。
  - **RESEARCH UPDATE:** `01015C` was verified NOT to exist in either CSV during this research — see Open Questions for a replacement recommendation.

**對外介面設計**
- **D-07:** rule_repository 模組對下游只曝露**單一查詢函式**：輸入醫令代碼，回傳一個結構化結果（dataclass 或等效型別），內含：支付規定文字（SQLite 來源）、對應條文位置與全文（PageIndex/rule_mapping 來源）。
- **D-08:** 三層（SQLite/PageIndex/rule_mapping）的內部組合、快取命中判斷、零 LLM 保證，都封裝在這個函式內部；下游（Phase 3-5 的解析器、比對器）不需要知道內部是資料庫查詢還是快取查表。
- 這個介面決策會影響所有後續 phase 的整合方式，規劃階段應優先鎖定此函式簽章。

**ChromaDB 基礎架構（順便建立，非本階段驗收項）**
- **D-09:** Phase 2 順便將 PageIndex 條文全文做 embedding 存入 ChromaDB，建立基礎架構完整性，避免 Phase 5 比對器需要自由文字查詢時回頭修改規則庫 schema。
- **注意：** 此項不在 REQ-rule-repository 的 3 項驗收標準內（SQLite 查詢、PageIndex 涵蓋、rule_mapping 命中率）——規劃階段應將 ChromaDB 建置列為附加/低優先任務，不可排擠三項核心驗收標準的完成度。若時間/複雜度超出預期，可將 ChromaDB 部分拆到獨立任務或延後，但不應阻塞核心驗收。

### Claude's Discretion
- 20 個驗收醫令代碼的最終清單（D-06 草案將在規劃或執行階段與使用者確認最終版本；`01015C` 需替換，見 Open Questions）
- PageIndex 對不同文件結構（科別條列式 vs 手術章節式）的前處理/解析策略細節
- SQLite schema 的確切欄位名稱與型別

### Deferred Ideas (OUT OF SCOPE)
- ChromaDB 完整運用（自由文字/類似案例查詢的實際使用場景）延後至 Phase 5（三方比對器）— Phase 2 只建立基礎架構（D-09），不實作查詢邏輯。
- 手術章節式文件（2-2-7...docx）與科別條列式文件的解析策略差異，若規劃階段發現複雜度顯著提高，可考慮是否值得拆分成更細的任務，但仍屬 Phase 2 範圍內。
- **候補工具評估：[OfficeCLI](https://github.com/iOfficeAI/OfficeCLI)**（iOfficeAI，Apache 2.0）— 離線、免安裝 Office、支援 .docx 結構化讀取（輸出 JSON/HTML），理論上可替代/輔助 python-docx 做 Phase 2 的 docx 文字擷取。**不在本階段引入**：(1) 與 D4 鎖定技術棧（Python+uv+python-docx+pageindex）重疊，額外引入一個 .NET runtime 打包的獨立 binary/MCP server 增加執行環境複雜度；(2) Phase 2 真正瓶頸是 PageIndex 條文樹索引與 rule_mapping 建置，不是 docx 文字擷取本身；(3) 對 CSV 規則資料（pandas 已鎖定）沒有幫助。**待評估時機：** 若研究員報告或執行階段實際發現 python-docx 在解析「附表.docx」（表格/樣式層級還原）或章節式手術規定檔案時遇到具體格式還原困難，可將 OfficeCLI 當作局部替換方案重新評估，而非現在整包導入。
  - **RESEARCH NOTE:** This research independently confirms python-docx (already installed v1.2.0) handles all sampled cases correctly — including the table-heavy 附表 doc (via `iter_inner_content()`) and the flat-structured 2-2-7 surgery doc (via regex hierarchy parsing) — so the OfficeCLI re-evaluation trigger condition described above has NOT been hit. python-docx remains sufficient; no fallback needed at this time. The one genuinely new gap found (legacy `.doc` binary files) is NOT a python-docx capability gap and is NOT what OfficeCLI would solve either (OfficeCLI's stated scope is also `.docx`, not legacy `.doc`) — it requires a separate format-conversion step (LibreOffice), addressed below.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REQ-rule-repository | 規則庫建置：CSV→SQLite（payment_rules/drug_rules）、審查注意事項→PageIndex、rule_mapping 預編譯。Acceptance: (1) SQLite payment_rules/drug_rules 可查詢 (2) PageIndex 樹狀索引涵蓋 officialdocument/審查注意事項/ 全部文件 (3) rule_mapping 預編譯快取命中率可驗收（抽20個常見醫令人工核對） | Standard Stack + Architecture Patterns sections give the concrete SQLite schema/loading approach for (1); Architecture Patterns Pattern 1/2 + Common Pitfalls #2 + the newly-surfaced .doc/.docx format-split finding (Metadata section) address (2) including the previously-unflagged legacy `.doc` binary format gap; Don't Hand-Roll + Code Examples + Open Question #3 (CSV `支付規定` may already contain 條文全文 for ~49% of payment codes) directly inform the rule_mapping build strategy and de-risk (3) |
</phase_requirements>

## Summary

Phase 2 builds three layers on top of real, already-scouted source data: two CSVs (payment/drug rules) and 23 .docx review-guideline documents (plus additional legacy `.doc` files discovered during this research — see below). The single most important finding of this research is that **the `pageindex` PyPI package already installed in `pyproject.toml` (v0.2.8) is not a local library — it is a thin HTTP client SDK for `https://api.pageindex.ai`, a paid cloud SaaS that requires an API key and uploads documents for cloud-side OCR/tree-generation** `[VERIFIED: read installed package source at .venv/lib/python3.12/site-packages/pageindex/client.py]`. This directly conflicts with locked decision D2 ("病歷個資不出本機" / nothing leaves the machine) and with D6's "PageIndex" branding, which was clearly intended to reference the open-source self-hostable project of the same name, not this cloud SDK. The planner MUST NOT use the installed `pageindex` package for tree generation or retrieval. Instead, Phase 2 should build a **custom lightweight docx-tree indexer** using `python-docx` (already a dependency, v1.2.0) — this is not a significant scope increase because the actual open-source `VectifyAI/PageIndex` project only supports PDF/Markdown input anyway (no native .docx), so some adaptation layer was always going to be required `[CITED: github.com/VectifyAI/PageIndex README]`.

The two source CSVs were verified directly: the payment CSV has 2,669 rows (not ~4,700 as estimated in CONTEXT.md) and the drug CSV has 11,273 rows (not ~38,000) `[VERIFIED: python csv.DictReader row count]`. Both have unique code columns suitable as SQLite primary keys, UTF-8-with-BOM encoding, and 民國 (ROC) calendar date strings (e.g., `1121001` = 112年10月1日) in the date columns rather than 西元 (Gregoric) dates — this affects date parsing/typing decisions the planner must make explicit. Critically, `01015C` (cited in REQUIREMENTS.md/constraints.md C6 as a canonical acceptance-test example) **does not exist** in the payment CSV and must be replaced in the final 20-code acceptance list; `64140C` does exist and has rich markdown-formatted 條文全文 already embedded in its `支付規定` cell.

The 23 docx files split into at least two structurally distinct families confirmed by direct inspection: (1) 21 specialty files using an inconsistent mix of custom Word styles (`第一層`/`第二層`/`第三層` on some files, absent on others — e.g., 牙醫 and 附表 docs use 100% `Normal` style) with hierarchy actually encoded as plain-text numbering patterns (`一、`, `1.`, `(1)`, `甲、`) rather than real Word outline levels; (2) the chapter-style surgery doc (2-2-7) which is **100% `Normal` style with zero heading styles at all** — hierarchy exists only as text patterns like `第七節`/`第一項`/`一、`. A style-only extraction approach will fail; a regex-based text-pattern hierarchy parser is required as the primary (not fallback) strategy for at least these two families. The 附表 doc additionally contains 27 embedded tables interleaved with paragraphs (56 total tables across all docs) requiring `python-docx`'s built-in `document.iter_inner_content()` (available in installed v1.2.0, verified working) to preserve document order between text and tables.

A further discovery beyond CONTEXT.md's framing: the source directory contains **11 legacy `.doc` (binary Word 97-2003) files** in addition to the 23 `.docx` files — `python-docx` cannot open `.doc` at all. REQ-rule-repository's acceptance criterion explicitly says "全部 .doc/.docx 文件," so these must be converted first. LibreOffice (`soffice`/`libreoffice` 24.2.7.2) is confirmed installed on this machine and can batch-convert via `soffice --headless --convert-to docx`, providing a viable local, offline conversion path. Note: CONTEXT.md had already separately evaluated and deferred `OfficeCLI` as a docx-parsing fallback tool — this research confirms python-docx handles all sampled `.docx` cases (including the table-heavy and flat-structure documents) without needing that fallback; the `.doc` legacy-format gap is a distinct issue OfficeCLI would not have solved either, since it also targets `.docx` only.

**Primary recommendation:** Do not use the installed `pageindex` PyPI package. Convert all legacy `.doc` files to `.docx` via LibreOffice headless conversion as a Wave 0 preprocessing step. Build a custom docx-tree extractor (python-docx + regex heading-pattern detection, keyed by per-file heading-style profile) that outputs a JSON/dict tree with real 條文全文 per node (not just summaries), persist `rule_mapping` as a SQLite table per the original design doc's schema `(醫令代碼, 科別, 文件版本) → [條文位置, 條文全文]`, and treat the llama.cpp-assisted mapping-generation step as a batch script that reads the tree JSON and proposes candidate node matches per code, with all candidates subject to the mandatory 20-item human spot-check before being trusted.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| payment_rules / drug_rules storage & lookup | Database / Storage (SQLite) | — | Exact-match code lookup, tabular data, already CSV-shaped |
| `.doc` → `.docx` conversion (new preprocessing step) | Build tooling (LibreOffice headless, one-time batch) | — | Legacy binary format incompatible with python-docx; must normalize before tree extraction |
| Docx → tree index (custom, replaces cloud "pageindex") | API/Backend (rule_repository module, offline batch build step) | — | Runs once at build time; not a runtime service |
| rule_mapping precompiled cache | Database / Storage (SQLite table) | — | Matches design doc §3.2: cache stored in SQLite, not a separate file format |
| LLM-assisted rule_mapping generation | API/Backend (one-time batch script calling llama.cpp) | — | D-04/D-05: LLM only at build time, never at query time |
| ChromaDB embedding of 條文全文 | Database / Storage (local persistent ChromaDB) | API/Backend (embedding function, local ONNX) | Auxiliary/low-priority per D-09; must stay fully local |
| Single query-function interface | API/Backend (`rule_repository/__init__.py` or new module) | — | D-07/D-08: sole entry point abstracting all 3 internal tiers |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `python-docx` | 1.2.0 (installed, verified) | Parse .docx paragraphs/tables in document order | Already a project dependency (D4); has built-in `iter_inner_content()` for order-preserving paragraph+table traversal `[VERIFIED: Context7 python-docx docs + local test against 附表.docx]` |
| `sqlite3` (stdlib) | bundled with Python 3.12.3, SQLite 3.45.1 | payment_rules/drug_rules/rule_mapping storage | Stdlib, zero new dependency, FTS5 available if full-text search is later needed `[VERIFIED: sqlite3.sqlite_version + in-process FTS5 CREATE VIRTUAL TABLE test]` |
| `pandas` | 2.2.3 (installed, verified via `import pandas; pandas.__version__`) | CSV loading + `to_sql` batch insert | Already a project dependency (D4); `DataFrame.to_sql(..., method="multi", chunksize=N)` is the standard batch-insert pattern for SQLite from pandas |
| `requests` | installed (project dep) | HTTP calls to llama.cpp server's OpenAI-compatible endpoint for rule_mapping build step | Already a dependency; llama.cpp server confirmed running and healthy at `localhost:8080` during this research (`/health` → `{"status":"ok"}`) `[VERIFIED: live curl against running server]` |
| LibreOffice (`soffice`) | 24.2.7.2 (installed, verified) | Batch-convert legacy `.doc` files to `.docx` before tree extraction | Not a Python dependency but a required system tool; confirmed present at `/usr/bin/soffice` on this machine `[VERIFIED: soffice --version]` — standard offline/local approach for `.doc`→`.docx` conversion, no cloud service needed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `chromadb` | 1.5.9 (installed, verified) | D-09 embedding storage, auxiliary/non-blocking | Use built-in default embedding function (ONNX all-MiniLM-L6-v2 via `onnxruntime`, already an installed transitive dep) — fully local after a one-time ~200MB model download from the ONNX/S3 cache on first use `[MEDIUM: WebSearch cross-referenced against multiple sources incl. GitHub issue #2910 and Chroma docs]` |
| `re` (stdlib) | — | Regex-based heading/numbering pattern detection across inconsistent docx styles | Required because Word paragraph styles alone (`第一層`/`第二層`/`第三層`/`Normal`) are inconsistently applied across the 21+ docs — verified directly |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom docx-tree indexer (recommended) | Installed `pageindex` PyPI SDK | Would silently call `api.pageindex.ai` cloud service and require an API key — violates D2 (offline/no-cloud) and D6 branding intent. **Do not use.** |
| Custom docx-tree indexer (recommended) | Self-host `VectifyAI/PageIndex` open-source repo directly | Repo only accepts PDF/Markdown input (`--pdf_path`/`--md_path`), no native .docx support; would require converting 23 docx→PDF or docx→Markdown first, adding a conversion step with its own fidelity risk, and its LLM integration defaults to `gpt-4o` via LiteLLM with unclear local-endpoint config `[CITED: GitHub VectifyAI/PageIndex + secondary blog sources]`. A direct python-docx extractor avoids the conversion step entirely and is simpler for this corpus size (23 files). |
| python-docx (recommended, already installed) | OfficeCLI (iOfficeAI, Apache 2.0) | Already evaluated and explicitly deferred in CONTEXT.md prior to this research; this research confirms no python-docx capability gap exists that would justify revisiting that decision (see Deferred Ideas note above) |
| SQLite for rule_mapping | JSON/pickle file cache | Design doc §3.2 explicitly specifies SQLite storage for rule_mapping; a JSON file would work functionally but breaks from the LOCKED design elaboration and loses transactional/indexed lookup benefits already available via stdlib sqlite3 |
| ChromaDB default local ONNX embedder | Calling llama.cpp `/v1/embeddings` | Tested live against the running llama.cpp server during this research — `/v1/embeddings` returned an error (server likely not launched with `--embeddings` flag / model not embedding-capable) `[VERIFIED: live curl test]`. Use ChromaDB's own local embedding function instead; do not depend on llama.cpp for embeddings unless the server launch flags are confirmed to support it. |
| LibreOffice headless conversion for `.doc` files | Skip legacy `.doc` files entirely | Would violate REQ-rule-repository's explicit "全部 .doc/.docx 文件" acceptance criterion; LibreOffice conversion is a proven, offline, zero-cost path already available on this machine |

**Installation:**
```bash
# No new Python packages needed — python-docx, sqlite3 (stdlib), pandas, chromadb, requests all already present.
# LibreOffice is already installed system-wide (verified: /usr/bin/soffice, v24.2.7.2) — no install step needed.
# Recommendation: REMOVE reliance on the `pageindex` PyPI package for actual indexing logic.
# It can remain in pyproject.toml as an unused dependency if the planner prefers not to touch
# Phase 1's pyproject.toml, but no Phase 2 code should import or call it.
```

**Version verification:** All versions above were verified against the actual installed `.venv` in this repo, not registry lookups, since the environment is already provisioned from Phase 1. `pip show pageindex` / reading `pageindex-0.2.8.dist-info/METADATA` confirms `Requires-Dist: openai (>=1.70.0)` and hardcoded `BASE_URL = "https://api.pageindex.ai"` in `client.py`.

## Architecture Patterns

### System Architecture Diagram

```text
                    BUILD-TIME (one-shot, offline, LLM used once here)
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│  payment CSV ──► pandas.read_csv ──► core-column projection ──► SQLite  │
│  (2,669 rows)                        (D-01/D-02 core cols)     payment_rules
│                                                                          │
│  drug CSV ─────► pandas.read_csv ──► core-column projection ──► SQLite  │
│  (11,273 rows)                       (D-01/D-02 core cols)     drug_rules
│                                                                          │
│  11 legacy .doc files ──► LibreOffice headless convert ──► .docx        │
│                                                                          │
│  23+11 .docx files ──► per-file structure classifier                   │
│         │            (heading-style profile: 第N層 present? Normal-only?)│
│         ▼                                                                │
│  regex-based hierarchy parser (text patterns: 第X節/第X項/一、/(一)/甲、) │
│         │  + python-docx iter_inner_content() for table-interleaved docs │
│         ▼                                                                │
│  docx-tree JSON (node: title, level, path, full_text, table_refs)       │
│         │                                                                │
│         ├──► (D-09, non-blocking) chunk node full_text ──► ChromaDB     │
│         │                          local ONNX embed         (persist_dir)│
│         │                                                                │
│         ▼                                                                │
│  llama.cpp batch script: for each code in payment_rules ∪ drug_rules,   │
│  prompt model with candidate tree nodes (by 科別/keyword pre-filter)    │
│  → propose (條文位置, 條文全文) → write to SQLite rule_mapping           │
│         │                                                                │
│         ▼                                                                │
│  20-code human spot-check (manual verification against real docx text) │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘

                    QUERY-TIME (Phase 3-5 callers, ZERO LLM)
┌──────────────────────────────────────────────────────────────────────────┐
│  醫令代碼 ──► get_rule(code) ──┬─► SQLite payment_rules/drug_rules lookup │
│  (single entry point,          ├─► SQLite rule_mapping lookup            │
│   D-07/D-08)                   └─► merge into RuleResult dataclass       │
│                                       │                                  │
│                                       ▼                                  │
│                              RuleResult(found, payment_text,             │
│                                article_location, article_full_text, …)  │
│                                       │                                  │
│                    not found ──► caller (Phase 3/5) handles per          │
│                                   constraints.md C5 fallback chain       │
└──────────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure
```
src/elc_audit_engine/rule_repository/
├── __init__.py          # public single query function (get_rule / lookup_rule)
├── db.py                # SQLite connection mgmt, schema creation, migrations
├── loaders/
│   ├── payment_loader.py    # CSV → payment_rules table
│   └── drug_loader.py       # CSV → drug_rules table
├── docx_tree/
│   ├── doc_converter.py # LibreOffice headless .doc → .docx preprocessing (new, discovered this research)
│   ├── extractor.py     # per-file structure detection + iter_inner_content traversal
│   ├── patterns.py      # regex hierarchy patterns (第X節/第X項/一、/(一)/甲、 etc.)
│   └── tree_builder.py  # builds tree JSON per document, handles two structure families
├── mapping/
│   ├── build_mapping.py # one-shot LLM-assisted rule_mapping build script (CLI/script, not imported at runtime)
│   └── prompts.py       # prompt templates for candidate-matching
├── embeddings/
│   └── chroma_store.py  # D-09 ChromaDB ingestion (non-blocking, separate from core path)
├── models.py             # RuleResult dataclass (or equivalent) — the D-07 return type
└── scripts/
    └── build_all.py      # orchestrates: doc→docx convert → CSV load → docx tree build → rule_mapping build → (optional) chroma ingest
```

### Pattern 1: Document-order traversal for table-heavy docs
**What:** Use `document.iter_inner_content()` (built into installed python-docx 1.2.0) instead of separately iterating `.paragraphs` and `.tables`, which lose relative ordering.
**When to use:** Any docx with interleaved tables and paragraph headers giving tables semantic names — confirmed present in `西醫基層醫療費用審查注意事項-附表.docx` (27 tables interleaved with paragraph labels like "個案活動能力評估表", "Karnofsky Scale").
**Example:**
```python
# Source: Context7 /websites/python-docx_readthedocs_io_en (verified against installed docx 1.2.0)
import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

d = docx.Document(path)
for block in d.iter_inner_content():
    if isinstance(block, Paragraph):
        handle_paragraph(block.text, block.style.name)
    else:  # Table
        handle_table(block)  # block.rows, block.columns, cell.text
```

### Pattern 2: Regex-based hierarchy detection (primary, not fallback)
**What:** Because Word paragraph styles are inconsistently applied — some docs use `第一層`/`第二層`/`第三層` custom styles for top-level headings but ALL sub-numbering (`1.`, `(1)`, `甲、`) is plain text inside `Normal`/`Body Text Indent N` paragraphs, and at least one doc (`2-2-7...手術...docx`) uses `Normal` style for literally everything including its section/article headers (`第七節`, `第一項`) — a hierarchy parser must primarily match against text patterns, using style name only as a weak secondary signal (e.g., "is this a `第N層` style paragraph, if so treat as depth-1 regardless of text").
**When to use:** All 23+11 docx files (after `.doc`→`.docx` conversion), but especially the two flagged in D-03 as structurally divergent (specialty docs vs. `2-2-7` surgery chapter doc).
**Example:**
```python
# Verified patterns from direct inspection of actual repo docx files during this research
import re

HEADING_PATTERNS = [
    (1, re.compile(r'^第[一二三四五六七八九十百]+部')),      # 第X部 (highest, seen in "第五部居家照護" etc.)
    (2, re.compile(r'^第[一二三四五六七八九十百]+章')),      # 第X章
    (3, re.compile(r'^第[一二三四五六七八九十百]+節')),      # 第X節 (verified: "第七節 手術" in 2-2-7 doc, style=Normal)
    (4, re.compile(r'^第[一二三四五六七八九十百]+項')),      # 第X項 (verified: "第一項 皮膚..." in 2-2-7 doc)
    (5, re.compile(r'^[一二三四五六七八九十]+、')),          # 一、二、三、
    (6, re.compile(r'^\([一二三四五六七八九十]+\)')),        # (一)(二)(三)
    (6, re.compile(r'^\d+\.')),                              # 1. 2. 3.  (verified: 內科 doc uses this)
    (7, re.compile(r'^\([0-9]+\)')),                         # (1)(2)(3)
    (8, re.compile(r'^[甲乙丙丁戊己庚辛壬癸]、')),           # 甲、乙、丙、 (verified: 內科 doc uses this at deepest level)
]
```

### Anti-Patterns to Avoid
- **Trusting `p.style.name` as the sole hierarchy signal:** Verified directly that `牙醫醫療費用審查注意事項.docx` is 100% `Normal` style (134/134 paragraphs) and `2-2-7...手術...docx` is 100% `Normal` (226/226 paragraphs) — a style-only tree builder would produce a completely flat, useless tree for these files.
- **Calling the installed `pageindex` package for anything:** It is a cloud SaaS client. Any call to `PageIndexClient(api_key=...)` or its methods sends the actual document file to `api.pageindex.ai` over the network.
- **Assuming CSV row counts from CONTEXT.md are accurate:** Verified actual counts are 2,669 (payment) and 11,273 (drug), significantly lower than the ~4,700/~38,000 estimates in CONTEXT.md — this is good news for performance (batch insert of these sizes is trivial, sub-second) but the planner should not carry forward the stale estimates into task sizing/time estimates.
- **Treating `01015C` as a valid acceptance-test code:** Verified it does not exist in the payment CSV. Must be replaced before finalizing the 20-code list (see Open Questions).
- **Forgetting the 11 legacy `.doc` files:** CONTEXT.md's D-03 only discusses .docx structural differences; it does not mention that ~11 files in the source directory are the older binary `.doc` format requiring conversion before python-docx can touch them.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Document-order paragraph+table traversal | Custom `iter_block_items()` recipe (the commonly-copied StackOverflow pattern using `CT_P`/`CT_Tbl` low-level XML types) | `document.iter_inner_content()` | Already built into the installed python-docx 1.2.0 — verified working, identical output to the manual recipe, no need to reimplement XML-level traversal |
| CSV → SQLite batch loading | Manual `INSERT` loop with `executemany` hand-rolled batching logic | `pandas.DataFrame.to_sql(table, conn, if_exists="replace", index=False, method="multi", chunksize=500)` | Standard pandas idiom; handles type inference, batching, and column mapping in one call; data sizes here (2.6k/11.3k rows) are small enough that a single `to_sql` call without even chunking would complete in well under a second |
| Local text embeddings for ChromaDB | Custom ONNX/sentence-transformers wrapper | ChromaDB's default embedding function (built-in, uses bundled ONNX all-MiniLM-L6-v2) | Zero additional code; already ships as part of the installed `chromadb==1.5.9` package; runs fully local after one-time model cache download |
| Full-text search over 條文全文 (if ever needed beyond code-based lookup) | Custom substring/keyword scanner | SQLite FTS5 virtual tables | Confirmed available in this Python 3.12.3 / SQLite 3.45.1 build (`CREATE VIRTUAL TABLE ... USING fts5(...)` succeeded in a live test) — no extra dependency, though this is optional/future-scope since core lookup is by 醫令代碼 not free text |
| `.doc` → `.docx` conversion | Custom binary-format parser for legacy Word 97-2003 `.doc` | `soffice --headless --convert-to docx --outdir <dir> <file>.doc` | LibreOffice is a mature, already-installed, offline tool purpose-built for this; hand-rolling a `.doc` binary parser would be substantial unnecessary effort |

**Key insight:** The temptation in this phase is to lean on the `pageindex` package name because it matches the design doc's terminology — but the actual installed package is unrelated cloud tooling. The safest path is to treat "PageIndex" as a *concept* (tree-structured document index preserving article hierarchy) to be implemented directly with already-vetted local tools (python-docx + regex + SQLite), not as a specific library to import.

## Common Pitfalls

### Pitfall 1: `pageindex` package name collision with cloud SaaS
**What goes wrong:** A developer imports `from pageindex import PageIndexClient` (or similar) expecting local tree-building, and the code silently requires/attempts an API key and network call to `api.pageindex.ai`, either crashing (no key) or — worse — actually uploading review-guideline documents to a third-party cloud service.
**Why it happens:** The PyPI package name `pageindex` was pre-declared in Phase 1's `pyproject.toml` based on the design doc's use of the term "PageIndex," without verifying at design time that this specific PyPI package is a cloud client rather than the open-source local library of the same brand name.
**How to avoid:** Do not import the `pageindex` package in any Phase 2 code. Build the tree index directly with python-docx. If a future phase genuinely wants the open-source VectifyAI/PageIndex approach, it would need PDF/Markdown conversion of the docx corpus first plus explicit LiteLLM-to-llama.cpp configuration — treat that as a separate, deliberate decision, not an implicit default.
**Warning signs:** Any `api_key` parameter appearing in rule_repository code; any `requests` call target containing `api.pageindex.ai`; `openai` package imports inside rule_repository code (the installed `pageindex` package depends on and likely re-exports `openai` client conventions).

### Pitfall 2: Style-based-only docx parsing produces a flat tree for several documents
**What goes wrong:** Relying purely on `paragraph.style.name in ('第一層','第二層','第三層')` to detect heading depth silently fails (produces zero detected headings) on documents that use no custom styles at all — verified for 牙醫 doc and the entire 2-2-7 surgery chapter doc.
**Why it happens:** The source docx files were apparently authored/edited across different years and possibly different people, resulting in inconsistent use of Word paragraph styles; some authors typed section numbers as plain text without setting a heading style.
**How to avoid:** Use the regex-based text-pattern detector (Pattern 2 above) as the primary signal for every file; use style name only as a secondary confidence booster when a `第N層` style happens to be present.
**Warning signs:** A built tree with only 1-2 levels of depth for a document that visibly has "第七節 手術" / "第一項 皮膚" section markers in its raw text — this indicates the extractor isn't detecting the text-pattern headings.

### Pitfall 3: 民國 (ROC) calendar dates parsed as Gregorian
**What goes wrong:** Payment/drug CSV date columns (`生效起日`/`生效迄日`/`有效起日`/`有效迄日`) contain values like `1121001` or `20160401` — verified BOTH conventions appear across the two CSVs (payment CSV uses `20160401`-style, i.e., already Gregorian `YYYYMMDD`; drug CSV uses `1121001`-style, i.e., ROC `YYYMMDD`). Naively parsing both columns with the same date format will silently produce wrong dates for one of the two tables.
**Why it happens:** The two CSVs come from different government data extraction pipelines with different date conventions; nothing in the column names (`生效起日` vs `有效起日`) signals the format difference.
**How to avoid:** Verify format per-CSV before writing the loader: payment CSV dates are 8-digit Gregorian (`20160401` = 2016-04-01); drug CSV dates are 7-digit ROC (`1121001` = ROC 112 = 2023, month 10, day 01 — note: the first 3 digits are the ROC year, so this needs `1121001` → year=112+1911=2023, month=10, day=01, i.e., parse as `RRRMMDD` not naive slicing). Store as ISO 8601 (`YYYY-MM-DD`) TEXT or as a normalized INTEGER in SQLite for consistent comparison, and document the source format assumption in the loader code comments so it's auditable.
**Warning signs:** Effective-date filtering logic that returns wrong/no results for known-valid codes; dates that parse to year 112 or similarly nonsensical values.

### Pitfall 4: Stale row-count and code-list assumptions from CONTEXT.md
**What goes wrong:** Planning tasks/time estimates around "~4700" and "~38000" row counts, or assuming `01015C` is a valid, present acceptance-test code.
**Why it happens:** CONTEXT.md's estimates were apparently derived from `wc -l` (line count) rather than actual CSV row parsing — quoted multi-line fields in the drug CSV (e.g., inside `AI-note`) inflate raw line counts well beyond actual data row counts.
**How to avoid:** Use the verified counts in this document (2,669 payment rows, 11,273 drug rows) for planning; use `csv.DictReader` (or pandas `read_csv`) row counts, never `wc -l`, for any future large multi-line-field CSV in this project. Replace `01015C` in the 20-code acceptance list with a verified-present code (see Open Questions for candidates).
**Warning signs:** None directly observable at runtime — this is a planning-input accuracy issue, not a code bug.

### Pitfall 5: llama.cpp server behavior needs live verification before the build script depends on it
**What goes wrong:** During this research, a test JSON-mode chat completion request to the live, healthy llama.cpp server (`Ornith-1.0-9B`, confirmed running via `/health` → `{"status":"ok"}`) returned what appears to be an OpenAPI-schema-shaped response (field names replaced with type descriptors like `"content": string`) rather than actual generated content. This could be a symptom of the specific request payload used in this quick test (e.g., missing a required chat template field) rather than a genuine server defect, but it was not resolved within this research session.
**Why it happens:** Unconfirmed — could be a request-formatting issue (this research's test request), a jinja/chat-template misconfiguration on the server, or a llama.cpp build quirk with the loaded GGUF's chat template.
**How to avoid:** Before writing the rule_mapping LLM-build script, the plan MUST include an explicit early verification task: send a real, correctly-formatted chat completion request to `http://localhost:8080/v1/chat/completions` (matching whatever client library — e.g., `openai` Python client pointed at the local base_url, or raw `requests` — the executor intends to use) and confirm it returns actual generated text before building the batch mapping logic around it.
**Warning signs:** Any rule_mapping build script silently writing schema-descriptor strings (like the literal text `"string"` or `"int"`) into the SQLite cache instead of real 條文全文 — this would be a severe, hard-to-detect data quality issue if not caught by the 20-code human spot-check.

### Pitfall 6: Legacy `.doc` files silently excluded from PageIndex coverage
**What goes wrong:** A docx-only glob pattern (`*.docx`) run over `officialdocument/審查注意事項/` will silently miss 11 `.doc` files (e.g., `1第一部總則-113.05.01.doc`, `3第三部牙醫-113.12.01.doc`, `5第五部居家照護-113.09.01.doc`), causing REQ-rule-repository's "涵蓋全部 .doc/.docx 文件" acceptance criterion to fail even though the code runs without errors.
**Why it happens:** `.doc` and `.docx` look similar but are structurally incompatible formats (`.doc` is the old OLE2/binary format; `.docx` is Open XML/zip-based). `python-docx` only supports `.docx`. It is easy to write a build script that globs `*.docx` and never notices the `.doc` files exist.
**How to avoid:** Wave 0 preprocessing step: glob both `*.doc` and `*.docx`, convert all `.doc` files via `soffice --headless --convert-to docx --outdir <staging_dir> <file>` (LibreOffice confirmed installed, v24.2.7.2), then run the tree extractor over the full combined + converted set. Add a coverage assertion test (file count in source dir == file count processed in tree build) to catch silent omissions.
**Warning signs:** Tree-build file-count logs showing 23 processed when 34 total source files (23 .docx + 11 .doc) exist in the directory.

## Code Examples

### Verified: Reading both CSVs correctly (encoding + core columns per D-01/D-02)
```python
# Source: verified directly against the actual repo files during this research
import csv

PAYMENT_CSV = "officialdocument/審查注意事項/醫療服務給付項目251027準確板_已優化填入支付規定.csv"
DRUG_CSV = "officialdocument/審查注意事項/藥品項查詢項目檔260605 AI  摘要支付價大於0.csv"  # NOTE: double space before "摘要" — verify exact filename via glob, don't hardcode

with open(PAYMENT_CSV, encoding="utf-8-sig") as f:  # utf-8-sig strips the BOM
    reader = csv.DictReader(f)
    # header: 診療項目代碼, 健保支付點數, 生效起日, 生效迄日, 英文項目名稱, 中文項目名稱, 支付規定
    # core cols per D-01/D-02: 診療項目代碼(PK), 中文項目名稱, 支付規定, 生效起日, 生效迄日
    rows = list(reader)  # 2,669 rows verified

with open(DRUG_CSV, encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    # header (22 cols): 異動, 藥品代號, 藥品英文名稱, 藥品中文名稱, 成分, 規格量, 規格單位,
    #   單複方, 支付價, 有效起日, 有效迄日, 藥商, 製造廠名稱, 劑型, 藥品分類, 分類分組名稱,
    #   ATC代碼, 給付規定章節, 藥品代碼超連結, 給付規定章節連結, 給付規定, AI-note
    # core cols per D-01/D-02: 藥品代號(PK), 藥品中文名稱, 給付規定, 有效起日, 有效迄日
    rows = list(reader)  # 11,273 rows verified, all 藥品代號 values unique (0 duplicates)
```

### Verified: 民國 date parsing helper (handles both formats found in the two CSVs)
```python
# Both formats verified present in this repo's actual CSVs during this research
def parse_flexible_date(raw: str) -> str | None:
    """Handles both '20160401' (Gregorian YYYYMMDD, seen in payment CSV)
    and '1121001' (ROC YYYMMDD, seen in drug CSV). Returns ISO 'YYYY-MM-DD' or None."""
    raw = raw.strip()
    if not raw or raw in ("null", "0", "99991231"[:len(raw)]):  # watch for sentinel "far future" dates too
        return None
    if len(raw) == 8:  # Gregorian YYYYMMDD
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    if len(raw) == 7:  # ROC YYYMMDD
        roc_year = int(raw[0:3])
        return f"{roc_year + 1911}-{raw[3:5]}-{raw[5:7]}"
    return None  # unrecognized format — log and investigate, don't silently swallow
```

### Verified: table-aware docx traversal for the 附表 document
```python
# Source: Context7 python-docx docs, verified against installed docx 1.2.0
# against 西醫基層醫療費用審查注意事項-附表.docx (151 paragraphs, 27 tables interleaved)
import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

def extract_ordered_blocks(path: str):
    d = docx.Document(path)
    blocks = []
    for block in d.iter_inner_content():
        if isinstance(block, Paragraph):
            if block.text.strip():
                blocks.append({"type": "paragraph", "style": block.style.name, "text": block.text})
        elif isinstance(block, Table):
            rows = [[cell.text for cell in row.cells] for row in block.rows]
            blocks.append({"type": "table", "rows": rows})
    return blocks
```

### Verified: LibreOffice headless `.doc` → `.docx` conversion
```bash
# Source: verified directly on this machine — soffice v24.2.7.2 confirmed installed
soffice --headless --convert-to docx --outdir /path/to/staging_dir "/path/to/source.doc"
# Batch form (run once per file, or loop in a shell/python subprocess wrapper):
for f in officialdocument/審查注意事項/*.doc; do
    soffice --headless --convert-to docx --outdir data/converted_docx/ "$f"
done
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Assume `pageindex` PyPI package = VectifyAI's open-source local tree indexer | `pageindex` PyPI package (0.2.8) is a cloud SaaS SDK; the actual open-source project must be self-hosted separately from its GitHub repo and only accepts PDF/Markdown | Discovered during this research session (2026-07-30) by reading the installed package source directly | Phase 2 must NOT rely on `pip install pageindex` for local functionality — build a custom extractor instead |
| Manual `iter_block_items()` XML-level recipe for docx paragraph+table ordering | `document.iter_inner_content()` built-in method | Available in python-docx ≥ some 1.x version, confirmed present and working in the installed 1.2.0 | Simpler code, no need to touch low-level `CT_P`/`CT_Tbl` OXML types |

**Deprecated/outdated:** N/A — no formal deprecations found; this is a first-time build, not a migration.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The apparent "schema-echo" response from the live llama.cpp server test was likely a request-formatting artifact of this research's quick test, not a genuine server misconfiguration | Common Pitfalls #5 | If the server genuinely cannot produce real completions in its current launch configuration, the entire LLM-assisted rule_mapping build step (D-04) is blocked until the server/request format is fixed — this must be verified early in Phase 2 execution, not assumed fixed |
| A2 | ChromaDB's default embedding function will download its ~200MB ONNX model successfully in this environment (assumes outbound network access is available for this one-time download, even though the project's runtime philosophy is "offline") | Standard Stack / Supporting | If the machine has no internet access at all (fully air-gapped), the first ChromaDB embed call will hang/fail; D-09 is already flagged as low-priority/non-blocking, so this should not block core acceptance, but the planner should note it as a setup prerequisite (one-time online step) rather than assume it "just works" identically to the fully-offline query-time guarantee |
| A3 | The double-space filename (`藥品項查詢項目檔260605 AI  摘要支付價大於0.csv`) is stable and not a filesystem quirk that will change if the file is ever re-copied/re-exported | Code Examples | If the filename is later "cleaned" to single-space, hardcoded path references would break; recommend the loader resolve the file via `glob` pattern matching (`藥品項查詢項目檔*.csv`) rather than an exact hardcoded filename |
| A4 | LibreOffice's `.doc`→`.docx` conversion will preserve enough structural fidelity (styles, tables) for the regex-based hierarchy parser to work on converted files the same way it does on native `.docx` files | Common Pitfalls #6 | If conversion degrades structure significantly (e.g., flattens all styles to Normal, or garbles Traditional Chinese text), the tree quality for those 11 files could be worse than for native .docx — recommend spot-checking at least 2-3 converted files' extracted text against the original before trusting the full batch |

## Open Questions

1. **What should replace `01015C` in the 20-code acceptance list?**
   - What we know: `01015C` does not exist in the payment CSV (verified). `64140C` does exist and has rich markdown-style 條文全文 already embedded in `支付規定`. CONTEXT.md's draft candidates (06012C, 06013C, 05316C) were all verified present.
   - What's unclear: Whether `01015C` was meant to be a drug code (checked: also absent from drug CSV's `藥品代號` column based on the code pattern, drug codes use a different alphanumeric format like `AC10398100`) or simply a typo/outdated reference from the original progress.md ADR.
   - Recommendation: Planner/user should finalize the 20-code list using only verified-present codes; treat `01015C` as a dropped/replaced reference, not something to chase down further, since constraints.md C6 only uses it as an illustrative example ("如01015C、64140C"), not a hard requirement that this exact code exists.

2. **Is the llama.cpp server's chat-completion behavior actually correct for JSON-mode prompts?**
   - What we know: The server is running and its `/health` and `/props` endpoints respond normally with real data (model name, sampler params, etc.).
   - What's unclear: A quick JSON-mode chat completion test during this research returned what looked like an OpenAPI schema template rather than generated text — cause not isolated (could be request-shape issue in this ad-hoc test, not a real defect).
   - Recommendation: First task of the rule_mapping build step should be a smoke test — send a minimal, correctly-formatted request (ideally using the same HTTP client code path the actual build script will use) and manually inspect the raw response before writing any batch logic that assumes well-formed completions.

3. **What is the actual node granularity needed for rule_mapping to satisfy "抽 20 個常見醫令...人工核對命中率"?**
   - What we know: rule_mapping must map (醫令代碼, 科別, 文件版本) → (條文位置, 條文全文). The payment CSV's `支付規定` column for many rows (1,316 of 2,669, i.e., ~49%) already contains rich, code-specific markdown-formatted review-guideline text (e.g., 64140C's cell literally contains "審查原則：(2024-10-23) 版本 1.0 1. **申報條件**...").
   - What's unclear: Whether this pre-embedded `支付規定` text is meant to BE the "條文全文" already (in which case for those ~1,316 rows, rule_mapping construction may be nearly trivial — just point back to the CSV cell, no docx tree lookup needed), or whether rule_mapping is strictly meant to reference the SEPARATE 審查注意事項 docx corpus's article text, treating the CSV's `支付規定` as a different, complementary source.
   - Recommendation: Planner should treat this as a scoping decision to surface explicitly in the plan: likely the cleanest design is "if `支付規定`/`給付規定` cell already contains substantive non-null review-guideline text, that itself can serve as one valid 條文全文 candidate in rule_mapping (source-tagged as 'CSV' rather than 'docx'), reducing how many codes strictly require docx-tree LLM matching." This significantly de-risks D-04/D-05 for at least half the payment codes.

4. **Do the 11 legacy `.doc` files need to go through the same rule_mapping build step, or only the SQLite/tree-coverage acceptance criteria?**
   - What we know: REQ-rule-repository's acceptance criterion (2) explicitly requires PageIndex tree coverage of "全部 .doc/.docx 文件" — this must include the 11 `.doc` files after conversion.
   - What's unclear: Whether the 20-code rule_mapping spot-check (acceptance criterion 3) needs codes that map into these `.doc`-originated documents specifically, or whether the existing candidate list (drawn mostly from specialty docx files) is sufficient.
   - Recommendation: Ensure tree-building coverage includes converted `.doc` files (hard requirement), but the 20-code spot-check list does not need forced representation from every single source file — natural candidate selection from CONTEXT.md's principle (non-null, substantive 支付規定/給付規定 text) should suffice.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| python-docx | docx tree extraction | ✓ | 1.2.0 | — |
| pandas | CSV loading, SQLite batch insert | ✓ | 2.2.3 | — |
| sqlite3 (stdlib) | payment_rules/drug_rules/rule_mapping storage | ✓ | 3.45.1 (incl. FTS5) | — |
| chromadb | D-09 embedding storage (non-blocking) | ✓ | 1.5.9 | Skip D-09 entirely if time-constrained (explicitly permitted by CONTEXT.md) |
| requests | HTTP calls to llama.cpp for rule_mapping build | ✓ | installed | — |
| llama.cpp server (localhost:8080) | D-04 LLM-assisted rule_mapping build | ✓ (running, healthy) | Ornith-1.0-9B Q6_K_XL, n_ctx 32768 | See Open Question #2 — verify actual completion quality before depending on it |
| `pageindex` PyPI package | — (NOT recommended for use) | ✓ installed but unusable offline | 0.2.8 | Custom python-docx-based extractor (this document's primary recommendation) |
| LibreOffice (`soffice`) | `.doc` → `.docx` conversion for 11 legacy files | ✓ | 24.2.7.2 | — |
| Outbound internet (one-time) | ChromaDB default embedder's first-use model download (~200MB) | Unverified in this session | — | If unavailable: pre-stage the ONNX model file manually, or defer D-09 entirely (already low-priority) |

**Missing dependencies with no fallback:** None — all core dependencies for the 3 REQ-rule-repository acceptance criteria (SQLite queryable, docx tree coverage, rule_mapping spot-check) are present and verified working, including the newly-discovered `.doc` conversion requirement (LibreOffice already installed).

**Missing dependencies with fallback:** `pageindex` PyPI package is present but should not be used; ChromaDB's one-time model download depends on unverified internet access at build time (D-09 is non-blocking so this has an easy fallback: skip/defer).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (established in Phase 1, `[dependency-groups] dev = ["pytest>=8.0"]`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` `testpaths = ["tests"]` (from Phase 1) |
| Quick run command | `uv run pytest tests/test_rule_repository*.py -x` |
| Full suite command | `uv run pytest tests/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REQ-rule-repository (SQLite queryable) | `payment_rules`/`drug_rules` return correct row for known code (e.g., 64140C, 06012C) | unit | `uv run pytest tests/test_rule_repository_sqlite.py -x` | ❌ Wave 0 |
| REQ-rule-repository (docx tree coverage, incl. converted .doc files) | Tree build process runs over all 34 (23 docx + 11 doc→docx converted) files without silently skipping any (assert file count processed == file count found) | integration | `uv run pytest tests/test_docx_tree_coverage.py -x` | ❌ Wave 0 |
| REQ-rule-repository (rule_mapping hit-rate) | 20-code human-verified spot-check list, each with expected 條文位置/全文 substring, checked against actual rule_mapping table contents | manual-assisted (semi-automated: script prints candidate + human confirms once, then locks as regression fixture) | `uv run pytest tests/test_rule_mapping_spotcheck.py -x` (asserts against a human-curated fixture file, not live LLM output) | ❌ Wave 0 |
| D-07/D-08 (single query function) | `get_rule("64140C")` returns a dataclass with all expected fields populated; unknown code returns a "not found" state, not an exception | unit | `uv run pytest tests/test_rule_repository_interface.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_rule_repository*.py -x` (fast, SQLite-only tests)
- **Per wave merge:** `uv run pytest tests/ -v` (full suite including docx tree + mapping spot-check)
- **Phase gate:** Full suite green + manual 20-code spot-check sign-off before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_rule_repository_sqlite.py` — covers payment_rules/drug_rules queryability
- [ ] `tests/test_docx_tree_coverage.py` — covers full-corpus docx tree coverage (23 .docx + 11 .doc→.docx converted)
- [ ] `tests/test_rule_mapping_spotcheck.py` — covers 20-code hit-rate acceptance (needs a human-curated fixture file created alongside the plan, e.g., `tests/fixtures/rule_mapping_20_spotcheck.json`)
- [ ] `tests/test_rule_repository_interface.py` — covers D-07/D-08 single-entry-point contract
- [ ] `tests/conftest.py` fixtures for a temp/test SQLite DB path (avoid polluting `data/db/` during test runs) — extend Phase 1's existing `tests/conftest.py` pattern

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No auth surface in this phase (offline batch/library code, no network-facing service) |
| V3 Session Management | No | N/A |
| V4 Access Control | No | Single-machine, single-user local tool per D2 |
| V5 Input Validation | Yes | CSV/docx parsing must handle malformed/unexpected rows defensively (e.g., unrecognized date formats logged not silently coerced — see Pitfall 3); SQL queries must use parameterized queries (`?` placeholders), never string-formatted SQL, even though input is currently trusted local file data (defense in depth against future input sources) |
| V6 Cryptography | No | No secrets/crypto in this phase; llama.cpp connection is plain HTTP to localhost, consistent with Phase 1's existing `llama_config.json` pattern |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via string-formatted queries in rule_repository lookups | Tampering | Always use parameterized queries: `cursor.execute("SELECT * FROM payment_rules WHERE code = ?", (code,))`, never f-string/`.format()` SQL construction |
| Accidental data exfiltration via the `pageindex` cloud SDK | Information Disclosure | Do not import/call the installed `pageindex` package (see Critical Finding); code review should explicitly check for any `api.pageindex.ai` or `PageIndexClient` usage in Phase 2 diffs |
| ChromaDB first-use model download reaching out to external hosts unexpectededly | Information Disclosure (minor — only fetches a public model, does not send project data) | Acceptable given D-09 is a local, one-time model fetch (standard practice for offline-embedding libraries); if the deployment target is truly air-gapped, pre-stage the ONNX model file instead of relying on first-use auto-download |

## Sources

### Primary (HIGH confidence)
- `/home/hsu/Desktop/Elcinsurrence/.venv/lib/python3.12/site-packages/pageindex/client.py` — read directly, confirms cloud-only SDK behavior
- `/home/hsu/Desktop/Elcinsurrence/.venv/lib/python3.12/site-packages/pageindex-0.2.8.dist-info/METADATA` — confirms `openai` dependency
- Context7 `/websites/python-docx_readthedocs_io_en` — `iter_inner_content()`, `BlockItemContainer` API docs
- Direct inspection of all relevant source files in this repo: both CSVs (headers, row counts, sample rows, date formats), all style profiles of the 21 specialty docx + 附表 + 2-2-7 surgery doc, the full directory listing revealing 11 legacy `.doc` files, live `curl` tests against the running llama.cpp server (`/health`, `/props`, `/v1/embeddings`, `/v1/chat/completions`), local `sqlite3`/`pandas`/`chromadb`/`python-docx`/`soffice` version checks

### Secondary (MEDIUM confidence)
- WebSearch: "PageIndex vectifyai GitHub open source tree index document local self-hosted" — cross-referenced across GitHub repo listing, buildfastwithai.com blog, zread.ai overview; consistent story across sources (open-source repo exists, is MIT-licensed, PDF/Markdown-only)
- WebFetch of `raw.githubusercontent.com/VectifyAI/PageIndex/main/README.md` and `github.com/VectifyAI/PageIndex` — confirms PDF/Markdown-only input, `gpt-4o` default model via LiteLLM, `.env`-based API key requirement, no explicit local-endpoint config documented
- WebSearch: ChromaDB default embedding function behavior — cross-referenced GitHub issue #2910, c-sharpcorner.com article, official Chroma docs; consistent on "~200MB ONNX all-MiniLM-L6-v2, downloaded on first use, cached thereafter"

### Tertiary (LOW confidence)
- None flagged as tertiary-only; the one item that would otherwise be LOW confidence (llama.cpp JSON-mode response oddity) is documented as a live-observed anomaly with an explicit recommendation to re-verify, not asserted as fact

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all core libraries verified installed and version-checked directly in this repo's `.venv`, and LibreOffice's presence verified directly on the system
- Architecture: MEDIUM — docx structure patterns verified directly against real files, but the regex hierarchy patterns list (Pattern 2) may need refinement once the executor processes all files, not just the samples inspected here (內科, 兒科, 外科, 婦產科, 家庭醫學科, 復健科, 放射線科, 泌尿科, 病理科, 皮膚科, 眼科, 神經外科, 精神科, 耳鼻喉科, 骨科, 麻醉科, 附表, 2-2-7, 中醫, 牙醫, 一般原則 were all directly sampled as native .docx; the 11 legacy `.doc` files — `1第一部總則`, `2-2-1`, `2-2-3`, `2-2-5`, `2-2-9`, `3第三部牙醫`, `5第五部居家照護`, `6-1`, `6-2`, `7-1`, `7-2` — were NOT sampled post-conversion since conversion has not yet been performed; their post-conversion style/structure profile is unverified (see Assumption A4))
- Pitfalls: HIGH — all pitfalls documented are directly observed in this session, not speculative

**Research date:** 2026-07-30
**Valid until:** 30 days (stable local-file-based domain; the one fast-moving risk is llama.cpp server behavior/config which should be re-verified at execution time regardless of this date)
