---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
stopped_at: **Phase 11 已規劃完成（3 plans / 3 waves，驗證通過）——待執行**
last_updated: "2026-08-08T03:23:10.928Z"
progress:
  total_phases: 11
  completed_phases: 9
  total_plans: 20
  completed_plans: 18
  percent: 90
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
- **GSD Phase 9 Plan 01（認證授權＋存取審計日誌）executed and committed.** Delivered: `auth.py`（`load_api_keys()` 解析 `ELC_API_KEYS` 的 `caller:key` 表、`resolve_caller()` 以 `hmac.compare_digest` constant-time 比對並回傳多呼叫方識別、`require_api_key` decorator 保留供未來 blueprint）；`audit_log.py`（`record_access()` JSON Lines 六欄位追加寫入，路徑取自 `AUDIT_LOG_PATH`，**零 PHI**——只記「誰在何時存取哪個端點」，不記請求主體）；`server.py` 以 **`before_request` 統一強制**而非逐端點 decorator（**新增端點預設受保護**，豁免需顯式列入 `_AUTH_EXEMPT_ENDPOINTS`＝`index`/`health`/`static`，避免「忘記加 decorator 就等於裸奔」的失敗模式），`_init_api_keys()` 啟動期 fail-fast 重拋 `AuthConfigError`（設定缺失時繼續啟動＝無認證對外開放，比啟動失敗更危險），`errorhandler(AuthenticationError)` 回 **401 而非 404**，`after_request` 寫審計且 `OSError` 只記 application log 不讓已完成業務回應變 500，新增 `GET /api/health` 供 HIS/監控探測。README 同步認證/審計契約並追認四筆既有 commit。**認證先於業務邏輯**：未帶 key 時 `run_presubmission_check` 替身呼叫次數斷言為 0。38 新測試（test_auth.py 30＋test_audit_log.py 8），全套件 354 passed / 2 skipped。**401 而非 404 與 P0-2／P1-1 同源：系統／授權故障必須與業務結論可區分。** 見 `.planning/phases/09-his-servicing/09-01-SUMMARY.md`。
- **GSD Phase 9 Plan 02（案件狀態機＋SQLite 持久化）executed and committed.** Delivered: `src/elc_audit_engine/case_store/` 純資料層子套件（無 Flask／LLM 依賴）——`states.py` 七狀態顯式轉換表（六主線＋failed 旁支，submitted 為封閉終態，未知狀態一律拋 `UnknownStateError` 而非回 False）；`db.py`／`store.py`：`cases`／`case_transitions` 兩表，`CaseStore` 提供 create/get/transition/history/list_by_state（同步版任務佇列取件，無 Celery／Redis）/list_all/counts_by_state；狀態與轉換歷史於單一 SQLite 交易內原子寫入；`failure_reason` 獨立欄位與業務結論分離（P1-1 同源原則延伸）；case_id 沿用既有 `safe_filename()` 校驗後拒絕。65 新測試全綠，全套件由 277 passed / 2 skipped 增至 336 passed / 2 skipped（`test_ingest.py` 7 個 ERROR 屬平行執行的 09-01 `server.py` 未完成所致，非本 plan 範圍）。刻意未動 `server.py`／既有 `data/uploads/*.json`——端點接線與遷移留給 09-03 裁示。見 `.planning/phases/09-his-servicing/09-02-SUMMARY.md`。

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

Last session: 2026-08-08（`/gsd-resume-work` → `/gsd-plan-phase 11` 完成）
Stopped at: **Phase 11 已規劃完成（3 plans / 3 waves，驗證通過）——待執行**
Resume file: `.planning/phases/11-paper-appeal-print/11-01-PLAN.md`

**Phase 11 規劃摘要（2026-08-08）：** research（11-RESEARCH.md，含實機 spike）→ pattern map
（11-PATTERNS.md）→ 3 plans（11-01 欄位組裝＋注入＋分頁含 D-03 checkpoint；11-02 壓縮基準
模板＋soffice 端到端；11-03 facility config＋CLI＋安全防線）→ plan-checker 3 輪驗證
0 blocker 收斂。**研究推翻兩項 CONTEXT 假設**：(1) D-03「核定欄在第三聯」實為**第二聯**
（11-01 Task 3 checkpoint 待使用者裁示）；(2) 官方主表為 **14 資料欄**（含傷病名稱欄，
row0 跨列 cell），非 13。壓縮基準模板（官方 ODT 9 頁→3 頁收斂）為最大技術風險，
11-02 Task 1 含 10 輪迭代上限與失敗上報出口。

**⚠️ 2026-08-08 修正**：本節前一版（2026-08-07 寫）聲稱「09-03/09-04 尚未執行、
準備開始 Plan 03」——與 git 實況脫節。實際上 09-03、09-04 皆已完成並 commit
（`860a13f`、`c2eb24f`），且其後還有 5 個 commit。**教訓（重複發生）：
STATE.md 的敘述性欄位會與 git 脫節，恢復時一律以 `git log` 與檔案系統實況為準覆核。**

**Phase 9 進度（COMPLETE 2026-08-07）：**

| Plan | 範圍 | 狀態 |
|---|---|---|
| 09-01 | 認證授權＋審計日誌 | ✅ COMPLETE（`25bf03a`／`e537c02`／`a2022f8`） |
| 09-02 | 案件狀態機＋SQLite 持久化 | ✅ COMPLETE（`c8602e5`／`f8d5dd6`／`1c298d4`） |
| 09-03 | 端點接 CaseStore＋uploads 遷移 | ✅ COMPLETE（`860a13f`） |
| 09-04 | Package Builder（申復 XML 序列化） | ✅ COMPLETE（`c2eb24f`） |

**Post-Phase-9 commits（2026-08-07，STATE.md 未追蹤到，本次補記）：**

- `948d8ad` docs(09): STATE／ROADMAP 標記 Phase 9 完成
- `61c8495` docs: README 補 HIS 系統串接步驟與 API 整合流程
- `0ebfa43` fix(ui): header 加 API Key 輸入欄位＋所有請求帶 X-API-Key
- `fcde2c8` feat(api): **依使用者裁示**，全部業務端點停用強制 API Key 認證，
  改走直接 HIS 對接（`_AUTH_EXEMPT_ENDPOINTS` 擴大納入六個業務端點）。
  09-01 的認證機制（constant-time 比對、審計日誌）程式碼仍在，只是不再強制——
  屬刻意政策轉向，非退化。

- `e7ace46` style(ui): 移除已無用的 API Key 輸入欄位（呼應上一 commit）
- `5915022`／`f19eb2e` fix(ingest): OCR 醫令代碼正則擴大支援 5-6 碼英數混合＋
  大小寫不敏感子字串搜尋修正（`ocr_rows.py`）

**2026-08-05 修復（詳見 `deepflash4improve.md` §7.6）：**

- **P1-5 前端 XSS＋CSP**：`renderCaseList` 改 DOM API（`createElement`＋
  `textContent`）；移除 Google Fonts 外鏈（D2 個資不出本機）；`server.py`
  新增 `@app.after_request` 安全標頭。**此漏洞原為休眠，因 `56d9902` 匯入
  上線而活化——教訓：靜態安全清單需在功能上線時重新評級。**

- **P1-3 路徑穿越**：新增 `safe_paths.py::safe_filename()`（校驗後拒絕，
  非清洗取代；白名單含 CJK）。實作期抓到自身 bug：初版先取 `basename()`
  會把 `../etc/passwd` 悄悄清洗成 `passwd` 而通過白名單。

- **P1-2 prompt 注入**：新增 `prompt_safety.py::fence()`，三處 prompt 標籤
  定界；包夾前中和 payload 內閉合標籤防逃逸。**緩解非證明安全**，下游
  `VERDICTS` 白名單校驗仍是真正邊界。

**2026-08-04 修復（詳見 `deepflash4improve.md` §7.5）：**

- **P0-2 flask 依賴漂移**：`pyproject.toml` 加回 `flask>=3.0`＋`uv lock`。
- **P1-1（升級為 P0）系統故障偽裝成業務結論**：`classify_support` 全「待人工」
  → `support_level=None`（待判定），不再歸「裸奔」；報告新增「⏳ 待判定」徽章，
  依 `rule_found` 與「查無規則」分辨。**與 D-06/P0-2「DB 故障 ≠ 查無規則」同源
  原則：系統故障必須與業務結論可區分。**

- **P0-1 server.py 假邏輯**：新增 `run_presubmission_check()`（事前預審＝唯讀比對，
  不寫檔），`/api/sampling/audit` 與 `/api/appeal/generate` 改接真實引擎；
  安全預設 debug=False＋綁 127.0.0.1＋統一錯誤脫敏＋入參校驗。

**Carry into Phase 9：**

- `pipeline.py` 現有**兩個**入口，對應架構圖兩個服務：
  `run_presubmission_check`（Review Service，唯讀）／`run_case_pipeline`
  （Appeal Service，寫檔）。Phase 9 服務化拆分直接沿用此切分。

- **P0-3 使用者決定暫緩**（倉庫稍後轉 private）：`data/output/*` 目前**未**被
  `.gitignore` 排除，跑 pipeline 後 `git add -A` 會把 PHI 入庫——轉 private 前
  務必人工確認暫存區。

- ~~未處理：P1-2 prompt 注入、P1-3 路徑穿越、P1-5 前端 XSS~~ → **已於
  2026-08-05 完成（`f6ac775`）**。~~P1-4 版本管理（CSV 內容 hash＋ChromaDB
  版本綁定）~~ → **已於 2026-08-05 完成（`5f1f38e`），deepflash4improve.md
  §7.6 追蹤表當時未同步、2026-08-08 補記確認**。**仍未處理：P2 全部。**

- **2026-08-08 新發現並修復 P1-6（審計日誌回歸）**：`fcde2c8`（2026-08-07，
  依使用者裁示停用業務端點強制 API Key 認證）誤把認證豁免清單
  `_AUTH_EXEMPT_ENDPOINTS` 拿去兼做審計豁免判斷依據，導致六個接觸病歷資料
  的業務端點**完全停止寫審計日誌**，違反 09-01「認證可選、審計必留」設計。
  已拆成 `_AUDIT_EXEMPT_ENDPOINTS`（僅 index/health/static）與
  `_AUTH_EXEMPT_ENDPOINTS`（兩者聯集）兩份獨立清單修復，並讓豁免端點若仍
  帶合法 key 也會解析 `caller_id`（否則審計會全落成 anonymous）。
  `tests/test_auth.py` 7 個測試斷言同步改寫。測試基線 `374 passed / 2
  skipped`。詳見 `deepflash4improve.md` §7.7。**教訓：兩個語義不同的白名單
  不應共用同一個 frozenset，即使目前外延相同。**

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

**Planned Phase:** 11 (paper-appeal-print) — 3 plans — 2026-08-08T02:13:49.066Z
