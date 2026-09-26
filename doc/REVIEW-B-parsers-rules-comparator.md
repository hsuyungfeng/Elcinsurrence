---
phase: whole-codebase-B-parsers-rules-comparator
reviewed: 2026-09-26T08:47:56Z
depth: deep
files_reviewed: 38
files_reviewed_list:
  - src/elc_audit_engine/parsers/deduction.py
  - src/elc_audit_engine/parsers/models.py
  - src/elc_audit_engine/parsers/soap.py
  - src/elc_audit_engine/parsers/soap_keywords.py
  - src/elc_audit_engine/parsers/submission_xml.py
  - src/elc_audit_engine/comparator/comparator.py
  - src/elc_audit_engine/comparator/evidence.py
  - src/elc_audit_engine/comparator/judger.py
  - src/elc_audit_engine/comparator/models.py
  - src/elc_audit_engine/comparator/narratives.py
  - src/elc_audit_engine/comparator/support.py
  - src/elc_audit_engine/record_aggregator/aggregator.py
  - src/elc_audit_engine/record_aggregator/models.py
  - src/elc_audit_engine/record_aggregator/providers.py
  - src/elc_audit_engine/ingest/media.py
  - src/elc_audit_engine/ingest/ocr_rows.py
  - src/elc_audit_engine/ingest/sampling.py
  - src/elc_audit_engine/ingest/table_ocr.py
  - src/elc_audit_engine/eval/gold_standard.py
  - src/elc_audit_engine/rule_repository/db.py
  - src/elc_audit_engine/rule_repository/models.py
  - src/elc_audit_engine/rule_repository/errors.py
  - src/elc_audit_engine/rule_repository/docx_tree/doc_converter.py
  - src/elc_audit_engine/rule_repository/docx_tree/extractor.py
  - src/elc_audit_engine/rule_repository/docx_tree/patterns.py
  - src/elc_audit_engine/rule_repository/docx_tree/tree_builder.py
  - src/elc_audit_engine/rule_repository/embeddings/chroma_store.py
  - src/elc_audit_engine/rule_repository/loaders/dates.py
  - src/elc_audit_engine/rule_repository/loaders/drug_loader.py
  - src/elc_audit_engine/rule_repository/loaders/payment_loader.py
  - src/elc_audit_engine/rule_repository/mapping/build_mapping.py
  - src/elc_audit_engine/rule_repository/mapping/llm_client.py
  - src/elc_audit_engine/rule_repository/mapping/prompts.py
  - src/elc_audit_engine/rule_repository/mapping/versions.py
  - src/elc_audit_engine/rule_repository/scripts/build_chroma_index.py
  - src/elc_audit_engine/rule_repository/scripts/build_docx_trees.py
  - src/elc_audit_engine/rule_repository/scripts/build_sqlite.py
  - config/settings.py
findings:
  critical: 5
  warning: 21
  info: 14
  total: 40
status: issues_found
---

# 程式碼審查報告 B：解析器／規則庫／比對器

**審查時間：** 2026-09-26T08:47:56Z
**深度：** deep（含跨模組呼叫鏈：server.py → build_timeline／compare_case → get_rule／judger／narratives）
**審查檔案數：** 38
**狀態：** issues_found

## 摘要

本次審查涵蓋申報 XML／核減明細／SOAP 解析器、病歷彙整、三方比對器（judger/narratives/support）、OCR 攝入層、規則庫（SQLite、docx 樹、ChromaDB、LLM mapping 建置）與設定檔。所有「疑似 bug」都以實際執行驗證（見各條「驗證」欄）。

整體評估：
- **SQL 建構是安全的**：`db.py` 以白名單＋靜態 SQL 字典＋`?` 參數化，未發現注入面。
- **XML 解析在目前環境實務上安全**：已實測 Python 3.12.3／expat 2.6.1 會擋下 billion-laughs（放大倍數上限），外部實體不解析（`undefined entity`）。但安全性仰賴執行期 expat 版本，未使用 `defusedxml`（Info）。
- **subprocess** 皆為 argv 陣列、無 `shell=True`，沒有命令注入。
- **核心問題在「資料正確性」與「靜默降級」**：SOAP 標記獨立成行時整份分段失效、規則庫的條文全文其實是 LLM 自由生成的摘要卻被當作權威規則原文、半年病史時間窗以「今天」而非就醫日為基準（會引用就醫日之後的紀錄佐證），以及 OCR 以醫令代碼去重造成不同案件被靜默丟棄。另有一個建置腳本必定崩潰（`settings.PAYMENT_RULES_CSV` 不存在）。
- 金額欄（點數／不予核銷金額）以 `int` 表示，健保點數本為整數，型別選擇合理；但解析路徑有 `OverflowError` 未捕捉與小數靜默截斷。

## Critical Issues

### CR-01：SOAP 標記獨立成行（`S:` 換行後才寫內文）時，全部內容被丟進「未分類」，卻仍標為高信度

**檔案：** `src/elc_audit_engine/parsers/soap.py:85-87`
**問題：** 標記行本身無內容時，程式把 `current = None`，註解寫「繼續等待內文」，但下一行因 `current is None` 而落入 `unclassified`。這是 HIS 最常見的排版（標記獨佔一行）。結果 `sections` 為空、`method="marker"`、`confidence="high"`——對下游宣稱「高信度」但沒有任何 S/O/A/P 段落，`evidence.py` 只能以「[未分類]」呈現，evidence packet builder（`generators/evidence_packet/builder.py:34`）讀 `doc.sections` 則完全空白。
**驗證：** `parse_soap_text("S:\n頭痛三天\nO:\nBP 120/80\nA:\n高血壓\nP:\n回診")` → `sections={}`，`unclassified=('頭痛三天','BP 120/80','高血壓','回診')`。現有測試 `test_marker_multiline_content` 只涵蓋「標記同行有內容」的情境。
**修正：**
```python
if matched is not None:
    if current is not None and current["text"]:
        segments.append(_finish_segment(current))
    content = _MARKER_PATTERNS[matched].sub("", stripped, count=1).strip()
    current = {"cat": matched, "text": content, "method": "marker"}
elif current is not None:
    current["text"] = (current["text"] + "\n" + stripped) if current["text"] else stripped
...
if current is not None and current["text"]:
    segments.append(_finish_segment(current))
```
並新增測試：標記獨佔一行、以及標記後完全無內文兩種情境。

### CR-02：規則庫 `article_full_text` 實為 LLM 自由生成的「摘要」，且 `article_location` 未驗證為候選節點之一，卻被下游當作權威規則原文與出處

**檔案：** `src/elc_audit_engine/rule_repository/mapping/build_mapping.py:146-167, 329-336`；`src/elc_audit_engine/rule_repository/mapping/prompts.py:14, 20, 46`
**問題：**
1. prompt 只給 LLM 每個候選節點**前 100 字**（`_FULL_TEXT_PREVIEW_LEN = 100`），卻要求它回「最相關的一段全文，至多200字」——超出 100 字的部分 LLM 根本看不到，只能編造。
2. `_parse_llm_response` 直接把 `條文位置：` 後的任意字串存為 `article_location`，未檢查它是否等於任一候選節點的 `path`；候選為空（「（無候選節點）」）時 LLM 仍可能回一個看似合理的路徑。
3. 這兩個值寫入 `rule_mapping` 後，`get_rule()` → `comparator._to_check_item()` 以 `article_full_text` 優先於 `payment_text` 作為 `rule_text`，被送進判定器當「健保規則要求」，並在補強敘述與申復草稿中以 `rule_location` 當「出處」引用。等於把二階 LLM 幻覺當作法規原文呈給醫師與健保署。
**修正：** 讓 LLM 只回傳候選「編號」，全文與路徑一律取自實際節點：
```python
# prompts：要求「只回答候選編號（1-5）或 0 表示查無」
m = re.search(r"\b([0-5])\b", response_text or "")
idx = int(m.group(1)) if m else 0
if idx == 0 or idx > len(candidates):
    location, full_text = None, None
else:
    node = candidates[idx - 1]
    location, full_text = node["path"], node["full_text"]   # 原文，非 LLM 摘要
```
既有 `rule_mapping` 中 `article_source='docx'` 的列應全部標記為待重建（`source_version=NULL`）。

### CR-03：半年病史時間窗以「今天」為迄日，而非案件就醫日——會把就醫日「之後」的紀錄當成佐證

**檔案：** `src/elc_audit_engine/record_aggregator/aggregator.py:118`（呼叫端 `server.py:469` 未傳 `end_date`）
**問題：** `window_end = end_date or date.today()`，而 server 以 `build_timeline(provider, record_no)` 呼叫。抽審通常在就醫後數月進行：(a) 就醫日之後的就診／檢驗會落入窗內，被 LLM 判定為「支持」該次醫令——事後紀錄不能證明當次醫療必要性，這會產生不實的「充分」結論與申復理由；(b) 就醫日前半年的真正病史可能已滑出窗外（被計入 `excluded_counts`）。
**修正：** `build_timeline` 的 `end_date` 應改為必填，或由呼叫端傳入 `SubmissionCase.visit_date`（民國 7 碼需先經 `parse_flexible_date`）；另外過濾 `record.date > visit_date` 的紀錄：
```python
visit = date.fromisoformat(parse_flexible_date(case.visit_date))
agg = build_timeline(provider, record_no, end_date=visit)
```
並為「就醫日後紀錄不得入窗」新增測試。

### CR-04：OCR／表格 OCR 以「醫令代碼」全域去重，不同案件（不同病患）使用同一醫令時被靜默丟棄

**檔案：** `src/elc_audit_engine/ingest/table_ocr.py:131-140`；`src/elc_audit_engine/ingest/ocr_rows.py:55-64`
**問題：** 抽樣清單每一列是一個「案件×醫令」，同一醫令代碼（如 00109C 門診診察費）必然在多個案件重複出現。`seen_codes` 只以 `order_code` 為鍵，第 2 筆以後一律被歸入 rejected（原因寫「跨頁/重複表頭」），等於抽樣案件資料遺失。CSV 路徑（`sampling.py`）沒有這個去重，三條攝入管道行為不一致。
**驗證：** 表頭含「流水號／病歷號／醫令代碼」、兩列分別為 (1, A1, 00109C)、(2, B2, 00109C) → 只保留 case_seq=1，第二列被 rejected。
**修正：** 去重鍵改為整列內容（或 `(case_seq, record_no, order_code)`），且只在「該列與表頭列相同」時才視為重複表頭：
```python
key = (rec.case_seq, rec.record_no, rec.order_code, rec.visit_date)
if key in seen: ...
```
OCR 行解析則以整行正規化文字為鍵，而非代碼。

### CR-05：`build_chroma_index` 腳本必定崩潰——引用不存在的設定 `settings.PAYMENT_RULES_CSV` / `DRUG_RULES_CSV`

**檔案：** `src/elc_audit_engine/rule_repository/scripts/build_chroma_index.py:26-31`
**問題：** `config/settings.py` 沒有定義這兩個屬性（全專案 grep 僅此處出現），`main()` 第一個 `if` 就拋 `AttributeError`，與檔頭「non-blocking、exit code 0」的承諾相反，ChromaDB 索引無法重建。沒有任何測試執行此腳本。
**修正：** 重用 `build_sqlite` 的解析函式：
```python
from elc_audit_engine.rule_repository.scripts.build_sqlite import (
    _resolve_payment_csv_path, _resolve_drug_csv_path)
try:
    source_ver = versions.build_source_version(
        _resolve_payment_csv_path(), _resolve_drug_csv_path(), docx_trees_path)
except FileNotFoundError:
    source_ver = None
```
並加一個 smoke 測試（monkeypatch `chroma_store.build_chroma_collection`）。

## Warnings

### WR-01：`_parse_int` 遇到 `1e400`／`inf` 拋未捕捉的 `OverflowError`；小數被靜默截斷、千分位變 None

**檔案：** `src/elc_audit_engine/parsers/deduction.py:106-113`
**問題：** `int(float("inf"))` 拋 `OverflowError`，只捕捉 `ValueError`，會讓整份核減檔解析失敗且不是 `DeductionFileError`（server 端只接 `DeductionFileError`）。`"300.7"` → 300（靜默截斷不予核銷金額，也就是申復值域上界 D-15）；`"1,200"` → None（金額遺失且無警告）。
**修正：** 用 `Decimal` 解析並要求為整數，失敗則拒收該列：
```python
from decimal import Decimal, InvalidOperation
try:
    d = Decimal(stripped.replace(",", ""))
except InvalidOperation:
    return None
if not d.is_finite() or d != d.to_integral_value():
    raise ValueError(f"金額非整數: {value!r}")   # 由呼叫端轉為 RejectedRow
return int(d)
```

### WR-02：`csv.Sniffer` 可能把分隔符誤判為 `;` 或 `\t`，整份檔案每列欄數不符而全部被拒收

**檔案：** `src/elc_audit_engine/parsers/deduction.py:200-205`
**問題：** 欄 16/18 為自由中文，可能含分號或全形標點；Sniffer 對少量列的判斷不穩定，一旦誤判，所有列都進 rejected，但函式仍正常回傳。
**修正：** 依序嘗試 `",", "\t", ";"`，選出「產生 18 欄列數最多」的分隔符；或在偵測結果下 18 欄比例低於門檻時拋 `DeductionFileError`。

### WR-03：SOAP 標記正則把生命徵象行 `P: 88/min`（脈搏）當成 Plan 標記

**檔案：** `src/elc_audit_engine/parsers/soap.py:31-35`
**問題：** `P\s*[:：)）]` 會命中以 `P:` 開頭的脈搏紀錄，導致 O 段的生命徵象被切成 P（計畫）段，連同後續行一併錯置。`A)`、`S)` 在條列式內文中也常見。
**驗證：** `"S: 頭痛\nP: 88/min\n體溫正常"` → `P: ('88/min\n體溫正常',)`。
**修正：** 字母標記要求其後不是數字（`P\s*[:：)）](?!\s*\d)`），或只在標記後跟非數字內容時才視為段落標記；新增生命徵象測試。

### WR-04：關鍵詞路徑以 `.` 斷句，會把小數切斷（`36.5` → `36`／`5 度`）

**檔案：** `src/elc_audit_engine/parsers/soap.py:38`
**問題：** 數值（體溫、檢驗值）被拆成兩句，分類與 evidence 呈現都失真。
**修正：** `re.compile(r"[。！!？?\n]+|\.(?!\d)")`，或只在 `.` 後面接空白或行尾時斷句。

### WR-05：`compare_case` 對醫令代碼為空的醫令靜默略過，未列入任何結果

**檔案：** `src/elc_audit_engine/comparator/comparator.py:94-96`
**問題：** `if not code: continue`——該醫令不出現在 `order_judgments`、`unknown_orders`、`manual_review_orders`，報告上看不出有一筆醫令未被審查。這違反專案自己的「不得靜默產生看似正常的結果」原則。
**修正：** 產生 `OrderJudgment(order_code="", order_seq=order.seq, rule_found=False, note="醫令代碼缺漏，建議人工查核")` 並加入 `unknown_orders`。

### WR-06：規則全文為空時仍送 LLM 判定，產生無意義的 verdict

**檔案：** `src/elc_audit_engine/comparator/comparator.py:44, 111-113`
**問題：** `rule_text = rule.article_full_text or rule.payment_text or ""`；空字串檢核項送進 judger，LLM 仍會回「支持／無記載」，進而分類為充分或裸奔。
**修正：** `if not check_item.rule_text.strip():` 直接給 `Judgment(verdict=VERDICT_MANUAL, reason="規則全文缺漏")`，不呼叫 LLM。

### WR-07：`get_rule` 忽略生效期間與代碼正規化；載入器同碼多版本時以「最後一列」覆蓋

**檔案：** `src/elc_audit_engine/rule_repository/__init__.py:55-84`；`src/elc_audit_engine/rule_repository/loaders/payment_loader.py:33-49`；`drug_loader.py:33-49`；`db.py:11-29`
**問題：** (a) `code TEXT PRIMARY KEY` 只能存一個版本，CSV 若有同碼多個生效區間，`INSERT OR REPLACE` 以檔案最後一列為準，而且回傳的 `len(rows)` 不等於實際列數；(b) `get_rule(code)` 不接受就醫日，無法判斷規則在就醫當日是否有效，已失效或尚未生效的規則照樣被拿來判定；(c) 代碼未 `strip()`／大小寫正規化，XML `p4` 若含空白就會落入「查無規則」。另外新版 CSV 已移除的代碼不會從表中刪除。
**修正：** 主鍵改為 `(code, effective_from)`；`get_rule(code, as_of: date | None)` 以 `effective_from <= as_of AND (effective_to IS NULL OR as_of <= effective_to)` 篩選；查詢前 `code = code.strip().upper()`；載入時先 `DELETE` 再在同一個 transaction 內插入。

### WR-08：`get_rule` 在 DB 不存在時會建立空的 `rules.sqlite3`（副作用），且 docstring 與行為矛盾

**檔案：** `src/elc_audit_engine/rule_repository/__init__.py:34-35, 58`；`src/elc_audit_engine/rule_repository/db.py:56-70`
**問題：** `get_connection` 會 `makedirs` 並由 `sqlite3.connect` 建立空檔；查詢路徑誤設時會在任意位置留下空 DB，後續建置腳本也可能誤以為 DB 已存在。docstring 寫「任何 SQLite 錯誤都降級為查無、絕不拋出」，與實際的 `raise RuleRepositoryError` 相反。
**修正：** 查詢路徑使用唯讀 URI：`sqlite3.connect(f"file:{path}?mode=ro", uri=True)`；把 `get_connection(create=False)` 與建置用的連線分開；更正 docstring。

### WR-09：判定器未驗證 `quote` 確實出自病歷；溫度沿用 0.7，判定不可重現

**檔案：** `src/elc_audit_engine/comparator/judger.py:70, 85`；`src/elc_audit_engine/rule_repository/mapping/llm_client.py:61`；`config/llama_config.json`（`temperature: 0.7`）
**問題：** C1 要求「引用病歷原文」，但 `_to_judgment` 接受任何 quote。LLM 捏造的引文會出現在報告與申復書中。判定與建置都沿用設定檔的 0.7 溫度，同一案件重跑結果不同，金標準回放也不穩定。
**修正：** `verdict in (支持, 部分支持)` 時要求 `quote` 是 evidence 的子字串（去除空白後比對），否則降為 `VERDICT_MANUAL`；`LLMJudger._call` 明確傳入 `temperature=0`。

### WR-10：補強敘述：`bool("false") is True`、C2 提示型前綴未強制、例外靜默吞掉

**檔案：** `src/elc_audit_engine/comparator/narratives.py:88-89, 94-105`
**問題：** (a) LLM 回 `"prompt_only": "false"`（字串）時會被判為 True；(b) C2 規定「無線索時以『若實際有執行，請補充：』開頭」，但 `prompt_only=False` 的敘述沒有檢查是否真的以病歷線索為本，捏造的事實敘述可能直接被醫師採用；(c) `except Exception: return []` 使 LLM 故障與「無候選」無法分辨，報告看起來像「沒有建議」。
**修正：**
```python
po = item.get("prompt_only")
prompt_only = po is True or (isinstance(po, str) and po.strip().lower() == "true")
if not prompt_only and not _has_overlap(text, evidence):   # 或一律強制提示型前綴
    text = "若實際有執行，請補充：" + text; prompt_only = True
```
失敗時回傳一個帶錯誤旗標的結果（或在 `OrderJudgment` 加 `narrative_error`）。

### WR-11：evidence 只取時間軸「最早」的 3 筆就診／檢驗，最相關的近期紀錄被截掉

**檔案：** `src/elc_audit_engine/comparator/evidence.py:43-60`
**問題：** timeline 依日期遞增排序，`[:3]` 取到的是半年前最舊的 3 筆，最接近就醫日的紀錄反而不會送給 LLM。
**修正：** `list(timeline.visits)[-_MAX_ITEMS_PER_CATEGORY:]`（labs/exams/imaging 同樣處理），或依與就醫日的距離排序。另外 `record.unit` 為空時輸出會多一個空白，建議略過。

### WR-12：`_get_bool_or_none` 把字串 `"false"`／`"N"`／`0` 以外的值都判為 True，檢驗會被誤標為「（異常）」

**檔案：** `src/elc_audit_engine/record_aggregator/providers.py:103-107`
**問題：** 雲端 provider 或 HIS 匯出常用字串布林值；`bool("false") == True` 會讓正常檢驗被標成異常，送進判定器形成錯誤佐證。
**修正：** 只接受 `bool`，以及明確的字串集合 `{"true","1","y","yes"}`／`{"false","0","n","no"}`，其他值回 None 或拋 `RecordProviderError`。

### WR-13：增量建置在 `source_version=None` 時會永遠跳過降級列；smoke test 沒有檢查回應內容

**檔案：** `src/elc_audit_engine/rule_repository/mapping/build_mapping.py:221, 244-251`
**問題：** (a) 未提供 CSV 路徑時 `source_version=None`，這時 `existing["source_version"] == source_version` 對所有降級列（寫入時為 NULL）都成立，於是 P1-4 設計的「降級列下次重試」全部失效；(b) `smoke_test()` 只要不拋例外就視為通過，Pitfall 5 描述的 schema 樣板回應（`"content": string`）照樣放行。
**修正：** `incremental and source_version is None` 時直接拋 `ValueError`；跳過條件改為 `existing["source_version"] is not None and ==`；smoke test 回應需 `.strip() == "2"`（或包含 "2" 且不含 `string`）才算通過。

### WR-14：ChromaDB 重建先刪除再新增，失敗時舊索引已被清空；未帶版本時舊內容永遠不會更新

**檔案：** `src/elc_audit_engine/rule_repository/embeddings/chroma_store.py:83, 115-133`
**問題：** (a) 刪除舊資料後才分批 `add`，中途失敗（embedding 下載失敗等）會回報 `skipped`，但舊索引已經不見；(b) `source_version=None` 時不清除，`add` 同 id 在新版 chromadb 會被忽略，內容永遠停在舊版；(c) `open(docx_trees_path)` 在 try 外，缺檔時直接拋例外，違反「絕不拋出」合約。
**修正：** 寫入新 collection（`f"{name}__{version}"`），成功後再切換或刪除舊的；改用 `collection.upsert`；把讀檔也納入 try。

### WR-15：`extract_csv_version` 讀檔失敗時靜默退回只有日期標籤，版本比對失去意義

**檔案：** `src/elc_audit_engine/rule_repository/mapping/versions.py:39-40`
**問題：** `except Exception: return date_tag`——檔案不存在或權限錯誤時仍回傳看似合法的版本，增量建置因此誤判「未換版」。
**修正：** 讀檔失敗直接拋出（建置階段應 fail-fast），不要吞例外。

### WR-16：`build_sqlite` 在有多版 CSV 時以 `glob` 的第一筆（順序不固定）載入

**檔案：** `src/elc_audit_engine/rule_repository/scripts/build_sqlite.py:21, 31`
**問題：** `glob.glob` 不保證順序；來源目錄同時存在新舊版 CSV 時，可能載入舊版規則且沒有任何提示。`build_mapping.__main__` 也共用這兩個函式。
**修正：** 找到多個檔案時直接拋錯要求指定，或依檔名中的版本日期排序取最新，並把實際使用的檔名印出。

### WR-17：docx 標題偵測不支援全形括號「（一）」、`^\d+\.` 會誤判小數或日期；兩種樣式同為深度 6

**檔案：** `src/elc_audit_engine/rule_repository/docx_tree/patterns.py:18-21`
**問題：** 台灣法規文件普遍使用全形「（一）」「（1）」，目前正則只認半形 `\(`，這些條目會併入上一節點的內文；`^\d+\.` 也會命中「1.5 mg…」「113.12.01 修正」之類的內文；`(一)` 與 `1.` 同為深度 6，`1.` 巢狀在 `(一)` 之下時會被當成兄弟節點而彈出，`article_location` 路徑因此錯誤。「第X條」也沒有被辨識為標題。
**修正：** `r"^[\(（][一二三四五六七八九十]+[\)）]"`、`r"^[\(（]\d+[\)）]"`；`^\d+\.(?!\d)`；把 `1.` 設為深度 7、`(1)` 設為深度 8，依次下推。

### WR-18：`convert_doc_files` 未確認輸出檔存在

**檔案：** `src/elc_audit_engine/rule_repository/docx_tree/doc_converter.py:117-130`
**問題：** soffice 已知在另一個實例執行中等情況下會 exit 0 卻不產出檔案；目前直接把預期路徑加入清單，後續 python-docx 才以難以理解的 `PackageNotFoundError` 失敗。
**修正：** `if not os.path.isfile(converted_path): raise RuntimeError(f"soffice 未產出 {converted_path}: {proc.stderr[:200]}")`。

### WR-19：OCR 行解析把任何 5～6 個 ASCII 英數字元的字詞都當作醫令代碼

**檔案：** `src/elc_audit_engine/ingest/ocr_rows.py:24, 52-53`
**問題：** 找不到標準格式代碼時退回 `candidates[0]`，所以「TOTAL」「12345」（金額）「Page1」都會變成記錄。
**驗證：** `"TOTAL 合計 12345"` → 產生 `order_code='TOTAL'` 的記錄。
**修正：** 退路也必須符合健保代碼格式（`\d{5}[A-Z]`、藥品 10 碼 `[A-Z]{1,2}\d{8,9}` 等），其餘列入 rejected，比照 `table_ocr` 的退路處理。

### WR-20：PDF 頁數與影像尺寸沒有上限（DoS 面）

**檔案：** `src/elc_audit_engine/ingest/media.py:79-91, 120-125`
**問題：** 上傳的 PDF 若有數千頁，`pdftoppm -r 200` 會把全部頁面渲染到暫存目錄，再逐頁執行 tesseract（每頁 120 秒逾時），可耗盡磁碟與 worker。
**修正：** 先以 `pdfinfo` 取得頁數並設上限（例如 50 頁），用 `pdftoppm -f 1 -l N`；限制上傳大小。

### WR-21：申報 XML 無宣告時先以 Big5 解碼，可能靜默產生亂碼；`SubmissionParseResult.warnings` 從未填入

**檔案：** `src/elc_audit_engine/parsers/submission_xml.py:30, 114-127, 280`
**問題：** 沒有 encoding 宣告的 UTF-8 檔會先嘗試 big5；實測隨機 1～4 個中文字的 UTF-8 字串約 1.5% 能被 big5 解碼成功（產生亂碼）。小檔或欄位中文少時可能靜默出錯。模型文件說檔層級 warnings 會記錄「編碼回退」，但 `_parse_decoded_text` 永遠回傳 `tuple()`。
**修正：** 沒有宣告時先嘗試 `utf-8`（嚴格解碼，誤判率極低），再試 big5/cp950；實際使用的編碼不同於宣告時寫入 `warnings`。

## Info

### IN-01：XML 解析使用 stdlib `xml.etree`，安全性仰賴執行期 expat 版本

**檔案：** `src/elc_audit_engine/parsers/submission_xml.py:25, 255`
**說明：** 實測 expat 2.6.1 會擋下 billion-laughs，外部實體也不解析；但若部署到舊 Python／系統 expat 就失去保護。建議改用 `defusedxml.ElementTree.fromstring(text, forbid_dtd=True)`（申報 XML 不需要 DTD），並加上 XXE／實體炸彈測試。

### IN-02：`_DECLARATION_FULL_RE` 未錨定行首，會命中 `<?xml-stylesheet …?>`

**檔案：** `src/elc_audit_engine/parsers/submission_xml.py:34, 142`
**說明：** 改為 `^\ufeff?\s*<\?xml\s[^>]*\?>`。

### IN-03：核減明細 `row_number` 為「非空資料列序」，不是檔案行號

**檔案：** `src/elc_audit_engine/parsers/deduction.py:222-226`
**說明：** 空白列被過濾後編號會偏移，使用者難以回到原檔定位。建議記錄 `reader.line_num`。

### IN-04：日期工具未把民國 7 碼 `9991231` 視為無限期哨兵；警告只經 `warnings.warn`

**檔案：** `src/elc_audit_engine/rule_repository/loaders/dates.py:16, 51-63`
**說明：** 藥品 CSV 常用 `9991231` 表示無迄日，目前會被轉成 2910-12-31，與 8 碼 `99991231`→None 的語意不一致。`warnings.warn` 預設每個呼叫位置只顯示一次，大量資料錯誤會被隱藏，建議改用 `logging` 並計數。

### IN-05：SOAP 關鍵詞跨類重疊、單字詞造成誤命中

**檔案：** `src/elc_audit_engine/parsers/soap_keywords.py`
**說明：** 「甲狀腺」同時出現在 objective 與 assessment、「運動」同時出現在 objective 與 plan；「痛」會命中「止痛」、「吐」會命中「吐氣」、`CT` 會命中英文單字中的片段。建議以最長匹配優先或排除子字串重疊。

### IN-06：`table_ocr._get_engine` 失敗不快取，每次都重試 import；並修改全域 `os.environ`

**檔案：** `src/elc_audit_engine/ingest/table_ocr.py:45-58`
**說明：** 建議加上 `_engine_failed` 旗標；cache 路徑改由 `PPStructureV3` 參數傳入，不要修改行程環境變數。

### IN-07：抽樣清單的就醫日期不支援 `115/07/10` 等斜線民國格式

**檔案：** `src/elc_audit_engine/ingest/sampling.py:127-128`
**說明：** server 範例資料即為此格式；目前會發出警告並保留原字串，下游若需 ISO 日期（例如 CR-03 的修正）就無法使用。建議在 `dates.py` 增加 `RRR/MM/DD` 分支。

### IN-08：`load_gold_standard` 遇到非 dict 項目時拋 `AttributeError` 而非 `GoldStandardError`

**檔案：** `src/elc_audit_engine/eval/gold_standard.py:101-102`
**說明：** 迴圈內先檢查 `isinstance(item, dict)`。

### IN-09：`settings` 的 DB_DIR/RAG_DIR/OUTPUT_DIR 不隨 DATA_DIR 覆寫；LLM 位址可經環境變數指向外部

**檔案：** `config/settings.py:11-18`
**說明：** 只覆寫 `DATA_DIR` 時，DB 仍寫到專案目錄。`LLAMA_CPP_BASE_URL` 若設為非本機位址，病歷原文（PHI）會送出本機，違反 D2 紅線。建議啟動時檢查 host 屬於 localhost／私有網段，否則拒絕。

### IN-10：載入器未關閉連線；CSV 缺欄時拋原生 `KeyError`

**檔案：** `src/elc_audit_engine/rule_repository/loaders/payment_loader.py:27-52`；`drug_loader.py:27-52`
**說明：** 使用 `with contextlib.closing(conn), conn:`，並先檢查 `reader.fieldnames` 是否包含所需欄位，缺欄時給出明確訊息。

### IN-11：版本標籤擷取會把檔名中不相鄰的數字串接起來；hash 演算法混用

**檔案：** `src/elc_audit_engine/rule_repository/mapping/versions.py:24-30, 49`
**說明：** `"2-2-7手術251027.csv"` 會得到 `227251` 而非 `251027`；請用 `re.search(r"\d{6}", base)`。sha256 與 sha1 混用，建議統一。

### IN-12：`*.doc` glob 區分大小寫，`.DOC`／`.DOCX` 會被靜默略過（涵蓋率斷言也抓不到）

**檔案：** `src/elc_audit_engine/rule_repository/docx_tree/tree_builder.py:36-41`；`doc_converter.py:108-112`
**說明：** 以 `os.listdir` 搭配 `.lower().endswith()` 過濾。

### IN-13：`CheckItem.rule_source` 混用兩種值域；`llm_client` docstring 已過時

**檔案：** `src/elc_audit_engine/comparator/comparator.py:45`；`src/elc_audit_engine/rule_repository/mapping/llm_client.py:3-4, 73`
**說明：** `article_source`（csv/docx）與 `source`（payment/drug）被放進同一個欄位。llm_client 的 docstring 寫「查詢階段絕不呼叫此模組」，但 judger/narratives 在執行期都會呼叫；另外 `message.content` 可能為 `None`，應 `or ""`。

### IN-14：測試缺口

**說明：** 以下行為目前沒有測試覆蓋（或只覆蓋到正常路徑）：
- SOAP 標記獨佔一行（CR-01）、`P:` 生命徵象（WR-03）、小數斷句（WR-04）
- `build_timeline` 預設 `end_date` 與就醫日後紀錄（CR-03）；evidence 取樣方向（WR-11）
- 同一醫令代碼多個案件的 OCR/表格去重（CR-04）
- `scripts/build_chroma_index.py`、`build_sqlite.py` 完全沒有測試（CR-05、WR-16）
- `build_mapping` 對 LLM 回傳非候選路徑的處理（CR-02）；`incremental` 且 `source_version=None`（WR-13）
- `_parse_int` 的 `inf`／小數／千分位（WR-01）；Sniffer 誤判（WR-02）
- judger 捏造 quote（WR-09）；narratives 的 `"prompt_only": "false"` 字串（WR-10）
- XML 實體炸彈／XXE 回歸測試（IN-01）

---

## 改善建議

1. **LLM 輸出一律「選擇」而非「生成」權威資料**：rule_mapping 只讓 LLM 選候選編號，條文原文與路徑取自語料（CR-02）；判定的 quote 必須是 evidence 的子字串（WR-09）；補強敘述預設為提示型，除非能證明來自既有線索（WR-10）。判定一律使用 `temperature=0`，並在結果中記錄模型、版本與 prompt hash，以便稽核重現。
2. **以「案件就醫日」作為全系統的時間錨點**：`build_timeline(end_date=visit_date)`、`get_rule(code, as_of=visit_date)`、規則表支援多個生效區間（CR-03、WR-07）。在 `SubmissionCase` 提供一個已解析的 `visit_date_iso` 欄位，避免各處自行轉換民國日期。
3. **消除靜默降級**：空醫令代碼、Sniffer 誤判、版本讀檔失敗、narrative 例外、OCR 去重等路徑，都應產生明確的 warning 或 rejected 紀錄（WR-05、WR-02、WR-15、WR-10、CR-04），並在 `SubmissionParseResult.warnings`／`CaseComparisonResult` 中呈現。
4. **建置管線（build-time）要 fail-fast 且具原子性**：腳本以 CI smoke test 執行（CR-05）；CSV 來源版本必須唯一（WR-16）；ChromaDB／SQLite 重建採「寫入新表或新 collection，成功後再切換」（WR-14、WR-07）。
5. **輸入解析的防禦性**：改用 `defusedxml`＋`forbid_dtd`、無宣告時優先嘗試 UTF-8（IN-01、WR-21）；金額改用 `Decimal` 嚴格解析（WR-01）；PDF／影像設定頁數與大小上限（WR-20）；標題正則支援全形括號（WR-17）。

---

_審查時間：2026-09-26T08:47:56Z_
_審查者：Claude (gsd-code-reviewer)_
_深度：deep_
