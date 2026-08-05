# Deepflash4Improve — elc-audit-engine 深度調查與改進意見

> 調查日期：2026-08-03
> 方法：codebase-memory-mcp 知識圖譜（full index：980 nodes / 1,838 edges）＋原始碼逐檔閱讀＋實際跑測試＋檢查資料產物（SQLite／docx_trees.json／ChromaDB collection）
> 狀態：Phase 1、2 已完成；Phase 3（解析器）context 已蒐集、尚未規劃
> 追加審查：2026-08-04 — 全項目審查（對照 Cloud HIS／Local Gateway 目標架構），見第七節

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

---

## 七、全項目審查（2026-08-04，對照目標架構）

> 觸發：使用者提供生產目標架構圖（Cloud HIS 九服務＋Local Gateway 七元件＋VPN/SAM/Reader→健保署 IDC），要求 review 專案。
> 方法：4 個平行只讀子代理（核心引擎正確性／規則庫與資料層安全／Web API 安全／架構差距）＋ pytest 全量回放。
> 測試基線：`201 passed / 1 skipped`（103s，全綠；與 progress.md Phase 8 一致）。

### 7.1 舊發現（第一～六節）現況對照

| 舊編號 | 內容 | 狀態（2026-08-04） |
|---|---|---|
| P0-1 | soffice 探測太弱 | ✅ 已修（真實轉檔探測） |
| P0-2 | get_rule 錯誤語意 | ✅ 已修（RuleRepositoryError；本次覆核 `rule_repository/__init__.py:57-91` 行為正確） |
| P1-3 | 表格未進 full_text | ✅ 已修（165→282 chunks，99.98% 有候選） |
| P1-4 | rule_mapping 無版本追蹤 | ✅ 已修（source_version＋增量）；**但 CSV 版本僅取檔名 6 位數、無內容 hash**，見 7.2 P1-4 |
| P1-5 | ChromaDB 不可觀測 | 🟡 部分（skipped 合約仍在；collection 無版本綁定，換版重跑會 `::dupN` 堆積） |
| P1-6 | 清依賴 | ⚠️ 已修但有副作用：flask 被誤刪，而 server.py 仍 `import flask` → 依賴漂移，見 7.2 P0-2 |
| P2-9 | parse_flexible_date | ❌ 未修（本次再次發現：`2025-13-99` 非法日期仍可產出） |

### 7.2 新發現（本次審查）

#### P0 — 上線前必須處理

**P0-1｜server.py 是「演示殼」而非 Gateway API，且預設危險**
- `/api/sampling/audit`（`server.py:74-104`）用關鍵字 if/else 硬編碼判定，**未呼叫引擎**；`/api/appeal/generate`（`server.py:161-196`）模板字串拼接，**無 P6 硬檢查、無 p8/p9 各 ≤1000 校驗**，與核心 `build_appeal_draft` 契約不一致。
- `app.run(host='0.0.0.0', port=5000, debug=True)`（`server.py:199-201`）：無認證＋監聽全網卡＋debug 回顯堆疊。
- 修法：端點接 `run_case_pipeline`／`build_appeal_draft`；`debug=False`＋綁定 127.0.0.1 或加認證；統一 `@app.errorhandler` 脫敏 JSON。

**P0-2｜flask 依賴漂移：乾淨環境直接崩**
- `pyproject.toml:9-14` 無 flask（P1-6 誤判「未使用」），但 `server.py:18` 實際 import；`uv sync` 重建後 `python server.py` 會 ImportError，README 啟動說明失配。
- 修法：加回 `flask` 依賴並 `uv lock`。

**P0-3｜`.gitignore` 漏掉輸出目錄，PHI 可能進公開倉庫**
- `.gitignore:23-29` 未排除 `data/output/*`；跑一次 pipeline 即產出含 SOAP/醫囑的 `病歷補強報告_*.md`、`審核軌跡_*.json`、`申復草稿_*.md`（`reinforcement_report.py:187-196`、`appeal.py:539-545`），而 remote 為公開 GitHub。
- `config/llama_config.json` 含本機絕對路徑 `/home/hsu/llama.cpp/...` 且已被 git 追蹤。
- 修法：`.gitignore` 追加 `data/output/*`（保留 `.gitkeep`）；llama 路徑改環境變數並清查 git 歷史。

#### P1 — 影響正確性／安全

**P1-1｜「待人工」被歸為「裸奔」（系統故障→業務結論誤判）**
- `judger.py:97-107` 把 LLM 逾時/解析失敗降級為 VERDICT_MANUAL，但 `support.py:54-56` 的 else 分支把「全部待人工」歸為 SUPPORT_NONE（❌ 裸奔），且會再觸發一次注定失敗的 narrative LLM 呼叫（`comparator.py:116-117`）。
- 修法：全待人工時 `support_level=None` 輸出「待判定」態。

**P1-2｜LLM prompt 注入面**
- `judger.py:83-86` 把 `rule_text`（LLM 生成後寫回 SQLite，`build_mapping.py:329-336`）與用戶可控病歷原文直接拼接，無角色隔離；`mapping/prompts.py:36-49` 同理。
- 修法：prompt 加 `<data>` 定界＋「以下僅為資料」聲明。

**P1-3｜三處路徑穿越（目前 HTTP 面未暴露，一接即爆）**
- `record_aggregator/providers.py:135-136`：`patient_id`（XML d3）未 sanitize → 讀取型穿越；`reinforcement_report.py:187-188`、`appeal.py:538-540`：`case_record_no`/`case_seq` 未校驗字符集 → 寫入型穿越。
- 修法：統一 `safe_filename()`（basename＋`^[A-Za-z0-9_-]+$` 白名單）。

**P1-4｜規則庫版本管理缺口**
- `mapping/versions.py:23-29` CSV 版本只取檔名 6 位數字、無內容 hash：換版不改名 → 增量建置跳過 → rule_mapping 引用舊條文（docx 側有 hash 是對的）。
- `chroma_store.py:97-117` 無版本綁定、失敗僅靜默 `status="skipped"`。

**P1-5｜前端 XSS 面＋入參零校驗**
- `static/index.html:363-371` 用 `innerHTML` 拼接 API 欄位（現為硬編碼資料不觸發；CSV 匯入一上線即爆，UI 已承諾「匯入 CSV」卻無實現）。`server.py` 所有入參無長度/型別校驗。
- 修法：`textContent` 建 DOM＋CSP；請求 schema 校驗（SOAP≤10KB 等），非法 400。

#### P2 — 體質（節錄）

- `parsers/soap.py:80-92` 空標記行（「S：」後換行）導致段內容落入 unclassified；
- `comparator/narratives.py:80-81` LLM 失敗 `except: return []` 靜默，與「確無可生成」無法區分；
- `parsers/deduction.py:110-113` `_parse_int` 靜默截斷小數/科學記號；
- `comparator/narratives.py:90` `bool("false")` 誤判 prompt_only 為 True；
- `generators/appeal.py:495-497` p3/p4/p5 恆為 None 無 schema 校驗；
- `generators/appeal.py:285-287` `_split_reason` 純字元位置硬切，句子中間斷裂；
- `pipeline.py:161-163` 未傳 `claimed_points` 時所有草稿恆帶硬檢查錯誤；
- `judger.py:33` `_JSON_OBJECT_RE` 貪婪匹配多段 JSON 會誤解析；
- 隱私：病歷號進證據文本與檔名（`evidence.py:79-80`）、`DeductionRecord.raw` 含未遮罩出生日期，若被日誌/API 序列化會外洩；
- `submission_xml.py:254-257` 本地 XML 會展開內部實體（billion laughs，目前僅 CLI 路徑）；
- `server.py:28` 無 `app.secret_key`；回應無 CSP/X-Content-Type-Options（`static/index.html:10` 外鏈 Google Fonts 無 SRI）。

### 7.3 目標架構差距矩陣（Cloud HIS／Local Gateway）

| 架構元件 | 現況 | 說明 |
|---|---|---|
| Cloud HIS · Rule Engine | ✅ 已有（最完整） | `rule_repository/` 13,942 碼全帶版本、docx 樹 1,633 節點、查詢零 LLM |
| Review / Appeal Service | 🟡 部分 | 真實邏輯在引擎（`pipeline.py run_case_pipeline`、`build_appeal_draft`），但 server.py 端點未接線（假邏輯，P0-1） |
| Validation / Audit Service | 🟡 碎片 | 硬檢查散落 appeal.py/parsers；醫師逐條審軌跡（D9）已實現；傳輸稽核缺失 |
| Package Builder | ❌ 缺失 | 無 PDF/DICOM/申復 XML 序列化，目前只出 .md/.json |
| Upload Queue / Status Service | ❌ 缺失 | 無任務佇列、無案件狀態機 |
| Local Gateway 全 7 元件 | ❌ 缺失（白紙） | Heartbeat／Job Downloader／AES 快取／NHI Adapter／Retry Manager／Status Reporter／NHI_EIIAPI.DLL 均無任何程式碼 |
| VPN + SAM + Reader → 健保署 IDC | ❌ 缺失 | 行政/硬體前置，非純程式問題 |

**結論**：引擎＝架構圖的「大腦」，服務外殼＝零。Phase 2（HIS 整合）完全未開工，Local Gateway 整側空白。NHI_EIIAPI.DLL 倉庫中無 DLL、無頭檔、無 wrapper，只有協定文件線索（電子抽審.md §四）。Phase 2 粗估 2–3 個月，最大風險點：Package Builder（官方格式規格）與 DLL 實機驗證。

### 7.4 建議執行順序（更新）

1. **P0-1** server.py 接真實引擎＋安全預設（debug=False、綁定本機/認證、統一錯誤處理）— 0.5–1 天
2. **P0-2** 加回 flask 依賴＋`uv lock` — 半天
3. **P0-3** `.gitignore` 補 `data/output/*`、llama 路徑脫敏 — 半天
4. **P1-1** support.py 全待人工→「待判定」— 半天
5. **P1-2** prompt 定界隔離 — 半天
6. **P1-3** 統一 `safe_filename()` — 半天
7. **P1-4** CSV 內容 hash＋ChromaDB 版本綁定 — 1–2 天
8. 之後才進入 Phase 2 服務化拆分

### 7.5 執行紀錄（2026-08-04）

**測試基線：`207 passed / 1 skipped`**（原 201 passed；新增 6 個測試，無回歸）。

| 項目 | 狀態 | 說明 |
|---|---|---|
| P0-3 | ⏸️ 使用者決定暫緩 | 倉庫稍後轉為 private，現階段不擋 `data/output/*` |
| P0-2 | ✅ 已修 | `pyproject.toml` 加回 `flask>=3.0` 並 `uv lock`（flask 3.1.3）；原註解誤稱「未使用」已更正 |
| P0-1 | ✅ 已修 | 見下方細節 |
| P1-1 | ✅ 已修（依使用者裁示升級為 P0） | 見下方細節 |

**P1-1（系統故障偽裝成業務結論）**
- `support.py`：全部「待人工」→ `support_level=None`（待判定），不再歸「裸奔」；空判定清單同理。
- `models.py`：`None` 的兩種成因（`rule_found=False` 查無規則 vs `rule_found=True` 判定失敗）寫入契約文件。
- `reinforcement_report.py`：`_support_badge()` 依 `rule_found` 分辨，新增「⏳ 待判定」徽章——原本兩種成因都印「❓ 查無規則」。
- 測試：`test_classify_support_manual_flags_review` 原本斷言 `== SUPPORT_NONE`（把 bug 鎖進測試），已改為斷言 `is None`；另補「待人工混合有效判定仍正常分級」與報告徽章不混淆的回歸測試。

**P0-1（server.py 假邏輯＋危險預設）— 採選項 C**
- `pipeline.py` 新增 `run_presubmission_check()`＋`PresubmissionResult`：事前預審＝唯讀比對，不產草稿、不寫檔（對應架構圖 Review Service 與 Appeal Service 分離）。
- `/api/sampling/audit`：移除硬編碼關鍵字 if/else，改接 `run_presubmission_check`＋Phase 3 真實 `parse_soap_text`。
- `/api/appeal/generate`：移除模板拼接，改接 `build_appeal_draft`。原第三段「規則依據」是把醫令碼代入固定句型＝**為任何醫令捏造法規依據**；字數檢查亦由錯誤的「合計 2000」改為 Q15 的「p8/p9 各 ≤1000」。
  - 實測旁證：硬編碼示範資料稱 `64140C` 為「手腕韌帶縫合術」，規則庫實際為「甲床與手指重建術」——假資料本身就是錯的。
- 安全預設：`debug=False`、綁定 `127.0.0.1`，三者皆可經 `ELC_SERVER_*` 環境變數覆寫；新增統一 `@app.errorhandler` 脫敏（不回傳 traceback）＋入參型別/長度校驗（SOAP ≤10KB，識別欄位 ≤200 字）——部分回應 P1-5。
- `RuleRepositoryError` → HTTP 503（規則庫故障不偽裝成「查無規則」，D-06/P0-2 語意延伸至 HTTP 層）。
- 前端 `static/index.html` 同步：徽章改以引擎結果為準（原停留在清單硬編碼值、且從不更新）、新增「⏳ 待判定」分支、`appeal_sections` 改讀陣列、字數改顯示 p8/p9 各別計數。

**尚未處理**：P0-3（使用者暫緩）、P1-2 prompt 注入、P1-3 路徑穿越、P1-4 版本管理、P1-5 前端 XSS（`innerHTML` 部分）、全部 P2。
（→ P1-2／P1-3／P1-5 已於 2026-08-05 完成，見 §7.6。）

---

### 7.6 執行紀錄（2026-08-05）— P1-2／P1-3／P1-5

**測試基線：`277 passed / 1 skipped`**（原 235 passed；新增 42 個測試，無回歸）。

| 項目 | 狀態 | 說明 |
|---|---|---|
| P1-5 | ✅ 已修 | 前端 XSS＋CSP＋移除外鏈字型 |
| P1-2 | ✅ 已修 | prompt 標籤定界隔離（3 處） |
| P1-3 | ✅ 已修 | `safe_filename()` 統一防線（3 處） |
| P1-4 | ⬜ 未處理 | CSV 內容 hash＋ChromaDB 版本綁定（下一項） |

**P1-3（路徑穿越）— 採「校驗後拒絕」而非「清洗取代」**
- 新增 `src/elc_audit_engine/safe_paths.py`：`safe_filename(value, field_name)`＋`UnsafeIdentifierError`。
- 白名單為 **ASCII 英數＋`_`＋`-`＋CJK**（2026-08-05 使用者裁示）：`case_record_no`／`case_seq`／`patient_id` 皆來自健保檔案，可能含中文，純 ASCII 白名單會把真實資料判為非法。刻意不用 `\w`——它在 Python 是 Unicode-aware，範圍遠大於「中文＋英數」。
- **實作期抓到的真 bug**：初版先取 `os.path.basename()` 再校驗，而 `basename('../etc/passwd')` 回傳 `'passwd'`（白名單可通過）＝**把攻擊悄悄清洗成合法檔名**，正是本次明確拒絕的靜默改寫行為。改為直接校驗原始值（路徑分隔符與 `.` 均不在白名單內）。此 bug 由新測試 `test_safe_filename_rejects_traversal_and_bad_chars` 當場抓出。
- 選擇拒絕而非清洗的理由：清洗會讓 `A/1` 與 `A_1` 收斂成同一檔名，兩個不同案件的 PHI 報告互相覆寫且無人察覺。**與 P1-1／P0-2 同源原則：系統故障必須與業務結論可區分，不得靜默產生看似正常的結果。**
- 三處呼叫點：`providers.py::_records_path`（讀取型，XML `d3`）、`reinforcement_report.py::write_report`（寫入型）、`appeal.py::write_appeal`（寫入型，校驗組合後的 `file_stem`，故 `18_1` 等合法組合不受影響）。
- HTTP 面：`server.py` 目前不直接呼叫這三者（端點走唯讀的 `run_presubmission_check`／`build_appeal_draft`）。`UnsafeIdentifierError` 繼承 `ValueError`，既有的統一 `@app.errorhandler(Exception)` 會回脫敏 500——**fail closed**，未來端點接上寫檔路徑時不會外洩內部路徑。

**P1-2（prompt 注入）— 緩解，非證明安全**
- 新增 `src/elc_audit_engine/prompt_safety.py`：`fence(payload, tag)`＋`DATA_ISOLATION_NOTICE`。
- **關鍵細節**：包夾前先中和 payload 內的閉合標籤（含 `</ RULE >` 等大小寫／空白變體），否則資料可自行關閉標籤逃逸到指令層——與輸出 HTML 前需先轉義同理。合法角括號（如 `血壓 <140/90`）不受影響。
- 三處呼叫點：`judger.py::judge`（`<rule>`／`<record>`）、`narratives.py::generate`（`<rule_location>`／`<rule>`／`<record>`）、`mapping/prompts.py`（`<code>`／`<name>`／`<category_hint>`／`<candidates>`）。system prompt 均附資料隔離宣告。
- **誠實界定範圍**：這降低成功率，不代表安全——LLM 仍可能服從資料內指示。真正邊界仍在下游：`judger` 只接受 `VERDICTS` 白名單，非法值降級待人工。**不得以「已加定界」為由放寬輸出校驗。**
- 注意 `rule_text` 是**二階不可信**：由 `build_mapping.py` 的 LLM 批次生成後寫回 SQLite，即 LLM 產出回流為 LLM 輸入。

**P1-5（前端 XSS＋CSP）— 嚴重性隨時間上升**
- 原審查註明「現為硬編碼資料不觸發；CSV 匯入一上線即爆」。**匯入已於 `56d9902` 上線，此休眠漏洞已活化**——`renderCaseList` 的 `order_code`／`patient_name`／`order_name` 全部來自使用者上傳的 CSV／OCR 結果。教訓：**靜態安全清單需在功能上線時重新評級，而非只在發現時評一次。**
- `static/index.html::renderCaseList` 改以 DOM API 建構（`createElement`＋`textContent`），移除 innerHTML 樣板。其餘 API 欄位早已走 `innerText`／`.value`（不解析 HTML），經全檔稽核確認 `renderCaseList` 是唯一注入點。
- 移除 Google Fonts 外鏈（`preconnect` ×2＋`stylesheet`）：本服務接觸病歷資料，外鏈字型會把使用者 IP 與瀏覽行為送到第三方，與 D2「個資不出本機」相衝，且離線／VPN 環境下載入失敗。改用系統字型堆疊（保留 `'Noto Sans TC'` 等作本機優先，僅去掉網路取用）。
- `server.py` 新增 `@app.after_request` 安全標頭：CSP（`default-src 'self'`、`object-src 'none'`、`frame-ancestors 'none'`、`base-uri 'none'`、`form-action 'self'`）＋`X-Content-Type-Options: nosniff`＋`Referrer-Policy: no-referrer`＋`X-Frame-Options: DENY`。inline `style`/`script` 暫留 `'unsafe-inline'`（頁面為單檔 inline 樣板），待拆出外部 `.css`/`.js` 後可移除此例外。
- 回歸測試含**負向控制**：刻意重新植入 `innerHTML` 樣板後 `test_frontend_case_list_does_not_use_innerhtml_templating` 確實失敗（已驗證後還原），確認該測試不是空過。

---

## 八、PaddleOCR 評估（2026-08-04，紙本表格結構化升級）

> 觸發：使用者提供 ClinFusion（達摩院醫學影像 MLLM）評估是否對本專案有用。
> 結論：ClinFusion 解決「讀醫學影像」（X光/CT/MRI），本專案缺的是「讀掃描文件」
> （紙本抽樣/核減清單）——是兩種「影像」；表格結構化應選 PaddleOCR。

### 8.1 ClinFusion 評估摘要

- **定位**：Vision-Centric 醫學多模態 LLM（Qwen3-VL-8B/32B＋DINOv2/ConvNeXt），醫學 VQA／報告生成；Apache-2.0。
- **不匹配**：非文檔/表格 OCR；**GPU-only**（requirements：vllm＋flash-attn 預編譯 wheel＋多卡）；倉庫極新（9 commits／16 stars，安裝腳本帶作者個人路徑）。
- **長期價值**：若申復流程未來要自動判讀影像證據（MRI/CT →「醫療必要性」佐證），ClinFusion-8B 為開源 SOTA 候選；pipeline 的 `judge_fn`/`narrative_fn` 可注入層可直接換接，無需改架構。
- **可吸收**：factualness-driven／RoI-grounded 評估原則（與 D9「標記不符事實」、Phase 8 金標準同源）。

### 8.2 PaddleOCR（PP-StructureV3）實測

隔離環境（Python 3.12，CPU）實測：模擬抽樣清單繁體表格圖 → 輸出結構化 HTML：

```html
<table><tr><td>醫令代碼</td><td>醫令名稱</td><td>就醫日期</td></tr>
<tr><td>14050B</td><td>糖化血色素檢驗 HbAlc</td><td>2026/07/10</td></tr>…</table>
```

- ✅ 表頭/欄位對齊正確——tesseract 無法做到（只能錨定醫令代碼）；表格 HTML 可直接對接 8 欄/18 欄契約
- ✅ 繁中＋英文混排；Apache-2.0 商用無礙；本地 CPU 推理符合 D2

**避坑（實測發現）**：

| 項目 | 結論 |
|---|---|
| paddlepaddle 版本 | **3.3.1 在 CPU 有 blocking bug**（`ConvertPirAttribute2RuntimeAttribute`，oneDNN/PIR）→ 釘 **3.2.2** 實測通過 |
| 依賴 | `paddleocr==3.7` 需 `paddlex[ocr]` extra（僅裝 `paddleocr` 會 DependencyError） |
| 緩存目錄 | 預設 `~/.paddlex` 本機唯讀 → 設 `PADDLE_PDX_CACHE_HOME` 指向可寫目錄 |
| 重量 | paddlepaddle wheel ~600MB＋模型首次下載 ~300MB；CPU 熱推理數秒~數十秒/張 |
| OCR 字符瑕疵 | `HbA1c→HbAlc` 等字符級誤識存在；**醫令代碼為錨點**（數字+字母 pattern），其餘欄位供人工核對 |

### 8.3 整合設計（已實作）

`ingest/table_ocr.py`：PP-StructureV3 → 版面 `table` 元素 HTML → `<tr>/<td>` 解析 → 表頭列對映 `sampling.COLUMN_ALIASES` 契約欄位 → `SamplingCaseRecord`（source="paddle"）。paddleocr 不可用（未安裝/import 失敗）時自動降級回 `ocr_rows.py` 的 tesseract 行解析——延續「誠實降級」精神：有表格結構化就用，沒有就用代碼錨點，絕不靜默給錯誤結構。

pyproject.toml 新增 `[project.optional-dependencies] ocr`（paddlepaddle==3.2.2、paddleocr、paddlex[ocr]）——不強制安裝，`uv sync --extra ocr` 才啟用。
