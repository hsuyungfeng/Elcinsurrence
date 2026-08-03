# Phase 6 Plan 01 Summary — 病歷補強報告交付

**Plan:** [06-01-PLAN.md](06-01-PLAN.md)
**Status:** ✅ Complete — 152 passed / 5 skipped（前 139 passed / 5 skipped，新增 13 測試全綠）

## Deliverables

| 檔案 | 內容 |
|------|------|
| `src/elc_audit_engine/generators/reinforcement_report.py` | `render_report(comparison, timeline=None) -> str`：Markdown checkbox 逐條審報告（標題/病歷號/警告區/逐醫令支持度徽章/候選補強 checkbox/半年病史摘要）；`render_timeline_summary(timeline)`；`write_report(output_dir, case_record_no, comparison, decisions, ...)` 薄包裝 |
| `src/elc_audit_engine/generators/tracking.py` | `render_tracking(comparison, decisions, reviewed_at=None) -> str`：審核軌跡 JSON（D9 四狀態＋原文＋編輯後文＋時間）；decisions 輸入 `{index: (status, edited_text)}`；未審核預設 status=未審核；reviewed_at 可注入 |
| `src/elc_audit_engine/generators/__init__.py` | 對外 API（render_report/render_timeline_summary/render_tracking/write_report＋四狀態常數） |
| `tests/test_reinforcement_report.py`（13 測試） | 報告結構/徽章（✅充分/❌裸奔/❓查無規則）/checkbox 格式/verdict＋quote/警告區（records_degraded/unknown/manual）/半年病史摘要/軌跡 JSON（四狀態/非法狀態回退/無敘述）/檔案輸出 |

## Real-Data Verification（真實 TOTFA 首案）

```
[報告] 長度=957 字元 | 醫令區塊=11 | 警告區=True
# 病歷補強報告
- 病歷號：`M220518024`
## ⚠ 注意事項
- ⚠ 本報告未含病史佐證（病歷缺席，僅以當次 SOAP 判定）
- ⚠ 未知醫令（查無規則依據，建議人工查核）：`AC37603100`、...
### A013382100（序 2）
- 支持度：✅ 充分
- 判定：支持
  - 引用原文：> 病歷記載局部腫脹、壓痛
- 規則出處：`CSV:drug_rules.payment_text`
[檔案] 病歷補強報告_M220518024.md / 審核軌跡_M220518024.json
```

## 決策落地

- **D-01**：報告結構五段（標題/警告區/逐醫令/候選補強 checkbox/半年病史摘要）。
- **D-02**：候選補強預設 `- [ ] 敘述〔提示型〕（出處）` 未勾選，四狀態由軌跡 JSON 記錄。
- **D-03/D-04**：審核軌跡 JSON 逐條含 status（採用/編輯後採用/略過/標記不符事實/未審核）＋narrative_text（原文）＋edited_text＋reviewed_at（ISO UTC，可注入固定時間）。
- **D-05**：`write_report` 薄包裝寫 `病歷補強報告_{病歷號}.md`＋`審核軌跡_{病歷號}.json`。
- **D-06**：render_report/render_tracking 純函式，可單元測試；輸出層薄。

## 對接說明（Phase 7）

- Phase 7 組裝器讀取 `審核軌跡_{病歷號}.json`：採用/編輯後採用的敘述 → 申復草稿 ④病歷佐證段。
- 「標記不符事實」→ 幻覺回饋品質監控指標（D9，獨立記錄）。
- 整稿確認（採用清單→p8/p9 四段）屬 Phase 7。
