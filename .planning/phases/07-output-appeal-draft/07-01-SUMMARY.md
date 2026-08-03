# Phase 7 Plan 01 Summary — 申復理由草稿交付

**Plan:** [07-01-PLAN.md](07-01-PLAN.md)
**Status:** ✅ Complete — 176 passed / 5 skipped（前 152 passed / 5 skipped，新增 24 測試全綠）

## Deliverables

| 檔案 | 內容 |
|------|------|
| `src/elc_audit_engine/generators/appeal.py` | `build_appeal_draft(record, *, is_appealing, claimed_points, timeline, rule_text, rule_location, evidence, has_attachment) -> AppealDraft`：D10 四段組裝（①案情摘要/②醫療必要性/③規則依據/④病歷佐證）；字數控制器（官方 Q15：每欄 1000／合計 2000、裁剪優先 ④→②、①③骨架不動）；P6 不申覆強制填 0 純函式硬檢查（C3/Q13）；D-15 核減上界檢查；`adopted_narratives_from_tracking`（審核軌跡消費）；`render_appeal_markdown`／`render_appeal_json`／`write_appeal`（C7 輸出） |
| `src/elc_audit_engine/generators/__init__.py` | 對外 API 擴充（build_appeal_draft/write_appeal/adopted_narratives_from_tracking 等） |
| `tests/test_appeal.py`（24 測試） | 四段結構／案情摘要內容／必要性降級／規則依據誠實提示／審核軌跡只取採用+編輯後採用（edited 優先）／字數裁剪（④先裁②未動、④裁完②壓縮、骨架獨超→over_limit）／p8/p9 各 1000 切分／P6 硬檢查（不申覆→0、超上界/負數/缺點數→validation_errors）／每筆獨立／C7 命名＋file_stem 防覆寫／JSON p1-p9 欄位＋p7 Y/N |

## Official Spec 落地（官方文件交叉驗證）

- **欄位**：`電子申復格式及填表說明門診.pdf` 醫令段 p1-p9 — p1 醫令序號、p2 醫令代碼、p3 改支序號（△）、p4 成數受理（△）、p5 數量受理（△）、p6 點數受理（＊必填，不申復填 0）、p7 申復檔案連結（Y/N）、p8 申復理由一（△，1000 中文字，超過填理由二）、p9 申復理由二（△，合計超過 2000 建議檔案連結）。
- **字數**：`申復作業電子化作業問答集(院所版).pdf` Q15 — p8/p9 各 1000 中文字、總長度放寬至 2000（每欄 1000／合計 2000）。
- **P6**：Q13 — 不申復填入 0；若申復該流水號，該流水號所有核減/改支醫令要完整申報（案件層規則，Phase 2 XML 層把關）。
- **A001**：註 5／Q15-4 — 單一理由可用虛擬醫令 A001 綜整陳述；屬 Phase 2 申復 XML 上傳層組裝選項，Phase 7 只做每筆獨立生成（D10）。

## 決策落地

- **D-01**：`generators/appeal.py` 純組裝層；規則全文由呼叫端經 `get_rule()` 注入字串（零規則庫查詢、零 LLM）。
- **D-02**：四段各自獨立生成；①③為骨架不動（C4），②④可裁。
- **D-03**：字數上限＝官方 Q15（每欄 1000／合計 2000）；裁剪優先 ④→②；裁完仍超 → `over_limit=True`＋報告建議 p7=Y。
- **D-04**：`resolve_p6_points` 不申覆強制 0；`validate_appeal_claim` 申覆點數≤核減上界（D-15 欄 1 不予核銷金額）、不得為負、申覆必填 — 驗證失敗進 `validation_errors` 不靜默修正。
- **D-05/D-06**：`write_appeal` 預設 `申復草稿_{案件流水號}.md`＋`appeal_{流水號}.json`（C7）；JSON 含 p1-p9 醫令段欄位＋四段＋word_stats＋validation_errors（Phase 2 轉 XML 契約）；`file_stem` 供多筆核減醫令防覆寫。
- **D-07**：病歷缺席（timeline=None）→ ②「（病歷缺席，無半年病史可資佐證）」；未知規則 → ③誠實提示（不幻覺捏造）。
- **D-08**：`adopted_narratives_from_tracking` 只取採用/編輯後採用（edited_text 優先）。

## Real-Data Verification（deduction_sample.csv 首列 E5002C）

```
[草稿] 案件 D2/18｜醫令 E5002C（序 1）｜核減上界 300｜P6=300（申覆）｜字數 288/2000
四段齊全：①案情摘要（含追扣原因/申復事項）②（病歷缺席降級）③條文+出處 ④兩條採用敘述（含出處）
p8=全文（288 字）｜p9=（免填）｜appeal_18.json 可解析、p1-p9 欄位齊
```

## 對接說明（Phase 8）

- 端到端測試以 `parse_deduction_file → build_timeline → compare_case → write_report → (人工 decisions) → build_appeal_draft → write_appeal` 為主軸組 3 案例（充分/薄弱/裸奔各一）。
- `appeal_{流水號}.json` 即 Phase 2 轉申復 XML 的輸入契約（p3/p4/p5 目前為 null，待改支檔/院所填報）。
- 真實驗收仍缺：核減明細實體檔（D-14b-rev reader 參數鎖定）、門診抽樣樣本檔 CSV、過去人工申復案例（申復結果 ground truth）。
