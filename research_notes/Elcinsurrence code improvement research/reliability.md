# 可靠性、錯誤處理、併發與效能：程式碼閱讀研究筆記

研究範圍：`src/elc_audit_engine/`（pipeline、monthly_audit、sampling_closed_loop、case_store、rule_repository、bridge_queue、audit_log、mailer、api）與根目錄 `server.py`。
方法：純靜態閱讀（未執行測試、未跑基準、未啟動伺服器）。所有引用皆為本地 `檔案:行號`。
標記說明：**[已確認]** 由程式碼直接可見；**[疑似]** 需 runtime 或負載測試才能證實；**[設計意圖]** 程式註解已說明的刻意取捨。

---

## 關鍵問題 1：SQLite 連線是否在所有路徑關閉、交易是否 commit／rollback

### Takeaway
CaseStore 每個方法都是「每次操作新開連線、`finally` 關閉」，關閉路徑完整，寫入交易以 `BEGIN IMMEDIATE` 或 `with conn:` 包覆，例外時會 rollback（[已確認]）。真正的風險在於：(a) 連線未設定 WAL 與 `busy_timeout`，(b) 多個「先讀後寫」流程拆成多個連線、多個交易，中間沒有鎖或版本條件，會產生 lost update。

### Cited Findings
- `get_connection` 只做 `sqlite3.connect(db_path)` 並開啟 `foreign_keys`，沒有 `PRAGMA journal_mode=WAL`、沒有 `busy_timeout`；全 repo 搜尋 `journal_mode`／`busy_timeout` 無結果 — [case_store/db.py:104-119](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/db.py)（連線於 116 行）[已確認]
- 同一資料庫的另一個連線函式 `attachment_store` 有 `timeout=10`，rule_repository 的 `get_connection` 也沒有 — [attachment_store.py:133](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/attachment_store.py)；[rule_repository/db.py:71-85](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/rule_repository/db.py)（連線於 83 行）[已確認]。各模組行為不一致；CaseStore 未設 timeout，因此採 Python 預設值（5 秒）。
- `create()` 與 `advance()` 的交易邊界正確：`BEGIN IMMEDIATE` 放在 `with conn:` 內，SELECT 與 INSERT／UPDATE 同一寫鎖，例外會 rollback — [case_store/store.py:156-195](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/store.py)、[store.py:262-292](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/store.py) [已確認]
- `create()` 只把 `sqlite3.IntegrityError` 轉為 `DuplicateCaseError`；若取得寫鎖逾時，`sqlite3.OperationalError: database is locked` 會直接穿透 — [store.py:189-193](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/store.py) [已確認]（是否在實際負載下發生：[疑似]）
- `update_payload()` 先 `self.get()`（一個連線），再 `UPDATE`（另一個連線，無 `BEGIN IMMEDIATE`，WHERE 也無版本或 state 條件），最後再 `self.get()` — [store.py:512-524](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/store.py) [已確認]。
- 因此 `save_review()` 的「讀整份 payload → 改 `review` 欄位 → 整份覆寫」會 lost update：同案的其他 payload 寫入（例如另一次閉環執行、其他 payload 寫入路徑）若在讀與寫之間發生，會被覆蓋 — [sampling_closed_loop.py:184-189](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/sampling_closed_loop.py) [已確認 code 形狀]；實際衝突機率 [疑似]。
- `set_artifact()` 同樣先 `self.get()` 再寫入 — [store.py:315-333](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/store.py) [已確認]（此方法本身的 UPSERT 是原子的，風險較低）。
- `delete_by_kind()`／`delete_by_batch()` 以 `conn.commit()` 提交，例外時依賴 `close()` 隱式 rollback；功能上正確，但不顯式 — [store.py:568-591](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/store.py) [已確認]，嚴重性低。
- `get_readonly_connection` 使用 `?mode=ro` URI，查詢路徑不會建立空檔 — [rule_repository/db.py:56-68](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/rule_repository/db.py) [已確認]；`get_rule` 在 `finally` 內關閉連線 — [rule_repository/__init__.py:80-115](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/rule_repository/__init__.py) [已確認]。

### Inferences
- 因為所有 close 都在 `finally`，連線洩漏風險低 [推論]。
- 沒有 WAL 時，讀取會與寫入互斥（reader 會被 writer 阻塞）。月批次匯入（每案一次寫入交易）與報告 GET（讀取）同時進行時，報告可能等待寫鎖 [疑似]。
- 無 WAL 且每案一次交易，每次 commit 都需要 fsync；效能影響見關鍵問題 2 [推論]。

### Gaps
- 無法在不執行的前提下確認實際併發下的 `database is locked` 發生率（已依規定不做測試）。
- 未確認 `attachment_store` 的 `timeout=10` 是否為有意設定或僅此處特例。

---

## 關鍵問題 2：N+1 查詢、重複全檔讀取、迴圈內重建索引

### Takeaway
最明顯的問題是「每筆紀錄一個連線＋一個寫入交易」的 N+1 模式：月批次匯入、批次稽核 persist、報告範本載入都屬此類。另有同一 ZIP 被讀兩次，以及 `get_rule` 無任何跨請求快取。沒有發現迴圈內重建索引（索引皆在 `init_schema` 一次建立，[已確認]）。

### Cited Findings
- 月批次匯入：每筆 `store.create()` 會開一個連線、執行 `BEGIN IMMEDIATE`、commit，且 `create()` 結尾又呼叫 `self.get()` 再開一個連線 — [case_store/monthly.py:83-96](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/monthly.py)、[store.py:126-197](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/store.py) [已確認]。`api/cases.py:105-118` 的 `persist_cases` 也是同樣的逐筆 `create` 模式 [已確認]。
- 批次稽核持久化：`audit_batch(persist=True)` 對每案呼叫 `store.set_artifact()`，每案 = 一次 `get()` 連線 + 一次寫入交易 — [monthly_audit.py:644-648](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/monthly_audit.py)、[store.py:315-333](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/store.py) [已確認]。
- 報告範本載入：`load_templates()` 對每個處置／手術醫令目標各呼叫一次 `store.get_soap_template()`，每次一個連線 — [monthly_pregen.py:125-132](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/monthly_pregen.py) [已確認]。報告 GET 每次請求都會執行此流程（[api/routes/monthly.py:160](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/monthly.py)）。
- `pregen_batch()` 先以 `get_soap_template` 檢查快取，`pregen_template()` 又再檢查一次 — [monthly_pregen.py:151](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/monthly_pregen.py)、[monthly_pregen.py:78-79](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/monthly_pregen.py) [已確認]，重複查詢，嚴重性低。
- 規則查詢無快取：`get_rule()` 每次呼叫都開新連線，最多執行 3 次 SELECT（payment_rules → drug_rules → rule_mapping）— [rule_repository/__init__.py:45-118](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/rule_repository/__init__.py)；全 repo 搜尋 `lru_cache` 無結果 [已確認]。月批次內以 per-call dict 快取同碼（[monthly_audit.py:623-635](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/monthly_audit.py)），但每個 HTTP 請求都會重建這個快取。
- 逐醫令規則查詢：`compare_case` 對每個醫令呼叫一次 `lookup(code)`，同案中相同代碼不去重 — [comparator/comparator.py:115-125](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/comparator/comparator.py) [已確認]。
- 管線內迴圈：`run_case_pipeline` 在每筆核減紀錄迴圈內執行 `lookup = rule_lookup or _default_rule_lookup()`（[pipeline.py:224](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/pipeline.py)）；函式本身便宜，但寫法不佳 [已確認]，嚴重性低。
- **同一 ZIP 讀兩次**：`sampling.py` 先呼叫 `inspect_zip_contents(path)`（[sampling.py:655](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/sampling.py)），再呼叫 `parse_totfa_zip(path)`（[sampling.py:656](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/sampling.py)）；`appeal.py:357-358` 相同 [已確認]。
- 批次預審閉環每案都呼叫 `evidence_vault.list_vault_files()`（檔案系統列舉）— [sampling_closed_loop.py:249-252](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/sampling_closed_loop.py) [已確認]；若在批次中逐案執行則為 N 次目錄列舉 [推論]。
- 索引：`idx_cases_state_kind`、`idx_transitions_case`、`idx_cases_batch` 皆於 `init_schema` 一次建立（[case_store/db.py:69-81](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/db.py)）；未發現迴圈內 `CREATE INDEX` [已確認]。
- 索引缺口：`ORDER BY created_at` 的查詢（`list_all`、`list_by_state`）無 `created_at` 索引，需排序匯總的列 [已確認]，影響見橋接佇列段。

### Inferences
- 每案 2～3 個連線與一次 fsync（無 WAL）的 N+1 模式，會使數千筆的批次匯入與 persist 的延遲與案件數近似線性成長 [推論，未實測]。
- 報告 GET 與 email 端點各自重新執行完整稽核與 HTML 渲染，沒有結果快取（[monthly.py:140-172](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/monthly.py)、[monthly.py:175-226](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/monthly.py)）[推論]。

### Gaps
- 未測量實際延遲；N+1 的成本僅為結構推論。
- 未檢查 `record_aggregator/providers.py` 的每次呼叫是否重讀 JSON（僅見 [providers.py:164-165](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/record_aggregator/providers.py) 的 `json.load`，未完整追蹤呼叫頻率）。

---

## 關鍵問題 3：外部呼叫（LLM、HTTP、郵件、OCR、LibreOffice）的 timeout 與錯誤處理

### Takeaway
SMTP、webhook、LibreOffice、ffmpeg／媒體、docx 轉換都有 timeout 且錯誤有轉換（[已確認]）。LLM 呼叫的 timeout 為 180 秒，但沒有 retry、沒有連線重用，且判定與補強逐醫令同步串行執行。同步 HTTP 端點可能因批次 LLM 呼叫而長時間阻塞。少數 bare `except:` 與無 logging 的 `except Exception` 會吞掉錯誤。

### Cited Findings
- LLM 呼叫：`chat_completion()` 每次新建 `requests.Session()`，`timeout=180`，無 retry、無 backoff — [rule_repository/mapping/llm_client.py:101-108](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/rule_repository/mapping/llm_client.py) [已確認]。
- 判定器：`LLMJudger.judge()` 在一個 check item 上最多執行兩次 `_call`（第一次失敗後換措辭重試），每次都是 180 秒上限 — [comparator/judger.py:124-141](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/comparator/judger.py) [已確認]。
- 逐醫令同步串行：`compare_case` 的 `for order in case.orders` 迴圈內依序 lookup、judge，並在弱／裸奔時呼叫 `generate()` 生成補強 — [comparator/comparator.py:115-170](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/comparator/comparator.py) [已確認]；單案最壞 LLM 呼叫數與醫令數成正比，每次最長 180 秒 [推論]。
- 處置範本預生成端點：`/api/monthly/batch/<id>/pregen` 的 `limit` 上限為 50（[api/routes/monthly.py:283-287](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/monthly.py)），`pregen_batch` 在同一請求執行緒中依序呼叫 LLM（[monthly_pregen.py:154-161](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/monthly_pregen.py)）。理論上限 50 × 180 秒 ≈ 2.5 小時的請求阻塞 [已確認 code 路徑；實際觸發機率 疑似]。
- `generate_soap_advice()` 以 `except Exception` 捕獲所有錯誤並回傳 `status="error"`，**未記錄 log**，且把 `str(exc)` 放進回應的 `comparison` 欄位 — [comparator/soap_advice.py:198-205](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/comparator/soap_advice.py) [已確認]。可能的內部錯誤訊息外洩與可觀測性不足。
- `LLMJudger` 的 `except Exception` 同樣未 log，只把類別名寫入 `reason` — [judger.py:141-146](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/comparator/judger.py) [已確認]，屬 C5 降級的刻意設計，但故障無法在 log 中被追蹤。
- SMTP：`timeout=SMTP_TIMEOUT_SECONDS=30`（[mailer.py:28](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/mailer.py)），建立連線處於 `timeout=` 參數中（[mailer.py:96-100](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/mailer.py)）；`SMTPException`、`OSError`、`ValueError` 統一轉為 `MailError` 且不含收件人（[mailer.py:109-110](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/mailer.py)）[已確認]。
- SMTP 寄送為同步：`email_monthly_report` 在請求中完整執行 audit → render → send，沒有 retry 與背景佇列（[api/routes/monthly.py:196-224](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/monthly.py)）[已確認]。
- Webhook：`urlopen(timeout=WEBHOOK_TIMEOUT_SECONDS=10)`，錯誤類別化，不回傳內容 — [api/routes/his_integration.py:57-67](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/his_integration.py) [已確認]。
- LibreOffice：`subprocess.run(..., timeout=120)`，逾時轉 `SofficeConvertError`；每次呼叫使用獨立的 `-env:UserInstallation` profile 目錄，可避免併發時 profile 鎖衝突 — [generators/_soffice.py:38-61](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/generators/_soffice.py) [已確認]。
- LibreOffice 殘留行程：`subprocess.run` 逾時只會終止直接子行程；`soffice` 常以父／子行程形式運作，子行程（soffice.bin）可能殘留 [疑似，需 runtime 驗證]。
- 媒體工具：`_run(...)` 含 `timeout=120` 並轉換 `TimeoutExpired` — [ingest/media.py:57-70](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/ingest/media.py) [已確認]。
- docx 轉換：`doc_converter.py` 有 `timeout=60` 與 `timeout=120`，並在 `(TimeoutExpired, OSError, ImportError)` 時降級 — [rule_repository/docx_tree/doc_converter.py:74-82、123-127](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/rule_repository/docx_tree/doc_converter.py) [已確認]。
- OCR（PaddleOCR）：只見引擎初始化的降級處理（[ingest/table_ocr.py:50-70](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/ingest/table_ocr.py)），未見推論呼叫的逾時機制 [已確認沒有顯式逾時；Gap：推論呼叫本身未讀]。
- **Bare `except:`**（會攔截 `KeyboardInterrupt`／`SystemExit`，且靜默吞掉）：
  - [api/routes/sampling.py:665、671、676](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/sampling.py) [已確認]
  - [api/routes/appeal.py:366、372、377](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/appeal.py) [已確認]
  - 兩處為整段複製貼上的程式碼（同一段 TOTFA 篩選邏輯），維護風險高。
- 其他 `except Exception` 需注意：
  - [rule_repository/embeddings/chroma_store.py:142-146](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/rule_repository/embeddings/chroma_store.py)（註明為 D-09 刻意設計）[設計意圖]
  - [comparator/comparator.py:171](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/comparator/comparator.py)（生成失敗視為「非沒有建議」）[設計意圖]
  - [generators/evidence_packet/builder.py:127](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/generators/evidence_packet/builder.py)、[pdf_exporter.py:49](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/generators/evidence_packet/pdf_exporter.py)（單一附件失敗不阻斷整包）[設計意圖]
  - [monthly_report_html.py:311](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/monthly_report_html.py)、[appeal_linkage.py:94](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/appeal_linkage.py)、[api/routes/printing.py:71、133](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/printing.py)（未逐一閱讀，需補查是否 log）[Gap]
- 清理後重拋的 `except BaseException:` 是正確用法（不吞例外）：[attachment_store.py:233](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/attachment_store.py)、[evidence_vault.py:185、235](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/evidence_vault.py)、[_soffice.py:78](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/generators/_soffice.py) [已確認]。

### Inferences
- LLM 呼叫為全系統最大的延遲與阻塞來源；單一慢速 LLM 會放大到請求層級 [推論]。
- 沒有 LLM 呼叫的並行化或 circuit breaker，LLM 服務下線時每個醫令都要等到 180 秒逾時才降級 [推論，由程式碼形狀得出]。

### Gaps
- 未確認 `llm_client` 的 `LLAMA_CPP_BASE_URL` 在不同部署下的實際逾時是否被覆寫。
- 未讀 `comparator/narratives.py` 的呼叫頻率細節。

---

## 關鍵問題 4：Flask 伺服器的執行緒與全域狀態（是否缺鎖）

### Takeaway
應用程式幾乎沒有模組層可變狀態：CaseStore 經 `app.extensions` 注入、每次操作開新連線，因此跨執行緒是安全的 [已確認]。唯一明確的模組層單例是 PaddleOCR 引擎（`table_ocr._engine`），無鎖。`src/` 內未找到任何 `threading`、`Lock`、執行緒池或背景工作佇列（[已確認]），所有長時間工作都在請求執行緒中同步完成。

### Cited Findings
- 伺服器入口：`server.py:42` 呼叫 `app.run(host, port, debug)`，未顯式指定 `threaded`；依 Flask 慣例預設為多執行緒 [疑似，需對照 Flask 官方文件確認預設值；本次未核對]（[server.py:39-42](/home/hsu/Desktop/Elcinsurrence/server.py)）。
- 無 gunicorn 設定檔（worker／thread 數）於 repo 內可見；`server.py` 文件註解提到 `gunicorn server:app`，實際部署參數未知 [Gap]。
- 請求期服務注入：`Services(case_store=store)` 存於 `app.extensions["elc"]`（[api/app.py:62-63](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/app.py)），`case_store()` 透過 `current_app` 取得（[api/context.py:24-25](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/context.py)）；CaseStore 本身無可變狀態（只有 `db_path`）→ 執行緒安全 [已確認]。
- 模組層可變全域：
  - [ingest/table_ocr.py:45-70](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/ingest/table_ocr.py)：`_engine`、`_engine_failed` 惰性單例，`global` 寫入，**無 `Lock`**。兩個請求同時首次呼叫時，可能重複初始化 PaddleOCR（重型引擎）[已確認無鎖；雙重初始化 [疑似]]。引擎推論是否 thread-safe 未知 [Gap]。
  - [generators/appeal_print/template.py:105](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/generators/appeal_print/template.py)：`_ROW_HEIGHT_MAP_NOTE = {}` 僅讀取（[template.py:145-146](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/generators/appeal_print/template.py)），無寫入路徑 [已確認，非風險]。
  - [rule_repository/__init__.py:19](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/rule_repository/__init__.py)：`_DEFAULT_DB_PATH = None` 無寫入 [已確認，非風險]。
- 無背景工作：月批次上傳同步執行解析、匯入、稽核、HTML 渲染、複製 ZIP、寫檔（[api/routes/monthly.py:79-130](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/monthly.py)）；長時間的 LLM 批次同樣同步（見關鍵問題 3）。
- 上傳流程並非交易式：匯入（`ingest_monthly_declaration`）先寫入案件，稽核與 HTML 渲染後才可能失敗並回 500；重送時 `DuplicateCaseError` 會略過（冪等），因此最終一致，但失敗當下狀態不一致（案件已入庫、報告未產出）[已確認]（[monthly.py:91-116](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/monthly.py)、[case_store/monthly.py:85-96](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/monthly.py)）。
- 同批次併發上傳：`create()` 的 `BEGIN IMMEDIATE` + 存在檢查可防止重複建案 [已確認]。
- 審計 hook：`after_request` 中的 `record_access` 只吞 `OSError` 並寫 application log（[api/security.py:143-158](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/security.py)），其他例外不會被捕獲，但 `record_access` 本身只會拋 `AuditFieldError`（detail 為 None 時不會觸發）[已確認]。

### Inferences
- 目前設計在「單一程序＋多執行緒」下大致安全，主要風險是「同步長任務占用執行緒」與「未同步的 OCR 單例」[推論]。
- 若日後改為多 worker（gunicorn 多程序），模組層狀態是各自獨立的，`table_ocr` 會在每個 worker 各自初始化，而 SQLite 寫入競爭會明顯增加（需 WAL 與 busy_timeout）[推論]。

### Gaps
- 未確認 Flask／Werkzeug 版本的 `threaded` 預設值（需依 pyproject 版本與官方文件核對）。
- 未確認 PaddleOCR 的 `PPStructureV3` 是否 thread-safe。

---

## 關鍵問題 5：大型月批次的無界集合

### Takeaway
月批次稽核會把全部案件的稽核結果保留在單一 list 中才做篩選，記憶體峰值與批次案件數成正比（[已確認]）。分頁只限制了 DB 讀取，沒有限制記憶體。ZIP 檢查端與核減管線也會把全部資料累積在記憶體中。

### Cited Findings
- `audit_batch()` 以 `audits: list[CaseAudit]` 保存每一案（含 findings、evidence、規則全文），迴圈結束後才以 `flagged` 過濾 — [monthly_audit.py:637-656](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/monthly_audit.py) [已確認]。`page_size=500`（[monthly_audit.py:605](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/monthly_audit.py)）只控制 DB 讀取批次，不控制記憶體，因為 `audits` 全部保留 [已確認]。
- 之後 `aggregate_batch()` 與 `render_batch_report_html()` 針對全批次資料工作；HTML 報告是完整字串在記憶體中組裝 [已確認]（[monthly_report_html.py](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/monthly_report_html.py)）。
- JSON 報告端點一次 `jsonify` 整個批次，並對每案執行 `attach_reasoning`，無分頁 — [api/routes/monthly.py:166-172](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/monthly.py) [已確認]。
- 上傳 ZIP 大小有限制：`MAX_TOTFA_UPLOAD_BYTES = 10MB`（[monthly.py:48、63](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/monthly.py)），TOTFA.xml 解壓後有 `MAX_TOTFA_XML_BYTES` 上限（[parsers/totfa.py:80-100](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/parsers/totfa.py)）[已確認]。
- 但 `inspect_zip_contents()` 對 ZIP 內**每個成員**都執行 `zf.read(name)`，不論副檔名，且無單檔或總量上限（[ingest/zip_support.py:70-78](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/ingest/zip_support.py)）[已確認]。高壓縮比的 ZIP（zip bomb）或含大量大型 PDF／圖片的 ZIP 可能使記憶體暴增；此函式被 sampling 與 appeal 上傳路徑呼叫（[sampling.py:655](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/sampling.py)、[appeal.py:357](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/appeal.py)）。實際可利用性 [疑似]。
- 核減管線：`appeal_paths` 與 `appeal_drafts` 隨 `deduction_records` 線性累積（[pipeline.py:213-215、216-265](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/pipeline.py)），且每筆同步寫檔。輸入量有限時可接受 [推論]。
- 橋接佇列：`list_all(kind="bridge", limit=1000)` 讀取固定上限的列，然後在 Python 端過濾（見下節）。
- `CaseStore.list_by_batch` 與 `list_by_state` 具備 `limit`／`offset` 參數（[store.py:365-440](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/store.py)）[已確認]，但月批次稽核把分頁結果全部保留，因此分頁形同虛設 [推論]。

### Gaps
- 未量測實際批次規模（例如每批次幾千案），因此無法判斷記憶體峰值是否會超過部署機器的可用記憶體。
- 未確認 `CaseAudit.to_dict()` 中的 `rule_full_text` 是否於每案重複保存（每案都引用同一規則全文，會造成重複字串）[疑似]。

---

## 關鍵問題 6（補充）：橋接佇列、審計日誌、郵件、以及綜合優先序

### 6-1 橋接佇列（bridge_queue.py）

- 狀態機沒有回收路徑：`PENDING → SENDING → SUCCESS | FAILED`，`SENDING` 只能前進，沒有超時回到 `PENDING` 的轉換 — [bridge_queue.py:31-34](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/bridge_queue.py) [已確認]。地端 Agent 在 `SENDING` 期間當機，該任務會永久停在 `SENDING`，`list_pending` 不會再回傳它 → **訊息遺失風險** [已確認 by state machine；發生頻率 疑似]。
- `FAILED` 為終態，沒有自動重試或重新排隊路徑 — [bridge_queue.py:31-34](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/bridge_queue.py) [已確認]。
- **`list_pending()` 的靜默飢餓**：`store.list_all(kind=BRIDGE_KIND, limit=1000)` 依 `created_at ASC` 取得最舊的 1000 筆 bridge 紀錄，然後在 Python 中過濾 `status == PENDING`（[bridge_queue.py:88-102](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/bridge_queue.py)，取件於 93 行）。當 bridge 紀錄總數（含歷史 `SUCCESS`／`FAILED`）超過 1000，較新的 `PENDING` 任務將**永遠不會出現在查詢結果中**，且沒有錯誤或警告 [已確認 by code；嚴重性：高]。
- 每次輪詢都會反序列化最多 1000 筆 JSON 並在 Python 過濾，成本與歷史總量成正比 — [store.py:398-420](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/store.py) [已確認]。`ORDER BY created_at` 也無對應索引（見關鍵問題 2）。
- `report_status()` 為非原子讀改寫：`get_job()`（[bridge_queue.py:116](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/bridge_queue.py)）→ 檢查轉換 → `update_payload()`（[bridge_queue.py:129](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/bridge_queue.py)，見 [store.py:512-524](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/store.py)）。兩個地端 Agent 若同時讀到 `PENDING` 並同時回報 `SENDING`，兩者都會通過檢查，後者覆寫前者 → **重複傳送風險** [已確認 code 形狀；實際發生 疑似]。
- 沒有 claim（認領）機制：`list_pending` 不會把任務標記為已取出，因此多個 Agent 可同時看到同一 `PENDING` 任務 [已確認]。
- `enqueue_job()` 每次使用新的 `uuid4` 作為 case_id，同一 `target_id` 可重複入列，無去重 [已確認]；可能造成重複送件 [疑似]。
- `report_status()` 只覆寫有值的欄位（`local_id or job.get(...)`，[bridge_queue.py:125-127](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/bridge_queue.py)）[已確認]，這是正確的。

### 6-2 審計日誌（audit_log.py）

- 每次呼叫都以 `open(..., "a")` 附加一行，寫完即關閉；沒有 `flush`／`fsync` 策略 — [audit_log.py:102-109](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/audit_log.py) [已確認]。當機時尾端紀錄可能遺失；若法規要求不可遺失，需評估 [疑似，需依需求判斷]。
- `OSError` 會記錄後重新拋出（[audit_log.py:107-109](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/audit_log.py)），由 `security.py` 的 `after_request` 捕獲並寫 application log，業務回應不受影響 [已確認，設計意圖]。代價是審計遺失時只剩 application log 可追查。
- `read_entries()` 逐行 `json.loads`，沒有容錯；單行損毀會使整個讀取失敗 [已確認]（[audit_log.py:126-131](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/audit_log.py)），嚴重性低。
- 多執行緒同時 append：每行以單次 `write` 寫入，通常足夠，但 Python 緩衝寫入不保證單行原子性 [疑似，嚴重性低]。

### 6-3 郵件（mailer.py）

- 有 30 秒 timeout、TLS 與錯誤統一轉換，且錯誤訊息不含收件人或內容（[mailer.py:28、92-110](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/mailer.py)）[已確認]。
- 沒有 retry、沒有佇列；寄送在請求中同步完成，SMTP 慢速會使 HTTP 請求阻塞最長約 30 秒 × 連線步驟數 [推論]（[api/routes/monthly.py:219-224](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/monthly.py)）。
- 開發模式（未設 `SMTP_HOST`）寫 `.eml` 檔，檔名含微秒時間戳（[mailer.py:113-120](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/mailer.py)）；同一微秒內兩次寫入理論上會覆寫，嚴重性極低 [推論]。

### 6-4 綜合優先序（供報告撰寫者參考，未經實測）

1. **高**：`bridge_queue.list_pending` 的 1000 筆視窗造成靜默飢餓（[bridge_queue.py:88-102](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/bridge_queue.py)）；修正方向為在 SQL 層以 `state`／`status` 過濾並分頁（bridge 的狀態存在 payload JSON 中，需考慮抽出欄位或索引）。
2. **高**：橋接任務無 lease／逾時回收，`SENDING` 卡死即遺失（[bridge_queue.py:31-34](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/bridge_queue.py)）；修正方向為加入 `sent_at` 與逾時回收，以及 FAILED 的重試計數。
3. **高**：`report_status` 與 `update_payload` 缺乏 CAS，重複認領與 lost update（[bridge_queue.py:105-130](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/bridge_queue.py)、[store.py:512-524](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/store.py)、[sampling_closed_loop.py:184-189](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/sampling_closed_loop.py)）；修正方向為 `UPDATE ... WHERE state=? ` 條件更新或 `BEGIN IMMEDIATE` 包覆整個讀改寫。
4. **中高**：SQLite 連線未設 WAL 與 `busy_timeout`（[case_store/db.py:116-118](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/db.py)）；修正方向為 `journal_mode=WAL`、`busy_timeout`，並將連線設定集中於 `get_connection`。
5. **中高**：月批次匯入與 persist 的 N+1（[case_store/monthly.py:83-96](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/monthly.py)、[monthly_audit.py:644-648](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/monthly_audit.py)）；修正方向為批次交易（單一連線、單一 `BEGIN IMMEDIATE`、多列 INSERT）。
6. **中**：LLM 同步串行與 pregen 的 limit=50（[monthly.py:283-299](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/monthly.py)、[monthly_pregen.py:135-162](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/monthly_pregen.py)）；修正方向為背景工作＋進度查詢，或縮小 limit 並加總時限。
7. **中**：`sampling.py` 與 `appeal.py` 的 bare `except:` 及重複程式碼（[sampling.py:665-676](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/sampling.py)、[appeal.py:366-377](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/appeal.py)）；修正方向為改為 `except (TypeError, ValueError)` 並抽成共用函式。
8. **中**：`zip_support.inspect_zip_contents` 無大小上限（[zip_support.py:70-78](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/ingest/zip_support.py)）；修正方向為總解壓量與成員數上限、只讀取需要的成員。
9. **中**：ZIP 被讀兩次（[sampling.py:655-656](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/sampling.py)、[appeal.py:357-358](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/api/routes/appeal.py)）。
10. **中**：`get_rule` 無快取、每次開連線（[rule_repository/__init__.py:80](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/rule_repository/__init__.py)）；修正方向為以 `db_path` 為鍵的程序內快取（規則庫為唯讀，失效條件單純）。
11. **中低**：`audit_batch` 全量保留 `audits`（[monthly_audit.py:637-656](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/monthly_audit.py)）；修正方向為串流篩選（只保留 flagged）並分段輸出報告。
12. **中低**：`table_ocr._get_engine()` 無鎖（[table_ocr.py:50-70](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/ingest/table_ocr.py)）；加 `threading.Lock` 的雙重檢查即可。
13. **低**：`soap_advice`、`judger` 的 `except Exception` 無 log（[soap_advice.py:198-205](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/comparator/soap_advice.py)、[judger.py:141-146](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/comparator/judger.py)）；`soap_advice` 另把 `str(exc)` 回傳給前端，宜改為通用訊息。
14. **低**：審計日誌 durability 與逐行容錯讀取（[audit_log.py:102-131](/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/audit_log.py)）。

### Gaps（整體）
- 所有結論均為靜態閱讀；未執行測試、未跑負載，依研究規定不做基準測試。
- 未讀完的檔案：`sampling.py` 全檔（僅讀取關鍵段落）、`appeal.py` 其餘、`monthly_report_html.py`、`record_aggregator/providers.py` 的呼叫頻率、`evidence_vault.py` 全檔、`generators/appeal_print/*`。
- 未確認 `api/security.py` 的 API key 比對方式（與可靠性無直接關係，未列入範圍）。
- `tests/` 未閱讀；無法判斷既有測試是否涵蓋上述 lost-update 或飢餓情境。
