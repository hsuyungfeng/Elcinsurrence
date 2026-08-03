# Phase 8 Plan 01 Summary — 端到端測試交付

**Plan:** [08-01-PLAN.md](08-01-PLAN.md)
**Status:** ✅ Complete — 197 passed / 5 skipped（前 176 passed / 5 skipped，新增 21 測試全綠）

## Deliverables

| 檔案 | 內容 |
|------|------|
| `tests/fixtures/llm_gold_standard_30.json` | 30 組「檢核項×病歷段落×預期判定」金標準（支持 12／部分支持 9／無記載 9，含空證據/無相關記載邊界） |
| `src/elc_audit_engine/eval/gold_standard.py` | `load_gold_standard`（欄位/唯一性/判定合法性驗證）＋`evaluate(judge_fn, cases) -> GoldStandardResult`（正確率/per-verdict/mismatches）；judge_fn 可注入替身（D-08） |
| `scripts/replay_gold_standard.py` | 真實 LLM 回放 CLI（health guard，伺服器未啟動 exit 1）；換模型回歸基準（C6-3） |
| `src/elc_audit_engine/pipeline.py` | `run_case_pipeline(case, soap_doc, timeline, deduction_records, *, output_dir, rule_lookup, judge_fn, narrative_fn, decisions, reviewed_at, appeal_options) -> PipelineResult`：比對→補強報告＋審核軌跡→逐筆申復草稿（D10 每筆獨立） |
| `src/elc_audit_engine/comparator/support.py` | **E2E-01 修正**：`classify_support` 任一「部分支持」→ 薄弱（原歸充分使薄弱不可達） |
| `src/elc_audit_engine/generators/appeal.py` | `adopted_narratives_from_tracking` 輸出加 `order_code` 鍵（appeal 依醫令過濾證據，向後相容） |
| `tests/test_gold_standard.py`（14 測試） | fixture 完整性/分佈 12-9-9/load 驗證（壞檔/重複 id/非法判定）/evaluate（全對 1.0、誤判回報、per-verdict）/CLI importable＋server down exit 1 |
| `tests/test_e2e_pipeline.py`（7 測試） | 三案例（充分/薄弱/裸奔）全管線斷言＋未知醫令誠實提示＋同流水號多筆防覆寫＋RuleRepositoryError 穿透（比對）／降級（appeal） |

## E2E-01 修正（Phase 8 發現）

`compare_case` 每醫令單一判定，而 `classify_support` 原把「部分支持（無無記載）」
歸充分 → 「薄弱」需「支持＋無記載」多重判定，單檢核項流程下**不可達**，D7 三級
缺一角。修正：任一「部分支持」→ 薄弱（部分支持＝有記載但有缺口，語意即薄弱）。
05-CONTEXT D-04 已同步加修正註記；`test_classify_support_partial_counts_as_support`
改為 `test_classify_support_partial_is_weak`。

## 端到端三案例（run_case_pipeline）

| 案例 | judge 判定 | 支持度 | 管線斷言 |
|------|-----------|--------|----------|
| 充分 | 支持 | ✅ 充分 | 報告徽章；無候選；appeal ④ 佔位；軌跡空 |
| 薄弱 | 部分支持 | ⚠️ 薄弱 | 候選補強 checkbox；採用敘述流入 appeal ④ |
| 裸奔 | 無記載 | ❌ 裸奔 | 提示型候選；編輯後採用敘述流入 appeal ④ |

輸出檔案：`病歷補強報告_{病歷號}.md`＋`審核軌跡_{病歷號}.json`＋
`申復草稿_{流水號}.md`＋`appeal_{流水號}.json`（同流水號多筆核減時第二筆起
`file_stem={流水號}_{醫令碼}` 防覆寫）。

## C6 五層測試策略涵蓋（Phase 8 完成後）

1. ✅ 單元測試（pure function 硬檢查）— Phase 1-7 既有套件
2. ✅ 規則庫驗收（rule_mapping 命中率）— test_rule_mapping_spotcheck/build/versions
3. ✅ LLM 判定金標準 30 組 — 本階段（fixture＋harness＋回放 CLI）
4. ✅ 端到端 3 案例 — 本階段（充分/薄弱/裸奔）
5. ⏳ 真實樣本回放 — 介面就緒（run_case_pipeline 換真輸入），待核減明細實體檔/抽樣 CSV/過去人工申復案例到位

## 對接說明（Phase 9）

- `run_case_pipeline` 為 HIS 整合/真實樣本回放的引擎接入點。
- `appeal_{流水號}.json`（含 p1-p9 醫令段欄位）為轉申復 XML 的輸入契約。
- A001 虛擬醫令綜整、t38/t39 總計、申復 XML 序列化、雲端病歷 Provider、Flask API → Phase 9。
