# Phase 5 Plan 01 Summary — 三方比對器交付

**Plan:** [05-01-PLAN.md](05-01-PLAN.md)
**Status:** ✅ Complete — 139 passed / 5 skipped（前 110 passed / 5 skipped，新增 29 測試全綠）

## Deliverables

| 檔案 | 內容 |
|------|------|
| `src/elc_audit_engine/comparator/models.py` | Verdict 常數（支持/部分支持/無記載/待人工）＋CheckItem（規則全文＋出處）＋Judgment（verdict/quote/reason）＋OrderJudgment（rule_found/support_level/manual_review/narratives）＋CandidateNarrative（text/rule_location/prompt_only）＋CaseComparisonResult |
| `src/elc_audit_engine/comparator/evidence.py` | `build_evidence_blocks(case, soap_doc, timeline)`：當次 SOAP 四段＋半年病史四類組裝；每類至多 3 筆、每筆截斷 500 字；timeline=None 時只輸出 SOAP |
| `src/elc_audit_engine/comparator/support.py` | `classify_support(judgments)` 三級分類純函式（充分/薄弱/裸奔）＋manual_review 旗標 |
| `src/elc_audit_engine/comparator/judger.py` | `LLMJudger`（JSON 強制＋```json 容忍＋換措辭重試一次＋失敗降級待人工）＋`create_judger` 注入點 |
| `src/elc_audit_engine/comparator/narratives.py` | `LLMNarrativeGenerator`（JSON array、至多 3 條、每條附規則出處、prompt_only 旗標）＋`create_generator` 注入點 |
| `src/elc_audit_engine/comparator/comparator.py` | `compare_case(case, soap_doc, timeline, rule_lookup=, judge_fn=, narrative_fn=)` 主流程 |
| `src/elc_audit_engine/comparator/__init__.py` | 對外 API |
| `tests/test_comparator.py`（29 測試） | 三級分類各情境、證據組裝（含截斷/病歷缺席）、主流程（充分/裸奔＋補強/未知醫令/DB 故障穿透/降級/待人工/多醫令混合）、judger JSON 解析＋重試＋網路錯誤降級、narratives 解析＋上限＋失敗空清單 |

## Real-Data Verification（真實 TOTFA 首案＋真實規則庫，注入替身判定器）

```
案件: d3=M220518024 醫令數=11 主診斷=S90221A
比對: 醫令=11 未知醫令=7 待人工=0 records_degraded=True
  AC37603100: found=False source=unknown support=None note=查無規則依據，建議人工查核
  A013382100: found=True source=drug support=充分
  ...
```
- 11 筆醫令：4 筆查得到規則（source=drug/payment）、7 筆未知醫令誠實標記
  「查無規則依據，建議人工查核」（C5），不幻構規則。
- records_degraded=True（未提供 timeline）符合 D-07。

## 決策落地

- **D-01**：檢核項＝規則全文＋出處（article_full_text or payment_text）。
- **D-03/C1**：LLM 判定強制 JSON、```json 包覆容忍、失敗換措辭重試一次、仍失敗降級「待人工」（不阻斷整案）。
- **D-04**：三級分類純函式（無記載=0 且支持>0→充分；有無記載且有支持→薄弱；全無記載→裸奔；任一待人工→manual_review）。
- **D-05/C2**：候選補強僅薄弱/裸奔生成、至多 3 條、每條附 article_location、prompt_only 旗標（提示型）。
- **D-06/P0-2**：`RuleRepositoryError` 穿透；`found=False` 才標未知醫令。
- **D-07**：timeline=None → records_degraded=True（Phase 6 報告標⚠）。
- **D-08**：judge_fn/narrative_fn/rule_lookup 全可注入；測試零真實 LLM 依賴（judger/narratives 的解析與重試以 mock 驗證）。

## 對接說明（Phase 6）

- `CaseComparisonResult` 是病歷補強報告的唯一輸入：逐醫令 support_level
  （充分/薄弱/裸奔）＋judgment.quote（引用原文）＋narratives（候選補強）。
- `records_degraded` → 報告開頭「⚠本報告未含病史佐證」；`unknown_orders`
  ／`manual_review_orders` → 報告附註。
- 真實 LLM 判定評測（C6 第 3 層 30 組金標準）屬 Phase 8。
