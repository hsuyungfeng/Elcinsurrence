---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: 紙本→數位化整合三項輸出
current_phase: 14
status: Awaiting next milestone
stopped_at: Resumed session, clarified `phases.clear` confusion (git deleted vs archive), state reset to v1.1 planning, PROJECT.md updated with 17 lines context
last_updated: "2026-08-12T03:02:49.668Z"
last_activity: 2026-08-12 — Milestone v1.1 completed and archived
progress:
  total_phases: 3
  completed_phases: 3
  total_plans: 7
  completed_plans: 7
  percent: 100
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
**GSD Phase 9 — HIS 服務化（本機可驗證）— COMPLETE (2026-08-07)** — 四個 Plans 全數完成 (09-01 認證/審計、09-02 狀態機/CaseStore、09-03 server.py 接線/遷移、09-04 Package Builder 申復 XML)。全測試套件 363 passed / 2 skipped 驗證通過。
**GSD Phase 10 — VPN／實機串接 — 阻塞中**（雲端 Provider 需 doctor-toolbox 存取權、NHI_EIIAPI.DLL 需 Windows＋VPN＋SAM 實機）。2026-08-05 自原 Phase 9 拆出：含阻塞項的 phase 永遠無法通過 verify，會汙染 phase 完成訊號。
**GSD Phase 11 — 紙本申復清單列印 — COMPLETE（2026-08-10，UAT 7/7 通過）** — 僅依賴 Phase 7，不依賴 Phase 9/10，與 Phase 10 阻塞無關可獨立完成。3 個 Plans（11-01/02/03）於 2026-08-08 執行完畢（VERIFICATION 3/3 passed），UAT 於本次 session 跑完剩餘 5 項（測項 3-7）：三聯 CLI 產出、版式與官方範本一致、第二聯核定/複核/初核/審查委員欄僅出現於頁 2、逐欄資料正確、缺欄誠實降級警告、院所設定可由 `FACILITY_CONFIG_PATH` 驅動、錯誤處理友善——全數 pass。UAT 測項 7 過程中發現並修復一個路徑穿越漏洞：`scripts/build_appeal_print.py` 的自訂輸出路徑參數（`output_pdf_path`）原僅驗證 basename，`../x.pdf` 可寫出至專案目錄外（已實測外洩至倉庫上層並清除測試產物）；修復為偵測路徑各段 `os.pardir` 穿越成分並拒絕（校驗後拒絕、非清洗，與既有 `safe_filename` 同一原則），全套件 424 passed / 2 skipped 無迴歸。commit `5b099d2`。

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
- **GSD Phase 9 Plan 01（認證授權＋存取審計日誌）executed and committed.** Delivered: `auth.py`（`load_api_keys()` 解析 `ELC_API_KEYS` 的 `caller:key` 表、`resolve_caller()` 以 `hmac.compare_digest` constant-time 比對並回傳多呼叫方識別、`require_api_key` decorator 保留供未來 blueprint）；`audit_log.py`（`record_access()` JSON Lines 六欄位追加寫入，路徑取自 `AUDIT_LOG_PATH`，**零 PHI**——只記「誰在何時存取哪個端點」，不記請求主體）；`server.py` 以 **`before_request` 統一強制**而非逐端點 decorator（**新增端點預設受保護**，豁免需顯式列入 `_AUTH_EXEMPT_ENDPOINTS`＝`index`/`health`/`static`，避免「忘記加 decorator 就等於裸奔」的失敗模式），`_init_api_keys()` 啟動期 fail-fast 重拋 `AuthConfigError`（設定缺失時繼續啟動＝無認證對外開放，比啟動失敗更危險），`errorhandler(AuthenticationError)` 回 **401 而非 404**，`after_request` 寫審計且 `OSError` 只記 application log 不讓已完成業務回應變 500，新增 `GET /api/health` 供 HIS/監控探測。README 同步認證/審計契約並追認四筆既有 commit。**認證先於業務邏輯**：未帶 key 時 `run_presubmission_check` 替身呼叫次數斷言為 0。38 新測試（test_auth.py 30＋test_audit_log.py 8），全套件 354 passed / 2 skipped。**401 而非 404 與 P0-2／P1-1 同源：系統／授權故障必須與業務結論可區分。** 見 `.planning/phases/09-his-servicing/09-01-SUMMARY.md`.
- **GSD Phase 9 Plan 02（案件狀態機＋SQLite 持久化）executed and committed.** Delivered: `src/elc_audit_engine/case_store/` 純資料層子套件（無 Flask／LLM 依賴）——`states.py` 七狀態顯式轉換表（六主線＋failed 旁支，submitted 為封閉終態，未知狀態一律拋 `UnknownStateError` 而非回 False）；`db.py`／`store.py`：`cases`／`case_transitions` 兩表，`CaseStore` 提供 create/get/transition/history/list_by_state（同步版任務佇列取件，無 Celery／Redis）/list_all/counts_by_state；狀態與轉換歷史於單一 SQLite 交易內原子寫入；`failure_reason` 獨立欄位與業務結論分離（P1-1 同源原則延伸）；case_id 沿用既有 `safe_filename()` 校驗後拒絕。65 新測試全綠，全套件由 277 passed / 2 skipped 增至 336 passed / 2 skipped（`test_ingest.py` 7 個 ERROR 屬平行執行的 09-01 `server.py` 未完成所致，非本 plan 範圍）。刻意未動 `server.py`／既有 `data/uploads/*.json`——端點接線與遷移留給 09-03 裁示。見 `.planning/phases/09-his-servicing/09-02-SUMMARY.md`.

## Not Yet Started

- Phase 3 (解析器) through Phase 9 (HIS 整合佔位) — see ROADMAP.md for full breakdown. Phase 3 (parsers) and Phase 4 (record aggregator) both depend only on Phase 1 (satisfied) and could be planned in either order or in parallel.
- **Phase 11（紙本申復清單列印）— 2026-08-08 新增**：檢討電子 vs 紙本兩種抽審申復流程時發現，
  紙本 OCR 辨識輸入（`media.py`／`table_ocr.py`）與內部資料處理（`CaseStore`／`AppealDraft`）
  皆與電子流程共用引擎，但輸出端只有 Markdown／JSON／申復 XML，缺少可列印 PDF。已依官方
  三聯式範本（`officialdocument/電子申復文件格式/30396_*`，105.04.01 修訂版）新增 Phase 11，
  **依賴 Phase 7（`AppealDraft` 已具備）、不依賴 Phase 10**——紙本列印是獨立輸出通道，
  不需等 VPN/實機串接解除門控即可規劃執行。見 `.planning/ROADMAP.md` Phase 11、
  `.planning/REQUIREMENTS.md` REQ-paper-appeal-print。尚未 `/gsd-plan-phase 11`。

## Blockers

None. Conflict detection found zero BLOCKER-severity issues and zero competing-variant issues. See `.planning/INGEST-CONFLICTS.md`.

## Session Continuity

Last session: 2026-08-11
Stopped at: Resumed session, clarified `phases.clear` confusion (git deleted vs archive), state reset to v1.1 planning, PROJECT.md updated with 17 lines context
Resume file: `.planning/PROJECT.md`

## Current Position

Phase: Milestone v1.1 complete
Plan: —
Status: Awaiting next milestone
Last activity: 2026-08-12 — Milestone v1.1 completed and archived

## Operator Next Steps

- Start the next milestone with /gsd-new-milestone

## Accumulated Context

### Roadmap Evolution

- Phase 09.1 (INSERTED, after 09, 2026-08-08): "Address tech debt: 09 狀態機語義 + W4 契約橋"（URGENT）— 清理 audit 發現之 W1（CaseStore 狀態機 imported→appealed 非法轉換）與 W4（/api/appeal/generate 回應契約 ≠ render_appeal_json 契約）
- Phase 11.1 (INSERTED, after 11, 2026-08-10): "Close milestone audit gaps: Phase 4 病歷時間軸未接入 Flask API + Phase 9/9.1/11 金額數量欄位鏈斷裂"（URGENT）— 第二輪 `/gsd-audit-milestone` 發現 2 個 critical blocker：(1) `RecordProvider`/`LocalFileProvider`（Phase 4）從未被 `server.py` 具現化，事前預審恆以 `timeline=None` 呼叫，生產環境永遠處於病歷缺席降級模式；(2) `deduct_amount`／`order_seq` 在 `_to_appeal_case`（server.py）與 `build_submission_from_case`（09.1 新增轉換層）兩層均未映射到 `orders[].points`/`total_qty`/`seq`，導致紙本申復清單 PDF 金額/數量欄在真實案件恆為空白。詳見 `.planning/v1.0-MILESTONE-AUDIT.md`（第 2 輪，2026-08-10，status: gaps_found）。

## Key References

- `.planning/PROJECT.md` — project overview, locked architecture, source doc precedence
- `.planning/REQUIREMENTS.md` — 9 requirements (8 Phase 1 + 1 Phase 2 placeholder)
- `.planning/ROADMAP.md` — M1-M8 Phase 1 breakdown + Phase 2 placeholder
- `.planning/INGEST-CONFLICTS.md` — conflict detection report (0 blockers, 0 variants, 5 auto-resolved/info)
- `.planning/intel/decisions.md` — full ADR decision detail (D1-D12)
- `.planning/intel/requirements.md` — requirement source detail
- `.planning/intel/constraints.md` — SPEC/DOC technical constraints (C1-C12)
- `.planning/intel/context.md` — DOC background/context notes

**Planned Phase:** 09.1 (address-tech-debt-09-w4) — 3 plans — 2026-08-08T06:06:46.708Z

> **Roadmap Evolution (2026-08-08):** Phase 09.1 (INSERTED, after 09) — "Address tech debt: 09 狀態機語義 + W4 契約橋"（URGENT）

**Current Phase:** 14
**Next recommended run:** `/gsd-plan-phase 11.1`

> **Roadmap Evolution (2026-08-10):** Phase 11.1 (INSERTED, after 11) — "Close milestone audit gaps: Phase 4 病歷時間軸未接入 Flask API + Phase 9/9.1/11 金額數量欄位鏈斷裂"（URGENT）

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-08-11 — Milestone v1.1 started

## Operator Next Steps

- Start the next milestone with /gsd-new-milestone
