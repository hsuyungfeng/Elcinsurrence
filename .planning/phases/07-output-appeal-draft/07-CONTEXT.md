# Phase 7: 輸出二（申復理由草稿）- Context

**Gathered:** 2026-08-03（由 Phase 6 交接 + ROADMAP/REQUIREMENTS/D10 + 官方規格書整理）
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 7 把「核減明細一列（一筆核減醫令）」組裝成申復理由草稿（D10 四段：
①案情摘要 ②醫療必要性 ③規則依據 ④病歷佐證），輸出
`申復草稿_{案件流水號}.md`（醫師審閱版）＋ `appeal_{流水號}.json`
（Phase 2 轉申復 XML，C7）。

**純組裝層：無 LLM、無規則庫查詢**（與 Phase 6 相同約束）。規則全文由
呼叫端經 `get_rule()` 取得後以字串注入（零 LLM、保持 pure）；審核軌跡
JSON 為 Phase 6 產出，本階段只讀取「採用／編輯後採用」的敘述。

輸入（全數已交付）：
- Phase 3 `DeductionRecord`（D-14d 18 欄）— 每筆核減醫令一列
- Phase 4 `PatientTimeline`（半年病史，②醫療必要性素材）
- Phase 6 `審核軌跡_{病歷號}.json`（採用/編輯後採用敘述，④病歷佐證）
- 規則全文＋出處（呼叫端注入；D-15 核減上界＝欄 1 不予核銷金額）

</domain>

<decisions>
## Implementation Decisions

- **D-01（模組與 API）:** 新增 `generators/appeal.py`。純函式核心
  `build_appeal_draft(record, *, is_appealing, claimed_points, timeline,
  rule_text, rule_location, evidence, has_attachment) -> AppealDraft`；
  渲染 `render_appeal_markdown(draft)`／`render_appeal_json(draft)`；
  檔案輸出 `write_appeal(output_dir, case_seq, draft)` 薄包裝（D-06）。

- **D-02（四段組裝，D10）:** 每段獨立生成（每段分開組裝文字）：
  ①案情摘要（費用年月/就醫日期/案件分類/流水號/醫令/追扣原因/申復事項/核減上界）
  ②醫療必要性（半年病史，`build_necessity(timeline)`；timeline=None 降級）
  ③規則依據（條文原文＋出處；無規則 → 誠實提示「查無規則依據，建議人工查核」）
  ④病歷佐證（審核軌跡採用/編輯後採用敘述，`edited_text` 優先）。

- **D-03（字數控制器，C4/Q15）:** 上限以官方問答集 **Q15** 為準：
  p8/p9 **各 1000 中文字、合計放寬至 2000**（取代 C8 舊「2000/欄」）。
  裁剪優先序 **④→②**（C4：④引文摘短、②病史壓縮），①③為骨架不動。
  ④逐條證據列由尾端移除、剩餘列再摘短；②由尾端壓縮。全部可裁段裁完
  仍超 → `over_limit=True`＋報告建議以 p7=Y 檔案連結提供（Q15 第 2 點）。

- **D-04（P6 硬檢查，C3）:** 純函式 `resolve_p6_points(is_appealing,
  claimed_points)`：**不申覆 → 強制 0**（官方 Q13「P6 不申復填入 0」）；
  申覆 → claimed。`validate_appeal_claim(claimed_points, upper_bound)`：
  申覆必填點數、claimed≥0、claimed≤核減上界（D-15，欄 1 不予核銷金額；
  官方 p6 勾稽「申復點數需<=核減點數」）。驗證失敗進 `validation_errors`
  （不靜默修正，留給醫師確認），P6=0 則直接強制。

- **D-05（檔案輸出，C7）:** `write_appeal` 預設命名
  `申復草稿_{案件流水號}.md` ＋ `appeal_{流水號}.json`（案件流水號＝
  `DeductionRecord.case_seq`）。同一案件多筆核減醫令時以 `file_stem`
  參數避免覆寫（預設維持 C7 命名，測試釘住）。

- **D-06（JSON 契約）:** `appeal_{流水號}.json` 含申復 XML 醫令段
  p1（醫令序號）p2（醫令代碼）p3（改支序號，null）p4（成數受理，null）
  p5（數量受理，null）p6（點數受理）p7（申復檔案連結 Y/N）p8（申復理由一）
  p9（申復理由二，超過 1000 才填）＋案件資訊＋四段 sections＋
  word_stats＋validation_errors。p8/p9 各 ≤1000 由 `split_reason` 切分。

- **D-07（降級與誠實輸出）:** 病歷缺席（timeline=None）→ ②降級文字
  「（病歷缺席，無半年病史可資佐證）」（C5）；未知規則（rule_text=None）
  → ③誠實提示，不幻覺捏造（比照 Phase 2 教訓）。

- **D-08（審核軌跡消費）:** `adopted_narratives_from_tracking(tracking)`
  解析 Phase 6 軌跡 JSON（字串或 dict），只取 status ∈ {採用, 編輯後採用}
  的條目，`edited_text` 優先、其次 `narrative_text`，附 rule_location。

- **D-09（A001 虛擬醫令）:** 官方註 5／Q15-4 允許以虛擬醫令 A001 綜整
  多筆醫令的單一申復理由 — 屬申復 XML 上傳層（Phase 2）的組裝選項，
  Phase 7 只做「每筆核減醫令獨立生成」（D10），A001 綜整延後。

</decisions>

<deferred>
- A001 虛擬醫令綜整、t38/t39 總計、申復 XML 序列化 → Phase 2（HIS/XML 轉換層）。
- 真實驗收：核減明細實體檔（D-14b-rev reader 參數鎖定）＋申復結果回饋。
- 字數控制器採「純字元裁切＋證據列移除」；若實測需語意保留（斷句裁剪），
  留待 Phase 8 端到端評測時強化。
</deferred>

---

*Phase: 7-輸出二（申復理由草稿）*
