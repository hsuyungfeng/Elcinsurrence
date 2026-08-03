# Phase 5: 三方比對器 - Context

**Gathered:** 2026-08-03（由 Phase 2/3/4 交接 + ROADMAP/REQUIREMENTS/D7/D8/C1/C2/C5 整理）
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 5 是引擎核心：對每筆醫令做「醫令↔規則↔病歷」三方比對，逐檢核項判定
支持度（C1），匯總成三級分類（充分/薄弱/裸奔，D7），並對缺口生成候選補強
敘述（D8/C2）。

消費 Phase 2/3/4 的輸出：`get_rule(p4)`、`SubmissionCase`（p4/d19/d20-d26）、
`parse_soap_text`（當次 SOAP 分段）、`build_timeline`（半年病史）。

與 Phase 6（輸出一）的邊界：Phase 5 只產出結構化判定結果（Python 物件），
不產出 Markdown 報告；`CaseComparisonResult` 是 Phase 6 的輸入。

</domain>

<decisions>
## Implementation Decisions

- **D-01（檢核項＝規則全文）:** 結構化檢核項語料不存在（rule_mapping 只存
  article_full_text），故檢核項即「該醫令的規則全文＋出處」單一項目；
  LLM 收到「檢核項（規則要求）＋病歷段落」逐項小問題判定（C1）。
  規則庫查無（get_rule found=False）→ 未知醫令，入 note「查無規則依據，
  建議人工查核」（C5），不評三級（support_level=None）。

- **D-02（證據組裝）:** `build_evidence_blocks(case, soap_doc, timeline)`：
  把當次 SOAP 分段（S/O/A/P）＋半年時間軸（就診/檢驗/檢查/影像）組裝成
  「病歷段落」文字。含長度上限（9B 模型 token 考量）：每類至多 3 筆、
  每筆截斷 500 字；組裝成結構化區塊供 LLM 引用原文（C1 quote）。

- **D-03（LLM 判定器，可注入）:** `judge(check_item, evidence) -> Judgment`
  預設走 `llm_client.chat_completion`，強制 JSON：`{"verdict":
  "支持|部分支持|無記載", "quote": "...", "reason": "..."}`。解析失敗
  換措辭重試一次；仍失敗 → `verdict=待人工`（C5，不阻斷整案）。
  測試注入 fake judge（關鍵字規則式），零 LLM 依賴。

- **D-04（三級分類，純函式）:** `classify_support(judgments)`：
  - 無「無記載」「部分支持」且無「待人工」→ 充分（✅）
  - 任一「部分支持」→ 薄弱（⚠️，有支持但有缺口）— **Phase 8 E2E-01 修正**：
    原實作把「部分支持（無無記載）」歸充分，使「薄弱」在單檢核項流程下
    不可達（D7 三級缺一角）；語意上部分支持＝有記載但不足，正是薄弱
  - 有「無記載」但亦有「支持/部分支持」→ 薄弱（⚠️）
  - 全部「無記載」（或無任何支持證據）→ 裸奔（❌）
  - 任一「待人工」→ manual_review=True（不阻斷，標記供 Phase 6）
  分級只依判定結果，不依賴 LLM（可單元測試）。

- **D-05（候選補強生成，可注入）:** 薄弱/裸奔的缺口才生成 1~3 條候選
  敘述（C2 約束：只能基於既有線索擴寫；無線索時生成提示型「若實際有
  執行，請補充：…」；每條附規則出處 article_location）。測試注入 fake。

- **D-06（錯誤語意，P0-2）:** `get_rule` 的 `RuleRepositoryError`（DB 故障）
  **穿透不吞**——compare_case 不把 infra 故障降級成「查無規則」；只有
  `found=False`（正常查無）才標未知醫令。

- **D-07（病歷缺席降級）:** timeline=None（Phase 4 degraded）時，證據只
  用當次 SOAP；`CaseComparisonResult.records_degraded=True` 供 Phase 6
  報告開頭標「⚠本報告未含病史佐證」（C5）。判定照常進行。

- **D-08（零 LLM 依賴測試）:** 全部純函式（evidence/support）獨立測試；
  LLM 路徑（judger/narratives）以注入替身測試；真實 LLM 判定評測（C6
  第 3 層 30 組金標準）屬 Phase 8。
</decisions>

<deferred>
- 30 組「檢核項×病歷段落」金標準測試集 → Phase 8（C6 第 3 層）。
- 結構化檢核項萃取（把規則全文拆成適應症/頻率限制/病歷記載要求）→ 無
  真實語料前不猜，D-01 以全文為檢核項；Phase 8 真實樣本回放後再評估。
</deferred>

---

*Phase: 5-三方比對器*
*Context gathered: 2026-08-03*
