# Milestones

## v1.0 elc-audit-engine MVP (Shipped: 2026-08-10)

**Phases completed:** 12 phases, 25 plans, 38 tasks

**Key accomplishments:**

- Task 1 — uv project init + directory skeleton
- Locked the RuleResult dataclass contract (D-07/D-08), finalized the 20-code human spot-check fixture (01015C replaced with 20 verified-present codes), and wrote 4 intentionally-failing test files that Plans 02-05 must turn green.
- SQLite `payment_rules`/`drug_rules` tables built from CSV via glob-resolved loaders with ROC/Gregorian-aware date parsing, populating a real 2,669-row + 11,273-row `data/db/rules.sqlite3`.
- Custom PageIndex-style hierarchical tree indexer (python-docx + regex + JSON, zero cloud dependency) processes all 32 source .doc/.docx files into a 1633-node tree JSON, replacing the unusable cloud-only `pageindex` PyPI package.
- Real `rule_mapping` cache built and populated for all 13,942 codes: 6,802 via CSV-reuse fast path, 558 via LLM-assisted docx-tree matching, 6,582 codes honestly resolved to no-match after the LLM found no relevant candidate among its keyword-prefiltered top-5 tree nodes. All 20 human-spot-check codes hit the CSV fast path with real, verifiable article text ready for Plan 05's checkpoint.
- `get_rule(code)` implemented as the sole D-07/D-08 public entry point (zero LLM/network calls, never raises); all 20 human spot-check codes confirmed correct via a published review artifact, closing REQ-rule-repository's third and final acceptance criterion. Phase 2 is complete.
- Non-blocking ChromaDB ingestion pipeline built and run for real: 165 chunks from the 32-file docx tree corpus embedded into a local persistent collection at `data/rag/`, using ChromaDB's default ONNX embedder.
- [03-01-PLAN.md](03-01-PLAN.md)
- [04-01-PLAN.md](04-01-PLAN.md)
- [05-01-PLAN.md](05-01-PLAN.md)
- [06-01-PLAN.md](06-01-PLAN.md)
- [07-01-PLAN.md](07-01-PLAN.md)
- [08-01-PLAN.md](08-01-PLAN.md)
- 1. `config/settings.py` 的 `CASES_DB_PATH` 被平行執行的 09-01 agent commit 意外一併帶入
- W1 合法化 imported→appealed（states.py 單行擴充）、/api/appeal/generate 回應改回 render_appeal_json 單一標準契約（sections/word_stats/p1-p9＋status/case_id/rule_found 三補充鍵、舊鍵全刪）、_to_appeal_case 透傳 rec.id_number 遮罩值——三處整合缺陷一次對齊，並同步測試（移除 fast-forward hack）
- 前端 generateAppealDraft 改讀 render_appeal_json 標準契約鍵（data.sections / data.p8_reason1 / data.p9_reason2），字數警告改由本地字串長度計算，rule_found 提示保留，並以全文子字串回歸測試鎖定舊鍵（appeal_sections/xml_p8_p9_valid/data.reason1/data.reason2）零殘留
- CaseStore appeal payload→submission 契約 dict 標準轉換純函式（8 鍵缺欄誠實留空＋warnings 欄名、id_number 遮罩照印不重建），CLI case_payload 分支改經轉換層，端到端證明完整鍵輸入可完整 join、真實路徑缺欄可歸因
- 欄位組裝層（field_mapping，14 資料欄契約）＋ODT 注入層（odt_fill，ET 文本節點注入/zip 重打包/分頁）＋Wave 0 測試脚手架，並完成 D-03 三聯版式差異與資料來源策略兩項使用者裁示
- 以 build_print_base 一次性把官方 ODT 壓縮成每聯一頁的基準模板（6 輪收斂：關佈局網格＋0.18in 資料行＋每聯 break-before=page → 3 頁、行高 26.4pt 對齊官方 PDF），並以 render_appeal_print 純函式＋write_appeal_print 薄包裝自 generators 對外匯出，e2e/copies/security 測試全綠（22 測試）
- facility.json 院所層設定（D-04，fail-fast）＋ `scripts/build_appeal_print.py` CLI（appeal JSON→一案一 PDF，缺欄「警告：」誠實列印）＋ README 使用說明，收束紙本申復清單輸出通道
- CSV 與 API 兩條路徑的 `deduct_amount → orders[].points`、`order_seq → orders[].seq` 在 `_to_appeal_case`（server.py）與 `build_submission_from_case`（case_to_submission.py）兩層轉換中閉合，紙本申復清單 PDF「金額/醫令序」欄不再因 matched=None 而恆為空白＋警告
- BLOCKER-1 閉合：`LocalFileProvider`/`build_timeline` 首次在真實服務路徑被具現化——`/api/sampling/audit` 與 `/api/appeal/generate` 帶病歷號且來源存在時以半年病史時間軸呼叫比對/生成引擎（不再恆以 timeline=None 降級），回應含 records_source 四態＋中文原因文案，前端兩面板對病歷缺席有可見呈現且 appeal 面板新增可選病歷號輸入欄

---
