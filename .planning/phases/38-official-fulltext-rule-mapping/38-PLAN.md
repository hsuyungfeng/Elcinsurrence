# Phase 38 計畫（修訂版 v2）：零 LLM 官方完整給付規定條文建置（`rule_mapping`）、全文展開優化與 `sync_latest_rules` 自動連動

**狀態**：已完成並通過獨立 Claude Plan Checker（PASS）與獨立 Claude Tester（PASS，1,766 passed / 0 failed）驗收
**建立日期**：2026-11-23
**前置依賴**：Phase 37（`d453313`，5,752 碼正式規則基準與四重整表防誤觸上線）

---

## 一、問題根因（實測確認）

使用者於預審報告展開「📜 檢視完整給付規定條文」檢視 `83048C`（頭皮腫瘤）時，僅看到 3 行簡要審查原則且與上方「📜 給付規定（payment_text）」幾乎重複，未能看到完整官方條文。經實測盤點確認三大成因：

1. **`data/db/rules.sqlite3` 的 `rule_mapping` 表目前為 0 筆**：
   - `get_rule()`（`rule_repository/__init__.py:90-93`）與一／二／三階報告皆已支援 `article_full_text` 與 `article_location`，但 `build_sqlite` 與 `sync_latest_rules` 僅寫入 `payment_rules`／`drug_rules`，未建置 `rule_mapping`。
2. **來源 CSV 的條文字段本身遭截斷或遺漏官方備註**：
   - `藥品項查詢項目檔261028AI  摘要支付價大於0.csv` 中有 **2,859 筆**藥品的 `給付規定` 遭截斷於 **303 字**（`...`），但其 `給付規定章節` 欄（共 5,502 筆）可確定性對應至本機官方原檔 `officialdocument/審查注意事項/完整給付規定1140221.odt`（例如第 `7.1.` 節實為 2,767 字、第 `1.2.2.2.` 節實為 831 字）。
   - `醫療服務給付項目支付標準261119已填支付規定.csv` 的 `支付規定` 上限為 400 字且 `payment_loader` 未讀入 **`備註` 欄**（共 2,709 筆有實質官方備註，其中 260 筆原本 `支付規定` 為空）；且本機 `officialdocument/審查注意事項/` 目錄下共有 **21 份 `.docx`**（含各科西醫基層醫療費用審查注意事項與 `2-2-7第二部第二章第七節手術-113.12.01.docx` 等），僅解析這 21 份 `.docx` 即可確定性命中 **2,050 個**醫令碼（含 `83048C` 外科 `(十八)` 與手術節註記、`62010C` 外科 `(十三)(二十三)` 與皮膚科 `(十六)`）。
3. **短文重複顯示與來源出處缺漏**：
   - 當 `payment_text` 本身已很短（如 `83048C` 僅 100 字）時，`summarize_payment_text()` 僅去標題與換項目符號（長度仍達原文 94%），導致上下兩區幾乎重複；且折疊展開區未標示官方條文出處（`article_location`）。

---

## 二、來源範圍界定（明確納入與排除項目）

本機 `officialdocument/審查注意事項/` 共含 33 份官方文件，Phase 38 採**純 Python 標準庫**（`zipfile` + `xml.etree.ElementTree`，不依賴 LibreOffice 執行期轉檔）：

- **納入範圍（Phase 38 實作）**：
  1. **1 份 `.odt`**：`完整給付規定1140221.odt`（對應藥品 CSV `給付規定章節`）。
  2. **全部 21 份 `.docx`**：17 科西醫基層審查注意事項＋一般原則＋附表＋中／牙醫審查注意事項＋`2-2-7第二部第二章第七節手術-113.12.01.docx`（對應 `payment_rules` 醫令碼；單獨 `.docx` 實測命中 2,050 碼）。
  3. **給付項目 CSV `備註` 欄**（如 `261119` 實測 2,709 碼有官方備註）。
- **明確排除範圍（留待後續 Phase）**：
  - 同目錄下 **11 份舊版二進位 `.doc`**（Word 97 格式：`1第一部總則`、`2-2-1檢查`、`2-2-3注射`、`2-2-5精神`、`2-2-9石膏`、`3第三部牙醫`、`5第五部居家照護`、`6-1/6-2論病例計酬`、`7-1/7-2 Tw-DRGs`）以及非條文輔助檔（2 份 `.csv`、2 份 `.ods`、1 份 `.pdf`、1 份 `.xlsx`）不在 Phase 38 解析範圍內（`.doc` 轉檔解析需 LibreOffice headless，列為後續選配增強）。
  - 既有舊版 LLM 批次建置腳本 `mapping/build_mapping.py` 於 Phase 38 後不再作為正式規則同步步驟（無執行期呼叫者）。
- **XML 信任邊界聲明**：本工具以 Python 標準庫 `xml.etree.ElementTree` 僅解析本機受信任之 `officialdocument/` 靜態官方檔案，絕不解析未受信任之使用者上傳 XML（故不涉及外部實體展開攻擊面）。

---

## 三、工作項目與實作設計

### Wave 1：確定性零 LLM 官方條文全文建置器（`build_fulltext_mapping.py`）
1. **新增模組 `src/elc_audit_engine/rule_repository/mapping/build_fulltext_mapping.py`**：
   - **寫入與優先序契約（解決主鍵衝突與既有 mapping 規範）**：
     - 本建置器寫入之 `article_source` 固定標記為 **`"official_fulltext"`**，`source_version` 記錄 `f"official-v1:{sources_hash12}"`（依實際讀取之來源檔 basename、size、mtime 計算 12 碼 SHA-256，具確定性可追溯性）。
     - **優先序**：凡本建置器對某代碼擷取到非空官方全文，一律以 `INSERT OR REPLACE` 寫入（確定性官方原文優先於舊版 LLM `"docx"`／`"csv"` 結果）。
     - **未命中代碼保留策略**：對目標 DB 中存在、但本建置器未命中任何官方來源之代碼，**完全不碰該代碼既有的 `rule_mapping` 列**（絕不執行整表 `DELETE FROM rule_mapping`）。
     - **孤立列清理策略（互斥、無矛盾）**：僅當呼叫端明確傳入 `prune_orphans=True`（對應 `sync_latest_rules(replace=True)` 刪除舊代碼時），才刪除「已不存在於 `payment_rules` 且亦不存在於 `drug_rules`」的孤立 `rule_mapping` 列；凡仍存在於任一主表的代碼皆保留。
   - **來源缺失策略（防洗空保證）**：
     - `official_docs_dir` 預設值為 `None` → 自動解析為 `settings.RULE_SOURCE_DIR`（即 `<PROJECT_ROOT>/officialdocument/審查注意事項`）。
     - 若指定的 `official_docs_dir` 不存在或目錄內無 `.odt`/`.docx`：**採「逐來源合併、保留既有列」策略**——不清除、不覆蓋既有的 `article_source='official_fulltext'` 較豐富列（僅對尚未有 mapping 的代碼補寫 CSV `備註`），並於回傳統計中記錄 `official_docs_available: False` 與 warning，確保**絕不會因缺少官方目錄而把 `rule_mapping` 洗空**。
   - **來源一：藥品官方完整給付規定（`完整給付規定1140221.odt` × 藥品 CSV `給付規定章節`）**：
     - 依文件順序解析 `<text:p>`、`<text:h>` 與 `<table:table>`（附表轉文字行保留，不遺漏表格內容）。
     - 跳過目錄區（自內文 `第1節` 開始），以嚴格章節標題正則 `^(\d+(?:\.\d+)+)(?:\.|(?=\s))`（首段限定 `1..15`，排除 `2.18歲`、`0.5mg` 等內文數值誤判），完整擷取每一章節之全部段落與附表至下一有效章節標題為止。
     - 若 CSV `給付規定章節` 指向父章節（如 `2.8.2.`）而 ODT 僅列子節（`2.8.2.1.`、`2.8.2.2.`…），自動按原文順序彙整該父章節下全部直屬子節原文。
     - 支援單筆藥品對應多章節（空白／逗號／分號分隔，去重保序合併）；每段冠明確出處標題：`【健保藥品給付規定原文｜完整給付規定1140221.odt｜章節 <ch>】`。
     - 若來源藥品 CSV 無 `給付規定章節` 欄或全為空，略過 ODT 解析（零耗時）。
   - **來源二：官方 21 份 `.docx` 審查注意事項與支付標準**：
     - **審查注意事項類**：以頂層項次標記 `^[（(][一二三四五六七八九十百]+[）)]`（並追蹤所屬科別／大標題 `^[一二三四五六七八九十]+、`）將跨段落條文分組為完整條文區塊（例如外科 `(十三)` 含 `1.`、`2.` 全部子項）；凡區塊內出現合法醫令碼（`(?<![A-Za-z0-9])(\d{5}[A-Z])(?![A-Za-z0-9])`），即對應**該整條完整區塊**。
     - **支付標準表格式 `.docx`**（如 `2-2-7第二部第二章第七節手術-113.12.01.docx`）：解析 `<w:tr>` 資料列，首欄為合法醫令碼且項目欄含「註：」或補充說明時，擷取該列完整項目名稱與全部註記。
     - 若目標 DB 中無任何符合 `^\d{5}[A-Z]$` 之 `payment_rules` 代碼，略過 DOCX 解析（加速單元測試並維持完全隔離）。
   - **來源三：給付項目 CSV 官方 `備註` 欄**：
     - 讀取給付項目 CSV 之 `備註` 欄（忽略空白與 `PLACEHOLDER_TEXTS`），補入 `【健保支付標準官方備註｜<csv_basename>】`；若與手術節 `.docx` 內容正規化去空白後重複包含，自動去重。
   - **快取與效能預算**：
     - 針對 `(official_docs_dir, tuple((name, mtime_ns, size)))` 建立行程內唯讀記憶體快取，避免同一 gunicorn worker 重複解析 8.8 MB ODT 與 21 份 DOCX。
     - **效能預算**：冷啟動完整建置（ODT + 21 DOCX + CSV `備註` + SQLite 單一交易寫入）目標 **≤ 15 秒**（實測預估 2–4 秒），熱快取重跑 **≤ 1 秒**，遠低於 `deploy/gunicorn.conf.py:26` 的 300 秒逾時；不需引入非同步背景執行緒，維持單次原子 `os.replace` 交易一致性。
     - **中斷／SIGKILL 復原契約**：建置全程只寫入 `rules.sqlite3.staging.<uuid>`，最後一步才執行單一原子 `os.replace`；即便遭遇極端 `SIGKILL` 強制終止，正式 `data/db/rules.sqlite3` 完好無損，殘留 `.lock` 與 `.staging.*` 依 `docs/CLINIC_SERVER_OPS_QUICKCARD.md` 第 4 節人工核對 PID 後移除即可（程式絕不自動刪鎖檔）。

### Wave 2：改善「📜 檢視完整給付規定條文」顯示（無矛盾規則＋完整向後相容）
1. **`src/elc_audit_engine/services/rule_summary.py`**：
   - 僅調整結構化條列分支（`1. ... 2. ...`）：若 `len(raw) <= 140` 且擷取結果長度 `>= len(raw) * 0.85`（亦即無法實質精簡，如 `83048C` 100 字換項目符號後仍為 94 字），回傳 `None` 避免上下重複。
   - 保留第 2 分支（一般多句文，如 `test_monthly_report_ux.py:57` 之 `"限拇指壓傷或嚴重損傷使用。需檢附術前術後照片"`）與長版結構化文（如 `62010C`）既有行為完全不變。
2. **一／二／三階統一顯示規則（`monthly_audit.py` + `monthly_report_html.py` + `report_renderer.py` + `sampling_service.py` + `api/routes/appeal.py`）**：
   - `OrderFinding` 新增可選欄位 `article_location: str | None = None`（預設 `None`）；`RuleBlock` 新增可選欄位 `location: str | None = None`（預設 `None`）。`evaluate_order()`、`sampling_service.py`、`appeal.py` 對應帶入 `rule.article_location`。
   - **上方區塊（`<div class="rule-payment">`）**：依使用者實測拍板——直接自動展開 **`payment_text` 完整原文**（不經 `summarize_payment_text()` 簡要截斷），標題維持 **`📜 給付規定（payment_text）`**。
   - **折疊展開區（`<details class="rule-fulltext"><summary>📜 檢視完整給付規定條文</summary>`）**：
     - 預設收合（須按下才展開），**僅包含非 `payment_text` 之官方完整條文（`article_full_text`）**，不再重複包含 `payment_text`；若無額外官方完整條文則不輸出空白折疊框。
     - 來源標題標示出處：`官方條文全文（{article_location}）`（無 `article_location` 時維持 `條文全文（article_full_text）`），100% 原始完整文字不截斷，所有動態文字一律經 `html.escape()` 跳脫。
   - **既有測試相容清單（零破壞，全數維持通過）**：
     - `tests/test_monthly_report_ux.py`（L77 `"📜 給付規定（payment_text）"`、L160–167 摘要精簡與短句 `None` 均保持通過）
     - `tests/test_monthly_report_html.py`
     - `tests/test_monthly_sort_fulltext.py`
     - `tests/test_rules_sync.py`、`tests/test_rules_api.py`

### Wave 3：`sync_latest_rules.py` 自動連動＋更新正式規則庫＋測試與文件
1. **`src/elc_audit_engine/rule_repository/scripts/sync_latest_rules.py`**：
   - `sync_latest_rules()` 新增可選參數 `official_docs_dir: str | None = None` 與 `rebuild_fulltext: bool = True`。
   - 於暫存庫（`staging`）完成 `load_drug_csv_full` 與 `load_payment_csv` 後、原子 `os.replace` 之前，若 `rebuild_fulltext=True`，呼叫 `build_fulltext_mapping(staging, payment_csv_path=payment_file, drug_csv_path=drug_file, official_docs_dir=official_docs_dir, prune_orphans=replace)`。
   - `SyncResult` 新增 `rule_mapping_rows: int = 0`（預設 `0` 向後相容，`to_dict()` 一併回報）；`rules_status()` 的 `db` 區塊新增 `rule_mapping_rows`（唯讀查詢，缺表回 `0`）。
2. **更新本機正式 `data/db/rules.sqlite3`（停服原子執行）**：
   - 先核對既有建置前固定快照 `scratch/rules.sqlite3.pinned_5752.bak` 之 SHA-256 與目前 `data/db/rules.sqlite3` 一致（保留不動作為 Phase 37 復原點）→ 停服 `elc-audit-engine.service` → 確認無側車／鎖檔 → 以暫存庫執行 `build_fulltext_mapping` 後原子 `os.replace` 寫入 `data/db/rules.sqlite3`（保留既有的 `5,752` 給付碼與 `11,472` 藥品碼）→ 實測建置耗時、SQL 命中筆數與代表代碼全文 → 另存 Phase 38 建置後固定快照 `scratch/rules.sqlite3.pinned_5752_fulltext.bak` → 重啟 `elc-audit-engine.service` 並確認 `/api/health` 與 `/api/rules/status`。
3. **新增測試 `tests/test_fulltext_rule_mapping.py`**：
   - 合成 ODT（含多層章節、附表、無尾點章節 `1.3.2.6 `、父章節彙整子節、干擾字樣 `2.18歲`）驗證 100% 精準原文與零誤判；
   - 合成審查注意事項 `.docx`（跨段落 `(十三) 1. ... 2. ...`）與支付標準表格 `.docx`（`<w:tr>` 含 `註：`）驗證完整區塊與和 CSV `備註` 去重；
   - 驗證 `official_docs_dir` 缺失時**保留既有 `rule_mapping` 列不被洗空**；
   - 驗證 `sync_latest_rules()` 自動建置 `rule_mapping`、`rules_status()` 回報 `rule_mapping_rows`，以及 `replace=True`（帶 `confirm="REPLACE_RULES"`）時正確清除孤立 mapping 且保留仍在主表的 mapping；
   - 驗證全文渲染路徑**絕不經過 `summarize_payment_text()`**（3,000 字官方全文完整出現於 `<pre class="rule-text">` 且帶 `article_location` 出處標題），且 `83048C` 類 100 字短結構文不於上下重複顯示。
4. **文件同步**：更新 `.planning/STATE.md`、`.planning/ROADMAP.md`、`.planning/.continue-here.md`、`README.md`、`AGENTs.md`。

---

## 四、不變量與安全邊界（`AGENTs.md`）

1. **絕不捏造、區分精簡預覽與完整全文**：`summarize_payment_text()` 僅用於上方精簡預覽區；折疊展開區與 `article_full_text` 100% 原文不截斷、零 LLM 呼叫；所有 HTML 輸出經 `html.escape()`。
2. **保留 5,752 / 11,472 既有代碼與四重 `replace=True` 防護**：不刪除任何既有主表代碼，不削弱 Phase 37 防誤觸護欄，絕不自動刪除 `.lock` 或側車檔。
3. **零 PHI & 測試隔離**：所有新增測試僅使用 `tmp_path` 合成檔案，絕不讀取 `TOTFA.zip` 或寫入正式 `cases.sqlite3`、`rules.sqlite3`、`access.log`。
4. **依賴穩定**：純 Python 標準庫，不更動 `pyproject.toml` / `uv.lock`（維持 `pydantic == 2.13.4`）。

---

## 五、驗收標準（獨立 Claude Plan Checker ＋ Tester）

- [x] 獨立 Claude Plan Checker 複審本修訂版計畫（v2）為 **PASS**。
- [x] `build_fulltext_mapping.py` 實測本機正式 `data/db/rules.sqlite3`：
  - 冷啟動建置耗時 **1.27 秒**（熱快取 **0.53 秒**，遠低於 15 秒預算）；
  - `payment_rules == 5,752`、`drug_rules == 11,472`、字面占位 `0`（原代碼零遺失）；
  - 明確 SQL 計數（`article_full_text IS NOT NULL AND trim(article_full_text) != ''`）：藥品表 JOIN `rule_mapping` 命中 **5,453 筆**（門檻 ≥ 5,450）、給付表 JOIN `rule_mapping` 命中 **2,849 筆**（門檻 ≥ 2,800），總計 **8,302 筆**；
  - 實測 `get_rule("83048C")`（286 字）、`get_rule("62010C")`（610 字）、`get_rule("AC25230100")`（2,805 字）、`get_rule("AB49742100")`（873 字）均回傳完整未截斷之 `article_full_text` 與 `article_location`。
- [x] 一／二／三階報告展開「📜 檢視完整給付規定條文」完整呈現官方全文與出處（測試驗證 3,000 字全文不經 `summarize_payment_text` 截斷），且 `83048C` 短文不上下重複；既有 `test_monthly_report_ux.py` 等全數通過。
- [x] `sync_latest_rules()` 自動連動重建 `rule_mapping`（缺 `official_docs_dir` 時保留既有列不洗空），`/api/rules/status` 回報 `rule_mapping_rows: 8302`。
- [x] `.venv/bin/ruff check .` 零錯誤、全套件 `.venv/bin/pytest -q --no-cov` 實測 **1,766 passed, 3 skipped, 1 deselected, 0 failed**，且測試期間正式 `cases.sqlite3`、`rules.sqlite3`、`access.log` 零測試寫入。
- [x] 獨立 Claude Tester 驗收 **PASS**，待使用者指示是否 commit/push（含更新後零 PHI 之 `data/db/rules.sqlite3`）。
