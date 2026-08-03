# Phase 6: 輸出一（病歷補強報告）- Context

**Gathered:** 2026-08-03（由 Phase 5 交接 + ROADMAP/REQUIREMENTS/D8/D9 整理）
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 6 把 Phase 5 的 `CaseComparisonResult` 渲染成「病歷補強報告.md」——
Markdown checkbox 逐條審格式（D8：Phase 1 為 Markdown checkbox 檢核表），
供醫師逐條審核（D9 四狀態：採用/編輯後採用/略過/標記不符事實），並留下
審核軌跡 JSON（D9：狀態、原文、編輯後文、時間）。

純渲染層：**無 LLM、無規則庫查詢**（與 Phase 3/4 相同約束）。報告是
「建議＋待審」文件，不是最終申復草稿（Phase 7 的組裝器才消費審核結果）。

</domain>

<decisions>
## Implementation Decisions

- **D-01（報告結構）:** `render_report(comparison) -> str`（Markdown 文字）：
  1. 標題＋案件資訊（病歷號、診斷）
  2. ⚠ 警告區（records_degraded → 「⚠本報告未含病史佐證」；unknown_orders；
     manual_review_orders）
  3. 逐醫令區塊：醫令碼＋支持度徽章（✅充分/⚠️薄弱/❌裸奔/❓查無規則）
     ＋判定（verdict＋引用原文 quote）＋規則出處
  4. 候選補強敘述（薄弱/裸奔才有）：checkbox 逐條「[ ] 敘述（出處）」
  5. 半年病史摘要區（timeline 存在時：就診/檢驗/檢查/影像筆數＋最近 3 筆摘要）

- **D-02（checkbox 語意）:** 候選補強敘述預設未勾選 `[ ]`；醫師勾選＝採用、
  編輯後勾選＝編輯後採用。四狀態由軌跡 JSON 記錄（D-03），Markdown 只承載
  初始狀態（checkbox 是醫師操作的 UI）。

- **D-03（審核軌跡 JSON）:** `render_tracking(comparison, decisions) -> str`
  產出審核軌跡 JSON（D9：每條狀態、原文、編輯後文、時間）。decisions 為
  醫師審核結果輸入（逐條：adopt/edit/decline/flag + edited_text），
  未審核（空 decisions）時輸出「未審核」預設軌跡（狀態=未審核），
  供 Phase 7 組裝器讀取。

- **D-04（時間戳）:** 軌跡 JSON 的 reviewed_at 使用 ISO 8601（UTC）；
  測試注入固定時間（reviewed_at 參數），避免測試不穩定。

- **D-05（檔案輸出）:** `write_report(output_dir, case_record_no, comparison,
  decisions=None)`：寫 `病歷補強報告_{病歷號}.md` ＋ `審核軌跡_{病歷號}.json`
  （對齊 C7 命名慣例）。output_dir 可注入（預設 config.settings.OUTPUT_DIR）。

- **D-06（純函式核心）:** `render_report`/`render_tracking` 都是純函式
  （輸入→字串），可單元測試；檔案輸出是薄包裝（D-05）。
</decisions>

<deferred>
- 整稿確認（組裝器：採用清單→完整草稿 p8/p9 四段）→ Phase 7（D9 的
  「組裝後整稿自由刪改再定稿」）。
- HIS 點選 UI（Phase 2 的 doctor-toolbox 整合）→ Phase 9。
</deferred>

---

*Phase: 6-輸出一（病歷補強報告）*
*Context gathered: 2026-08-03*
