# Deepflash4Improve — elc-audit-engine 深度調查與改進意見

> 調查日期：2026-08-03
> 方法：codebase-memory-mcp 知識圖譜（full index：980 nodes / 1,838 edges）＋原始碼逐檔閱讀＋實際跑測試＋檢查資料產物（SQLite／docx_trees.json／ChromaDB collection）
> 狀態：Phase 1、2 已完成；Phase 3（解析器）context 已蒐集、尚未規劃

---

## 一、現況快照（實測數據）

| 項目 | 實測結果 |
|---|---|
| 測試 | `30 passed / 3 failed / 2 skipped`（失敗集中在 soffice 轉檔） |
| SQLite | `payment_rules` 2,669 列、`drug_rules` 11,273 列、`rule_mapping` 13,942 列（`data/db/rules.sqlite3`） |
| docx 樹 | 32 份來源文件（11 .doc + 21 .docx）→ `data/db/docx_trees.json`，1,633 節點 |
| ChromaDB | `rule_articles` collection 僅 **165 chunks**（見發現 #3） |
| 程式結構 | `rule_repository/` 完整實作；`parsers/ comparator/ generators/ record_aggregator/` 仍是空殼 docstring |

## 二、做得好的地方（維持）

- **以真實資料驅動決策**：`TOTFA.xml`（633 案 / 2,624 醫令 / Big5 / CRLF）的欄位出現率實測（`d20` 73.3%、`d10` 18.6%…）直接寫進 Phase 3 context，決策有證據而非臆測。
- **查詢路徑零 LLM**（D-05）：`get_rule()` 純查表，LLM 只在一次性建置使用，符合「病歷/文件不出本機」的隱私紅線。
- **誠實降級，不捏造**：`rule_mapping` 6,582 碼「無匹配」寫 `article_source=None`；批次前先 `smoke_test()` 防 schema-descriptor 垃圾文字寫入（`build_mapping.py`）。
- **介面品質**：`RuleResult` frozen dataclass + `not_found()` 工廠 + 完整中文 docstring（`models.py`）；`get_rule` 對外單一入口，內部三層封裝乾淨。
- **合規意識**：`.gitignore` 把 `TOTFA.xml`、PHI 目錄擋在版控外；參數化 SQL 防注入有測試把關（T-02-08）。
- **規劃文件品質極高**：`03-CONTEXT.md` 的 D-01~D-20（Big5 解碼策略、致命/可容忍欄位分級、SOAP 兩層策略、核減 CSV 為主要輸入）具體、可驗證、有真實檔佐證。

## 三、發現與風險（依優先級）

### P0 — 會咬人的問題

**1. 測試不是全綠：soffice 功能探測太弱**
`tests/test_doc_converter.py` 與 `tests/test_docx_tree_coverage.py` 的 `_soffice_is_functional()` 只跑 `soffice --version`（回傳 0），但 headless 轉檔在 `/run/user/1000` 唯讀的環境（沙箱/CI）會 exit 1（dconf profile 寫入失敗）。實測 `soffice --version` 成功、同一環境轉檔失敗 → 3 個測試掛掉且永遠不會被 skip 機制接住。
改法：把探測升級為「對一個最小 .docx 做真實轉檔」；或轉檔呼叫加 `-env:UserInstallation=file://<writable>` + 可寫 HOME。否則之後任何 CI/沙箱跑測試都是紅燈，真實環境的轉檔正確性也無從驗證。

**2. `get_rule` 的錯誤語意會誤導 Phase 5**
`get_rule()` 把**所有** `sqlite3.Error` 一律降級成 `not_found`（`warnings.warn` 就吞掉了）。Phase 5 比對器無法區分「這醫令真的沒有規則」vs「DB 壞掉／表被刪／檔案不存在」。在醫療給付情境，這會把系統性故障偽裝成「查無規則」。
改法：增加 typed exception（如 `RuleRepositoryError`）或讓 `RuleResult` 帶 `degraded=True` 旗標＋錯誤統計；至少要有一支測試鎖定「DB 壞掉 ≠ not_found」的語意。

### P1 — 影響正確性的結構問題

**3. 表格內容是最大的盲點（很可能解釋 46% 無匹配與 6,582 筆無匹配）**
docx 樹把表格全部丟進 `table_refs`（實測 **213 個表格區塊**），而 1,633 節點中只有 **165 個節點有 `full_text`**。意思是：審查注意事項裡大量以表格呈現的條文（給付項目、點數、條件對照），在以下三條路徑全部隱形：
- 關鍵字候選計分 `_score_candidate()`（只掃 `title + full_text`）
- ChromaDB chunks（所以 collection 只有 165 chunks）
- LLM 候選 prompt（`build_candidate_matching_prompt` 只看 `path + full_text` 前 100 字）

這極可能就是 deferred 項目「ChromaDB 檢索 46% 無匹配率」與 6,582 筆「誠實無匹配」的結構性成因——不是模型差，是語料在來源端就被切掉了。
改法：`extractor.build_tree_for_file` 把 `table_refs` 的儲存格文字以固定分隔格式（如 `|`）併入節點 `full_text`（表格通常掛在最近的標題節點下）；重跑 `build_docx_trees` → 重建 ChromaDB → 對原 6,582 無匹配碼抽樣複查，驗證無匹配率是否大幅下降。

**4. `rule_mapping` 無版本追蹤、一次性批次無法續跑**
來源 CSV 檔名內含版本日期（`251027` / `260605`），但 DB 沒有版本欄位；13,942 碼的批次若中斷必須全重跑（LLM 路徑 558 碼每次都重來）。deferred 項目「rule_mapping 版本追蹤」應該現在就做，因為 Phase 4/5 會依賴它判斷「規則庫是否過期」。
改法：`rule_mapping` 表加 `source_version` 欄（寫入時記錄來源 CSV 版本與 docx 語料 hash）；`build_rule_mapping` 改增量（只處理缺 mapping 或版本不符的碼），並支援 checkpoint/續跑。

**5. ChromaDB 輔助層「不可觀測」**
`build_chroma_collection` 的 non-blocking `skipped` 合約很安全，但真實失敗（embedding 模型首次下載無網路、權限問題）只回 `status="skipped"`，不會有 log 或告警——使用者會以為向量層已就緒，其實 collection 可能幾乎是空的。實測 collection 只有 165 chunks，無人察覺。
改法：`main()` 印出 collection count 健康檢查（如 `rule_articles: 165 chunks`）；skipped 時寫 logger.error 而非只回 dict。

**6. 依賴與說明文件欠整理**
`pyproject.toml` 宣告的 `flask`、`pandas`、`pageindex` 在 src/tests 完全沒有 import（`pageindex` 只在 `docx_tree/__init__.py` 的 docstring 被提及）；`README.md` 只有一行，三個建置腳本（`build_sqlite` → `build_docx_trees` → `build_chroma_index` → `build_rule_mapping`）的執行順序只寫在各自 docstring。
改法：移除未用依賴（用到再加）；補 README 管線說明；加 ruff 設定（deferred 項目）讓 CI 有最低 lint 門檻。

### P2 — 體質改善

**7. `build_all_trees` 的 zip 配對脆弱**：`zip(doc_source_paths, converted_docx_paths)` 依賴兩邊排序一致；若 soffice 少產出一個檔會靜默錯配。建議改用「原檔路徑 → 轉檔路徑」的顯式 dict，或對應後驗證檔名。

**8. `_score_candidate` 逐字元掃描**：O(名稱字數 × 節點全文)，對 7,360 個需要候選的碼是建置期可接受；若改增量/頻繁重跑會放大。可改用字元 set 交集加速。

**9. `parse_flexible_date` 的小瑕疵**：`try/except` 包住 f-string 格式化是 dead code（不會拋 ValueError）；且未驗證真實曆法（如月份 13 會產出 `2026-13-01` 這種非法字串）。建議用 `datetime.date` 驗證，失敗回 None＋警告。

**10. `patterns.py` depth 6 同時掛「（一）」與「1.」**：對現有 32 份文件已驗證 OK，但新增語料時需靠 `test_docx_tree_coverage` 把關；建議該測試改為對 `RULE_SOURCE_DIR` 全語料跑（目前只有 1 份 flat doc 案例）。

## 四、對 Phase 3（解析器）的意見

- **規劃品質極高，方向都對**：Big5 解碼順序（big5→cp950→big5hkscs→utf-8）、CRLF 不假設 LF、致命/可容忍欄位分級（D-05~D-08）、SOAP marker/keyword 兩層策略＋信度標記（D-10/D-11）、「無關鍵詞命中不預設 subjective」的重寫決定——全部支持。
- **趁 Phase 3 定案錯誤語意**：與發現 #2 連動。`ParseResult` 的「拒收案＋原因＋警告」設計很好，但下游 Phase 5 同時吃 ParseResult 與 RuleResult，兩者的「缺資料 vs 系統故障」語意必須一致，否則 Phase 5 會把解析器故障誤判成「該案無可救」。
- **核減 CSV 規格未到手**：`03-CONTEXT.md` 已正確記錄「本機無樣本、已知形態為 CSV」。規劃時先鎖欄位契約＋容忍度（D-14 精神），避免 Phase 3 後半被規格變更打斷。
- **保持解析器純度**：不呼叫 `get_rule()`、無外部依賴、可單獨測試——這是對的，別為了「方便」把 SQLite 依賴偷渡進解析器。

## 五、知識圖譜的額外觀察

- 複雜度熱點全在 `rule_repository`：`build_rule_mapping`（complexity 11 / cognitive 26）、`build_tree_for_file`（7/21）、`build_chroma_collection`（8/11）、`get_rule`（5/11）。建議把「單一 code 的 LLM 比對」抽成獨立函式（現在內嵌在 120 行的批次迴圈裡），單測與重試都更好做。
- 目前 clusters 幾乎都標成 tests/officialdocument，因為四大核心套件還是空殼；等 Phase 3-5 實作後，圖譜才會長出真正的架構分群——屆時值得重跑一次 index 再看熱點。

## 六、建議執行順序（若要我接著做）

1. **P0-1**：修 soffice 探測（真實轉檔探測）→ 測試回到全綠。
2. **P0-2**：`get_rule` 錯誤語意（typed exception / degraded 旗標）＋鎖定測試。
3. **P1-3**：表格併入 `full_text` → 重跑 docx_trees/ChromaDB → 複查無匹配率。
4. **P1-4**：`rule_mapping` 版本追蹤＋增量建置。
5. **P1-6**：清依賴、補 README 管線。
