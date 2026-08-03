# Phase 8: 端到端測試 - Context

**Gathered:** 2026-08-03（由 Phase 7 交接 + ROADMAP/REQUIREMENTS/C6 整理）
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 8 是**測試階段**：把 C6 五層測試策略補到「全數涵蓋並可執行」，
並以真實管線（比對→補強報告→審核→申復草稿）串出 3 個端到端案例
（充分/薄弱/裸奔各一，ROADMAP 成功條件 4）。介面保留真實樣本替換空間。

五層現況（Phase 1-7 已交付）：
1. 單元測試（pure function 硬檢查）— 已齊（test_appeal/test_reinforcement_report/…）
2. 規則庫驗收（rule_mapping 命中率）— 已齊（test_rule_mapping_spotcheck/build/versions）
3. LLM 判定金標準 30 組 — **本階段建立**（fixture＋回放 harness＋CLI）
4. 端到端 3 案例（規格造：充分/薄弱/裸奔）— **本階段建立**
5. 真實樣本回放 — 介面保留（run_case_pipeline 換真解析器/Provider/規則庫即可）

</domain>

<discovery>
## 探索發現（codebase-memory-mcp + 原始碼調查）

- **E2E-01（Phase 8 發現）:「薄弱」在目前引擎不可達。**
  `compare_case` 每醫令只查一筆規則、產生單一 `Judgment`；而
  `classify_support` 目前把「部分支持（無無記載）」歸為**充分**，把「薄弱」
  定義為「有無記載＋有支持/部分支持」（需多重判定）。結果：單檢核項流程下
  只有 充分/裸奔 兩級可達，D7 三級缺一角。語意上「部分支持＝有記載但有缺口」
  正是 ⚠️薄弱 — 修正 `classify_support`：任一「部分支持」→ 薄弱（有支持
  但不足）；純「支持」且無無記載 → 充分。鎖定測試一併更新。
- Phase 6/7 輸出層已就緒（render_report/render_tracking/render_appeal），
  但缺少「把整條管線接起來」的單一入口 — 本階段新增 `pipeline.run_case_pipeline`。
- `adopted_narratives_from_tracking` 目前不回傳 order_code，appeal 無法
  依醫令過濾證據 — 本階段補上 order_code 鍵（向後相容）。

</discovery>

<decisions>
## Implementation Decisions

- **D-01（金標準 fixture）:** `tests/fixtures/llm_gold_standard_30.json` —
  30 筆 `{id, rule_text, evidence, expected_verdict, note}`，判定分佈
  支持 12／部分支持 9／無記載 9（含空證據/無相關記載等邊界）。
  內容為臺灣健保審查常見場景（檢驗/影像/用藥/手術/疫苗/轉診/會診…）。
- **D-02（回放 harness）:** `src/elc_audit_engine/eval/gold_standard.py` —
  `load_gold_standard(path=None)`、`evaluate(judge_fn, cases) ->
  GoldStandardResult`（total/correct/accuracy/per_verdict/mismatches）。
  judge_fn 可注入替身（D-08）；`scripts/replay_gold_standard.py` 為 CLI：
  真實 LLM 回放（health guard，伺服器未啟動即說明並 exit 1），
  輸出逐筆表＋準確率（換模型回歸基準，C6-3）。
- **D-03（端到端管線）:** `src/elc_audit_engine/pipeline.py` —
  `run_case_pipeline(case, soap_doc, timeline, deduction_records, *,
  output_dir, rule_lookup=None, judge_fn=None, narrative_fn=None,
  decisions=None, reviewed_at=None, appeal_options=None) -> PipelineResult`
  （comparison＋report/tracking 路徑＋逐筆 appeal 路徑與草稿）。每筆核減
  醫令：依 order_code 過濾採用敘述 → get_rule 注入規則全文（RuleRepositoryError
  不阻斷整案，單筆降級為查無規則）→ build_appeal_draft → write_appeal
  （同一流水號多筆時 file_stem 加醫令碼）。
- **D-04（E2E 3 案例）:** `tests/test_e2e_pipeline.py` 參數化三案例
  充分/薄弱/裸奔，全管線斷言：報告徽章＋候選補強＋軌跡狀態＋appeal 四段
  ＋JSON p1-p9。案例以規格造資料（SubmissionCase/SOAP/timeline/rule stub/
  judge stub/narrative stub），真實樣本替換空間＝換注入層。
- **D-05（E2E-01 修正）:** `classify_support`：任一「部分支持」→ 薄弱
  （不再歸充分）；無部分支持且無無記載且無待人工 → 充分；其餘規則不變。
  更新 `test_classify_support_partial_counts_as_support` 為
  `test_classify_support_partial_is_weak`，並在 05-CONTEXT D-04 加修正註記。
- **D-06（既有驗收確認）:** C6-1 單元測試、C6-2 規則庫驗收測試已存在，
  本階段以全套件綠（+ 金標準 + E2E）作為五層涵蓋證明，不重造既有測試。

</decisions>

<deferred>
- 真實樣本回放（C6-5）：待核減明細實體檔（D-14b-rev reader 參數）、門診抽樣
  樣本 CSV、過去人工申復案例到位後，以 run_case_pipeline 換真輸入回放。
- 結構化檢核項萃取（多檢核項規則 → 每醫令多重判定）：E2E-01 修正後薄弱
  已可達（部分支持），但「一筆規則拆多個檢核項」仍為未來強化，不屬本階段。
</deferred>

---

*Phase: 8-端到端測試*
