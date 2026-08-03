---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-08-03T00:00:00.000Z"
progress:
  total_phases: 9
  completed_phases: 6
  total_plans: 11
  completed_plans: 10
  percent: 91
---

# STATE.md — elc-audit-engine

## Bootstrap Status

Net-new project bootstrap from document ingest (`gsd-ingest-docs` → `gsd-doc-synthesizer`). This is the first `.planning/` synthesis; no prior ROADMAP/PROJECT/REQUIREMENTS existed before this run.

## Current Phase

ROADMAP.md was remapped to GSD's per-phase structure: progress.md's M1-M8 (originally sub-milestones inside one "Phase 1 — 獨立引擎") are now GSD Phase 1-8, one GSD phase each. progress.md's "Phase 2" (HIS integration) is now GSD Phase 9 (placeholder).

**GSD Phase 1 — 專案骨架 (Project Skeleton) — COMPLETE (2026-07-29)**
**GSD Phase 2 — 規則庫建置 (Rule Repository) — COMPLETE (2026-07-31)** — all 6 plans done, REQ-rule-repository's 3 acceptance criteria automated-and-passing, 20-code human spot-check confirmed 20/20 correct.
**GSD Phase 3 — 解析器 (Parsers) — COMPLETE (2026-08-03)** — 03-01 單輪交付三個解析器：申報 XML（Big5 編碼偵測＋三種致命缺漏分級＋raw 全保留＋次診斷清單，真實檔回放 633 案／2,624 醫令／0 拒收）、核減明細（D-14d 18 欄、欄 17 代碼拆分、reader 參數化）、SOAP（marker/keyword 兩層＋信度、317 關鍵詞移植、無命中歸 UNKNOWN）。46 新測試全綠。
**GSD Phase 4 — 病歷彙整器 (Record Aggregator) — COMPLETE (2026-08-03)** — 04-01 單輪交付：RecordProvider ABC（雲端/本地可互換）＋LocalFileProvider（records.json 契約）＋build_timeline（半年時間窗過濾＋排序＋excluded 統計）；病歷缺席降級（C5）、JSON 損毀拋 RecordProviderError（P0-2 教訓）。14 新測試全綠。
**GSD Phase 5 — 三方比對器 (Three-way Comparator) — COMPLETE (2026-08-03)** — 05-01 單輪交付：檢核項＝規則全文＋出處；證據組裝 SOAP＋半年病史（含截斷）；LLMJudger（JSON 強制＋重試一次＋失敗降級待人工）；classify_support 三級純函式；LLMNarrativeGenerator（C2：1~3 條附出處、prompt_only 提示型）；RuleRepositoryError 穿透、found=False 標未知醫令；病歷缺席 records_degraded。29 新測試全綠。
**GSD Phase 6 — 輸出一（病歷補強報告）— COMPLETE (2026-08-03)** — 06-01 單輪交付：render_report（Markdown checkbox 逐條審：標題/警告區/支持度徽章/候選補強/半年病史摘要）＋render_tracking（審核軌跡 JSON：D9 四狀態＋原文＋編輯後文＋時間）＋write_report（.md＋.json 薄包裝）。13 新測試全綠，全套件 152 passed / 5 skipped。
**GSD Phase 7 — 輸出二（申復理由草稿）— COMPLETE (2026-08-03)** — 07-01 單輪交付：build_appeal_draft（D10 四段組裝：①案情摘要/②醫療必要性/③規則依據/④病歷佐證；每筆核減醫令獨立生成）＋字數控制器（官方問答集 Q15：每欄 1000／合計 2000、裁剪優先 ④→②、①③骨架不動）＋P6 不申覆強制填 0 硬檢查（C3/Q13）＋D-15 核減上界檢查（申復點數≤不予核銷金額）＋adopted_narratives_from_tracking（審核軌跡消費，D-08）＋render_appeal_markdown/render_appeal_json/write_appeal（C7：申復草稿_{流水號}.md＋appeal_{流水號}.json，含 p1-p9 醫令段欄位）。24 新測試全綠，全套件 176 passed / 5 skipped。
**GSD Phase 8 — 端到端測試 — COMPLETE (2026-08-03)** — 08-01 單輪交付：LLM 判定金標準 30 組（tests/fixtures/llm_gold_standard_30.json：支持12/部分支持9/無記載9＋eval/gold_standard.py harness＋scripts/replay_gold_standard.py 真實 LLM 回放 CLI，health guard，C6-3）＋端到端 3 案例（充分/薄弱/裸奔，run_case_pipeline：compare→write_report→審核 decisions→build_appeal→write_appeal，C6-4）＋E2E-01 修正（classify_support 任一『部分支持』→ 薄弱，原歸充分使 D7 三級缺一角）＋真實樣本替換介面（注入層可換，C6-5）。21 新測試全綠，全套件 197 passed / 5 skipped。五層測試策略全數涵蓋並可執行（C6）。
**Next: Phase 7 — 輸出二（申復理由草稿）— 依賴 Phase 5（已完成）。**

**Phase 3 context highlights (see `.planning/phases/03-parsers/03-CONTEXT.md`):** 使用者提供真實申報 XML `TOTFA.xml`（633 案 / 2,624 醫令 / Big5 / 348 位病患，已 gitignore）。實測推翻三項文件假設：(1) C11 欄位表為精選子集，真實檔多出 18 個 dbody 欄位，其中 `d20`-`d26` 為次診斷代碼（Phase 5 判斷醫療必要性的關鍵）；(2) C8 的 p8/p9 字數上限描述有誤，官方問答集 Q15 確認為**每欄 1000 中文字／合計 2000**——影響 Phase 7 字數控制器；(3) **`電子申復格式及填表說明門診.doc` 是申復「輸出」規格，不是核減「輸入」格式**（原 D-14 據此建模輸入檔屬誤判，已由 D-14a 修正）。

**核減輸入格式已釐清（D-14c/D-14d）：** 使用者提供 VPN 下載畫面實況與官方欄位範例——抽樣樣本檔為 **CSV**（兩種院所型態都拿得到）；**申復明細資料檔 18 欄欄位順序已確定**（日期為西元非民國、金額有零填補與純數字兩種格式、身分證號已遮罩但出生日期未遮罩、第 17 欄為 `代碼-說明` 複合欄即核減代碼表線索、欄 5/6/10/11 為與申報 XML 的完整 join key）。**故核減解析器已納入 Phase 3 實作範圍（D-14b-rev），ROADMAP Phase 3 的 Goal 與三項成功條件維持原樣不需修改。** 仍待補：實體檔案（分隔符／表頭／編碼／檔名規則），故 reader 層須參數化。

## Completed Work

- Design phase complete (progress.md §3, §4; docs/plans/2026-07-29-elc-audit-engine-design.md full design doc) — 12 locked architectural decisions, system architecture diagram, rule-repository layering, Phase 1/Phase 2 roadmap all finalized prior to this ingest.
- Document ingest + synthesis complete: 3 source docs (1 ADR, 1 SPEC, 1 DOC) classified and merged into `.planning/intel/`.
- **GSD Phase 1 (專案骨架) planned, verified (2 rounds, 0 blockers/warnings on final pass), executed, and merged to main.** Delivered: uv-managed Python 3.12 project (`pyproject.toml`, `uv.lock`), `config/settings.py` env-var-overridable settings module mirroring DrtoolboxLocalServer conventions, `config/llama_config.json` with D2-locked values (Ornith-1.0-9B, n_ctx 32768, localhost:8080), `src/elc_audit_engine/` package with 5 empty subsystem stub sub-packages (`parsers`, `rule_repository`, `record_aggregator`, `comparator`, `generators` — one per future GSD phase), `data/{db,rag,output}/` directory structure, and a 4-test config test suite (all passing). See `.planning/phases/01-project-skeleton/01-01-SUMMARY.md`.
- **GSD Phase 2 Plan 01 (Wave 0: rule repository scaffolding) executed and committed.** Delivered: `RuleResult` frozen dataclass (D-07/D-08 query-result contract) with `not_found()` factory in `src/elc_audit_engine/rule_repository/models.py` (3/3 tests green); finalized 20-code human spot-check fixture (`tests/fixtures/rule_mapping_20_spotcheck.json`, `01015C` replaced with 20 CSV-verified-present codes); 4 intentionally-red Wave-0 test files (`test_rule_repository_sqlite.py`, `test_docx_tree_coverage.py`, `test_rule_mapping_spotcheck.py`, `test_rule_repository_interface.py`) for Plans 02/03/05 to satisfy; `tests/conftest.py` extended with `tmp_rule_db_path` fixture. See `.planning/phases/02-rule-repository/02-01-SUMMARY.md`.
- **GSD Phase 2 Plan 02 (Wave 1: SQLite structured-rule layer) executed and committed.** Delivered: `parse_flexible_date()` (`loaders/dates.py`) disambiguating 8-digit Gregorian vs 7-digit ROC dates by string length; `db.py` schema (`payment_rules`/`drug_rules`) + parameterized `query_by_code()` with table-name allowlist; `payment_loader.py`/`drug_loader.py` CSV-to-SQLite loaders (2,669 + 11,273 rows, exact expected counts); `scripts/build_sqlite.py` one-shot entrypoint, actually run to populate the real `data/db/rules.sqlite3`. `tests/test_rule_repository_sqlite.py` (Plan 01's red scaffold) now 4/4 green. See `.planning/phases/02-rule-repository/02-02-SUMMARY.md`.
- **GSD Phase 2 Plan 03 (Wave 1: custom docx-tree indexer) executed and committed.** Delivered: `src/elc_audit_engine/rule_repository/docx_tree/` package (`doc_converter.py` — LibreOffice headless `.doc`→`.docx` batch conversion; `patterns.py` — 8-depth Traditional Chinese regex hierarchy detection, confirmed working as primary mechanism against 100%-Normal-style source docs; `extractor.py` — `iter_inner_content()`-based ordered paragraph/table extraction + depth-stack tree builder; `tree_builder.py` — full 32-file orchestration with internal coverage assertion) and `scripts/build_docx_trees.py` (one-shot entrypoint). Real artifact produced: `data/db/docx_trees.json` (32 files, 1633 tree nodes, gitignored build output). `tests/test_docx_tree_coverage.py` now green (was red since Plan 01); fixed a dict-iteration bug in that test file along the way. Confirmed via grep: zero `pageindex` PyPI import anywhere (explicitly NOT used — it's a cloud SaaS client, violates D2 offline-only). See `.planning/phases/02-rule-repository/02-03-SUMMARY.md`.
- **GSD Phase 2 Plan 06 (Wave 2: ChromaDB D-09 embeddings, non-blocking) executed and committed.** Delivered: `src/elc_audit_engine/rule_repository/embeddings/` package (`chroma_store.py` — `flatten_tree_nodes()` + `build_chroma_collection()`, wrapped in a broad non-blocking exception handler per D-09) and `scripts/build_chroma_index.py`. Real artifact produced: local persistent ChromaDB collection at `data/rag/` (165 chunks ingested from the 32-file docx tree corpus, default ONNX all-MiniLM-L6-v2 embedder). Low-priority/non-blocking infrastructure only — no query logic (deferred to Phase 5 per CONTEXT.md). See `.planning/phases/02-rule-repository/02-06-SUMMARY.md`.
- **GSD Phase 2 Plan 04 (Wave 2: rule_mapping LLM-assisted build, D-04/D-05) executed and committed.** Delivered: `src/elc_audit_engine/rule_repository/mapping/` package (`llm_client.py` — llama.cpp chat_completion wrapper with mandatory smoke test; `prompts.py` — keyword-prefiltered candidate-matching prompts; `build_mapping.py` — CSV-reuse fast path + LLM-assisted fallback batch orchestrator) and `db.py` extended with the `rule_mapping` table schema. Real batch run completed for all 13,942 codes (2,669 payment + 11,273 drug): `{'csv_reuse_count': 6802, 'llm_matched_count': 558, 'no_match_count': 6582}` — the run took ~9.3h wall-clock (mostly LLM inference for the LLM-path codes) and survived an account spend-limit session interruption thanks to a periodic-commit resilience fix (every 100 rows) added during implementation. All 20 human spot-check fixture codes resolved via the CSV fast path with real, substantive article text. Discovered and fixed during batch testing: `chat_template_kwargs.enable_thinking=false` cuts the loaded model's per-call latency from ~30s to ~0.6s (default reasoning-trace mode was otherwise making the batch infeasible). The 46% LLM-path no-match rate is documented as an honest recall limitation of top-5 keyword prefiltering, not a bug — manually verified the LLM correctly declines to fabricate matches when no relevant candidate is found. See `.planning/phases/02-rule-repository/02-04-SUMMARY.md`.
- **GSD Phase 2 Plan 05 (Wave 3: get_rule() single query interface + human spot-check) executed and committed — Phase 2 now COMPLETE.** Delivered: `get_rule(code)` in `src/elc_audit_engine/rule_repository/__init__.py`, the sole D-07/D-08 public entry point — combines `payment_rules`/`drug_rules` + `rule_mapping` lookups, zero LLM/network calls at query time, never raises (SQLite errors degrade to `not_found()`). Fixed a cross-plan integration gap: `rule_mapping` was missing from `db.py`'s `query_by_code` allowlist. Human 20-code spot-check conducted via a published Artifact review page (Traditional Chinese regulatory text, per user request over raw terminal output) — user confirmed **20/20 correct**. `tests/fixtures/rule_mapping_20_spotcheck.json` locked with real article data, `verified: true` for all entries. Full test suite green: 34 passed, 1 skipped. All 3 REQ-rule-repository acceptance criteria now automated-and-passing. See `.planning/phases/02-rule-repository/02-05-SUMMARY.md`.

## Not Yet Started

- Phase 3 (解析器) through Phase 9 (HIS 整合佔位) — see ROADMAP.md for full breakdown. Phase 3 (parsers) and Phase 4 (record aggregator) both depend only on Phase 1 (satisfied) and could be planned in either order or in parallel.

## Blockers

None. Conflict detection found zero BLOCKER-severity issues and zero competing-variant issues. See `.planning/INGEST-CONFLICTS.md`.

## Session Continuity

Last session: 2026-08-03（Phase 8 執行完成）
Stopped at: **Phase 8 COMPLETE** — 08-01-PLAN 產出並執行（金標準 30 組＋端到端 3 案例＋E2E-01 修正），全套件 197 passed / 5 skipped。Phase 8 的四項成功條件全部達成並自動化驗證（見 ROADMAP.md；C6 五層全數涵蓋）。
Next action: `/gsd-plan-phase 9`（doctor-toolbox HIS 整合佔位；依賴 Phase 8 已完成 — 屬 Phase 2 原設計文件命名）
Resume file: `.planning/phases/06-output-reinforcement-report/06-01-SUMMARY.md`（交付摘要）＋ `.planning/HANDOFF.json`（結構化）

**Carry into planning:**
- **E2E-01 已修正**：classify_support「部分支持（無無記載）」由充分改為薄弱（05-CONTEXT D-04 已同步加註記）；薄弱三級在單檢核項流程下已可達。
- **run_case_pipeline 是 Phase 9/真實樣本回放的接入點**：換真解析器/Provider/rule_lookup/judge_fn 即可回放真實核減案（C6-5）；appeal 階段單筆規則庫故障降級查無規則不阻斷（C5 精神），比對階段故障依 P0-2 穿透。
- **金標準回放**：`scripts/replay_gold_standard.py` 需 llama.cpp :8080 健康（換模型回歸基準，C6-3）；測試零 LLM 依賴（替身 judge_fn）。
- **Phase 7 字數上限已定案**：以官方問答集 Q15 為準（p8/p9 各 1000 中文字、合計放寬至 2000），取代 C8 舊「2000/欄」；A001 虛擬醫令綜整（官方註 5）屬申復 XML 上傳層（Phase 2）選項，Phase 7 未實作。
- **appeal JSON 為 Phase 2 轉 XML 的契約**：`appeal_{流水號}.json` 含 p1-p9 醫令段欄位（p3 改支序號/p4 成數/p5 數量 目前為 null，待真實改支檔與院所填報）；t38/t39 總計、A001 綜整、XML 序列化 → Phase 2。
- **核減解析器已納入 Phase 3 範圍**（D-14b-rev）——欄位表見 D-14d。⚠️ **不要**採用已作廢的 D-14／D-14b（保留刪除線供追溯）。
- **核減欄位只認 D-14d**：`officialdocument/電子申復文件格式/` 底下所有規格書都是申復**輸出**格式（Phase 7），不得用來建模輸入檔。
- **reader 層須參數化**（分隔符／表頭／編碼），實體檔到手只調參數、不動欄位映射。
- fixture 去識別化範圍為使用者知情後的明示決定（**只洗 `d49` 姓名**），下游不得自行擴大。
- **`get_rule()` 已改為會拋 `RuleRepositoryError`**（P0-2 breaking change）——Phase 3 解析器不呼叫它，但 Phase 5 比對器必須處理此例外。

## Key References

- `.planning/PROJECT.md` — project overview, locked architecture, source doc precedence
- `.planning/REQUIREMENTS.md` — 9 requirements (8 Phase 1 + 1 Phase 2 placeholder)
- `.planning/ROADMAP.md` — M1-M8 Phase 1 breakdown + Phase 2 placeholder
- `.planning/INGEST-CONFLICTS.md` — conflict detection report (0 blockers, 0 variants, 5 auto-resolved/info)
- `.planning/intel/decisions.md` — full ADR decision detail (D1-D12)
- `.planning/intel/requirements.md` — requirement source detail
- `.planning/intel/constraints.md` — SPEC/DOC technical constraints (C1-C12)
- `.planning/intel/context.md` — DOC background/context notes
