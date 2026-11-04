# 先堵 PHI 外洩與送審錯誤，再談結構重構

Elcinsurrence 目前最需要處理的是兩類風險：病歷資料的存取控制，以及送審內容與審查狀態的正確性。在 14 條免認證端點中，批次報告寄送端點 `monthly.email_monthly_report` 可在無身分下把全月病歷報告寄到任意信箱，且沒有 CSRF 防護（**已確認**）；前端 `static/index.html` 內另有一組與 `.env` 之 `ELC_API_KEYS` 某把金鑰完全相同的預設字串，首次載入即寫入 localStorage，等同公開金鑰（**已確認**）。送審路徑上，批次抽審 XML 的件數欄位寫死為 1（**已確認**）、批次閉環在 LLM 失敗時仍把案件標為 reviewed（**已確認**）、TOTFA 高風險篩選的條件使風險判斷完全失效（**已確認**，由程式流程推導）。橋接佇列的 1000 筆查詢視窗會讓較新的待送任務永遠查不到，屬靜默丟件（**已確認**）。另有一項必須先查證：`data/TOTFA.zip` 被 git 追蹤，其內容是否為真實病患資料尚未確認。結構與測試缺口則是放大器：三個超過 650 行的模組、多處複製貼上的業務邏輯、沒有 CI、ruff 與 coverage，`doc/tests/` 的約 108 個測試不在預設路徑。認證政策在 progress.md、README.md 與程式碼之間互相矛盾，本報告不替使用者選邊，必須先由使用者裁示。

**證據與方法。** 本報告彙整六份靜態研究筆記（architecture、security、testing、reliability、docs_known_issues、code_review_branch_diff），所有結論都未執行測試。標記沿用筆記原有標籤：已確認、疑似、推論、未確認。研究開始時工作目錄有三個已修改未提交的檔案（`api/routes/appeal.py`、`appeal_linkage.py`、`static/index.html`），且筆記的圖譜基準為 commit 98f5f31c，因此部分行號已位移。我另以 grep 抽查數處關鍵引用：送審件數、`order_name`、閉環 reviewed、橋接 `list_pending` 大致成立；但 TOTFA 條件實際位於 `api/routes/appeal.py:430-432`（筆記記為 :379-380），而豁免清單的定義位於 `api/security.py:34`，筆記部分引用的 `auth.py:34-46` 找不到該定義。本機檔案沒有公開網址，故引用以 `路徑:行號` 表示；code review 的發現附 GitHub 連結（commit 6ea9be6）。

## 免認證端點與預設金鑰，讓病歷資料暴露在可觸及範圍

安全面的核心不是單一漏洞，而是豁免清單與 PHI 政策互相衝突。14 條免認證端點（豁免清單位於 `api/security.py:34-46`，筆記原記為 `auth.py:34-46`）中，最嚴重的是 `monthly.email_monthly_report`：`routes/monthly.py:175-190` 接受 email 參數且無認證，`:194-206` 會渲染完整批次 HTML（含每案 SOAP 與推理）並寄出。全專案未見 CSRF token 或 Origin／Referer 檢查，Flask 的 `request.form` 又接受簡單跨站 POST，因此同一台機器上的瀏覽器只要開啟惡意網頁，就能把 `MONTHLY-YYYYMM` 格式（可猜測）的全月報告寄到攻擊者信箱（**已確認**，H1）。其他寫入端點同樣免認證，包括抽樣匯入、申復匯入、附件上傳與月報上傳（筆記引用 `auth.py:36`、`:38`、`:39`、`:42`）。附件上傳最需注意：`attachments.py:58-87` 允許以唯一的 `case_seq` 查找案件（`attachments.py:33`），等於無身分者可把影像寫入任一案件的佐證（**已確認**，H3）。讀取端點 `monthly.monthly_batch_report`（`routes/monthly.py:140-172`）回傳每案推理樹與 SOAP 清單，也在豁免清單中，與 `auth.py:30-33` 的註解政策相違（**已確認**，M3）。

審計層的問題與此相連。豁免端點的呼叫者一律記為 `anonymous`（`api/security.py:119-127`、`:152`），PHI 存取因此無法歸屬（**已確認**，M2）。審計的 `path` 欄位又會寫入由身分證字號衍生的 vault_key（`api/security.py:149-156`、`evidence_vault.py:25`、`routes/vault.py:20,36,79`），而 `audit_log.py:34-38` 的禁止欄位檢查只看 detail、不看 path，與 audit_log 宣告的零 PHI 原則矛盾（**已確認**，M1）。Werkzeug 的請求行日誌也可能含 vault_key（**疑似**）。

金鑰管理有兩個獨立問題。第一，`.env` 中 `ELC_API_KEYS` 的某把金鑰與前端預設字串完全相同；研究以精確字串比對確認，本報告不輸出金鑰值。`static/index.html:615` 在無輸入時回退到該字串，`:2048` 定義它，首次載入即寫入 localStorage（筆記記為 :612、:2000、:611-613、:2001-2005，行號已位移），因此頁面原始碼即可取得（**已確認**，H2）。`server.py:30-37` 與 `auth.py` 的 fail-fast 只防「未設定」，不防「設成公開值」。第二，`api/security.py:55-56` 的 CSP 含 `'unsafe-inline'`，金鑰又存於 localStorage（`static/index.html:943`），一旦出現 XSS 金鑰即外洩（**已確認**，L2，屬縱深防禦缺口）。`ELC_ALLOW_NO_AUTH_FOR_TESTS=1` 會讓 `api/security.py:92` 的金鑰表變空；依筆記，空表時非豁免端點仍回 401，因此不是立即的全面放行，但旗標名稱誤導、正式啟動也不拒絕，且 `AGENTs.md:86` 的測試指令依賴它（**已確認**，M4，設定風險）。

其餘風險依序為：bridge 的 `target_id` 只檢查非空，即直接嵌入 `download_path`（`bridge_queue.py:47-53`，**已確認**，M5）；LLM 自由文字的 narratives 無引文比對（`comparator/narratives.py:104`、`comparator/comparator.py:170`，**疑似**，M6）；PHI 留存期限未文件化，`monthly.py:108-109` 把 TOTFA.zip 保存到 `data/uploads/`，`sampling_*.json` 含 `patient_name` 欄位（**疑似**，M7）。低風險包括 `safe_paths.py:25` 的 `$` 允許結尾換行（L1）、`errors.py:58-61` 與 `printing.py:134` 記錄完整 traceback（L3）、附件錯誤把第三方例外訊息回傳前端（`attachments.py:82`、`attachment_store.py:70,80,90,98`，L4），以及 `pypdf` 只在 dev 群組（L6）。`rule_repository/scripts/sync_latest_rules.py:111` 的 f-string SQL 因表名來自固定常數而無注入路徑（L7）。

最先要查證的是 `data/TOTFA.zip`。它被 git 追蹤（**已確認**），而 `.gitignore:45-47` 的意圖是排除 XML 與 PHI；zip 內僅含一個 `TOTFA.xml`，大小與根目錄 `TOTFA.xml` 相同（**已確認**）。研究未解開內容，因此無法確認是否為真實病患資料。`tests/test_zip_import.py:38,52` 還會把該檔送進匯入端點。若內容為真，就必須停止追蹤並評估 git 歷史清除。同樣已確認、需修的還有 `config/llama_config.json:3` 的本機絕對路徑仍被追蹤（**已確認**）。

## 送審結果的錯誤直接落在申報檔與審查狀態上

分支 diff（`git diff main...HEAD`，78 檔、+9037／-114）經審查得出五項已驗證發現，加上一項既存缺陷。最嚴重的是批次閉環：[static/index.html#L1638-L1647](https://github.com/hsuyungfeng/Elcinsurrence/blob/6ea9be627ecace63c7cefecb301b14429f7518ed/static/index.html#L1638-L1647) 只以 HTTP 200 判斷成功，並在 `:1646` 設定 `c.state = 'reviewed'`；而 [sampling_closed_loop.py#L73-L88](https://github.com/hsuyungfeng/Elcinsurrence/blob/6ea9be627ecace63c7cefecb301b14429f7518ed/src/elc_audit_engine/sampling_closed_loop.py#L73-L88) 在判定為 None 時回傳「待判定」，端點 `api/routes/sampling.py:232-250` 仍回 200。於是 LLM 逾時的案件會顯示「已審查」。AGENTs.md §2.2 明定 LLM 失敗須轉為 `failed` 而非 `reviewed`；同檔的單案路徑 `sampling.py:560-565` 有處理，批次路徑沒有（**高，已確認**）。

第二項是批次送審 XML。[generators/sampling_xml.py#L136-L146](https://github.com/hsuyungfeng/Elcinsurrence/blob/6ea9be627ecace63c7cefecb301b14429f7518ed/src/elc_audit_engine/generators/sampling_xml.py#L136-L146)（抽查確認於 :142-144）把 `t9`、`t17`、`t37` 寫死為 1。`電子抽審.md:989-993` 把這三欄定義為申請件數，範例值為 633，fixtures 中為 4。單案為 1 是正確的，批次 N≥2 即錯，申報件數與實際 `<ddata>` 數量不符（**高，已確認**）。

第三項是 TOTFA 高風險篩選，它是一個「看似有效、實際失效」的例子。sampling 與 appeal 各有一份幾乎相同的迴圈（`api/routes/sampling.py:656-693`、`api/routes/appeal.py:358-390`），內含 `d39`、點數 `pts >= 350`、單價 `price >= 5.0`、上限 50 與 `seen_cases` 去重。外層 `if (tp > 1000 and (pts >= 350 or price >= 5.0)) or len(records) < 50:`（sampling 在 `:678`，appeal 在 `:430`）於筆數不足 50 時必定為真；內層 `if c.case_seq not in seen_cases and len(records) < 50:`（sampling `:679`，appeal `:431`）又只看去重與筆數。因此風險條件永遠不影響結果，最終等同取檔案順序前 50 個不重複的 `case_seq`，而 `sampling.py:658` 的註解寫的是「取前50筆高風險項」。這是由程式流程推導、未執行驗證的結論，但推導簡單且兩處完全一致，值得以回歸測試確認（**已確認**，靜態推導）。閾值 1000、350、5.0、50 在兩處各寫一次，與 `parsers/totfa.py` 的判斷並存，形成三處來源。兩處還都以 bare `except:` 吞例外（`sampling.py:665,671,676`、`appeal.py:366,372,377`，**已確認**），且 ZIP 被讀取兩次（`sampling.py:655-656`、`appeal.py:357-358`，**已確認**）。

第四項是 SOAP 範本與判定的關係。閉環在 SOAP 缺漏時改用 `soap_templates` 範本餵入比對器（`sampling_closed_loop.py:225-235`；單案路徑 `sampling.py:534`）。[sampling_closed_loop.py#L86-L88](https://github.com/hsuyungfeng/Elcinsurrence/blob/6ea9be627ecace63c7cefecb301b14429f7518ed/src/elc_audit_engine/sampling_closed_loop.py#L86-L88) 只有 `records_degraded` 會把「充分」降為「薄弱」，範本來源時只附加警示文字。範本由 `monthly_pregen.py:99-103` 的 LLM 生成並以 `llm_validated` 寫入快取；生成提示詞要求模型產生「realistic」範本，內含 ICD-10 代碼（`comparator/soap_advice.py:101-103`，此提示在 main 即已存在）。於是範本可能被判為「充分」，違反 AGENTs.md §2.1 要求引文為病歷原文子字串（**中，已確認**）。

第五項是「查無規則」被併入「待判定」。[sampling_closed_loop.py#L163-L176](https://github.com/hsuyungfeng/Elcinsurrence/blob/6ea9be627ecace63c7cefecb301b14429f7518ed/src/elc_audit_engine/sampling_closed_loop.py#L163-L176) 在 rule_found 為 False 時把 level 設為 None，`resolve_support_state` 回傳「待判定」，而 `SUPPORT_STATES` 沒有「查無規則」。AGENTs.md §2.2 要求三種狀態不可混用，因此規則缺漏與服務異常在持久化與批次統計中無法區分（**中，已確認**）。`audit_sampling_case` 的回應欄位 `undetermined` 能區分，但持久化沒有。第六項是統一審查報告的 onclick 注入：[unified_review_report.py#L682-L685](https://github.com/hsuyungfeng/Elcinsurrence/blob/6ea9be627ecace63c7cefecb301b14429f7518ed/src/elc_audit_engine/unified_review_report.py#L682-L685) 把 HTML escape 後的診斷與醫令放入單引號 JavaScript 字串，瀏覽器還原屬性值後即可跳出字串；`primary_diagnosis` 來自匯入檔（`:352`），而 `api/security.py:55-56` 的 CSP 允許 unsafe-inline，故不會被擋（**中，已確認**，需惡意或損毀的匯入資料）。

既存缺陷是 `api/routes/appeal.py:175` 使用未定義的 `order_name`（抽查確認該檔僅此一處出現），`:180-181` 的 `except Exception` 將 NameError 吞掉，使申復草稿的 LLM 建議恆為 None（**已確認**；執行結果為推論）。此問題在 main 上即存在（code review 原記於 `appeal.py:153`）。最後，ZIP 解壓總量只以宣告的 `file_size` 加總（[evidence_vault.py#L221-L234](https://github.com/hsuyungfeng/Elcinsurrence/blob/6ea9be627ecace63c7cefecb301b14429f7518ed/src/elc_audit_engine/evidence_vault.py#L221-L234)），實際寫入沒有累計上限，可超過設計的 200 MB（**低，已確認**，需 API Key）。審查也排除了 `case_seq` 缺漏預設為 "1" 等刻意設計（commit 40b886e），避免誤判。

## 橋接佇列與持久層會靜默丟件，並在併發下覆寫

橋接佇列是可靠性最嚴重的區域。`list_pending` 以 `store.list_all(kind=BRIDGE_KIND, limit=1000)` 取得最舊的 1000 筆，再於 Python 中過濾 `PENDING`（`bridge_queue.py:88-102`，取件於 `:93`；查詢實作於 `case_store/store.py:398-420`）。只要 bridge 紀錄總數（含歷史 SUCCESS 與 FAILED）超過 1000，較新的待送任務就永遠不會出現在結果中，且沒有任何錯誤或警告（**高，已確認**）。`ORDER BY created_at` 也沒有對應索引（`case_store/db.py:69-81` 只建立既有的三個索引），每次輪詢的成本與歷史總量成正比。狀態機沒有回收路徑：`PENDING → SENDING → SUCCESS | FAILED`（`bridge_queue.py:31-34`），地端 Agent 在 SENDING 期間當機，任務就永久卡住，FAILED 也是終態、無重試（**高，已確認**；發生頻率為**疑似**）。沒有 claim 機制，`enqueue_job()` 每次給新的 uuid4，同一 `target_id` 可重複入列（`bridge_queue.py:56-70`，重複送件為**疑似**）。

`report_status()` 是非原子的讀改寫：`get_job()`（`bridge_queue.py:116`）、檢查、再 `update_payload()`（`:129`，見 `store.py:512-524`）。`update_payload` 沒有 `BEGIN IMMEDIATE`，WHERE 也沒有版本或狀態條件，因此兩個 Agent 同時看到 PENDING 時，兩者都可能通過檢查，後者覆寫前者（程式形狀**已確認**，實際重複傳送為**疑似**）。同樣的讀改寫模式也出現在閉環：`sampling_closed_loop.py:184-189` 的 `save_review()` 先讀整份 payload、改 review 欄位、再整份寫回，與其他寫入路徑競爭時會 lost update（程式形狀**已確認**，衝突機率為**疑似**）。`set_artifact()` 的 UPSERT 本身是原子的（`store.py:315-333`），風險較低。

SQLite 層面，`case_store/db.py:104-119` 的 `get_connection` 只開啟 `foreign_keys`，沒有 WAL 與 busy_timeout（`:116-118`）；`attachment_store.py:133` 設了 `timeout=10`，`rule_repository/db.py:71-85` 則沒有，各模組行為不一致（**已確認**）。`create()` 只把 IntegrityError 轉為 DuplicateCaseError，寫鎖逾時的 `database is locked` 會直接穿透（`store.py:189-193`，**已確認**）。批次端點以 `limit=1000` 讀取且不比對總數（`api/routes/sampling.py:140`、`appeal.py:228`、`:307`、`:326`），而 `case_store/store.py:401-403` 的 docstring 明文要求揭露總數，等於違反自己的規範（**已確認**）。

效能問題以結構為主。月批次匯入每案開一次連線與寫入交易，且 `create()` 結尾又開連線讀取（`case_store/monthly.py:83-96`、`store.py:126-197`；`api/cases.py:105-118` 同樣模式）；批次稽核持久化對每案呼叫 `set_artifact`（`monthly_audit.py:644-648`）；範本載入對每個醫令目標各查一次（`monthly_pregen.py:125-132`），報告 GET 每次請求都會重跑（`api/routes/monthly.py:160`）。`get_rule()` 每次開新連線、最多三次 SELECT（`rule_repository/__init__.py:45-118`），全 repo 無 `lru_cache`，逐醫令查詢也不去重（`comparator/comparator.py:115-125`）。N+1 另見於 `api/cases.py:37-43`、`sampling.py:407`、`:724`，以及 `sampling.py:320` 的批次報告（每案重查規則與佐證清單）。這些在數千案時會線性放大（**推論**，未實測）。

外部呼叫與同步長任務構成另一組延遲風險。LLM 的 `chat_completion()` 每次新建 Session、timeout 180 秒，且無 retry 與 backoff（`rule_repository/mapping/llm_client.py:101-108`）；判定器一個醫令最多兩次呼叫（`comparator/judger.py:124-141`）；`compare_case` 逐醫令串行（`comparator/comparator.py:115-170`）。處置範本預生成的 `limit` 上限為 50（`api/routes/monthly.py:283-287`），`pregen_batch` 在同一請求執行緒中依序呼叫（`monthly_pregen.py:154-161`），理論上可阻塞約 2.5 小時（程式路徑**已確認**，觸發機率為**疑似**）。月批次上傳同步完成解析、匯入、稽核、渲染與寫檔（`api/routes/monthly.py:79-130`），上傳也非交易式：案件已入庫而報告未產出時回 500，重送時靠冪等補齊（`monthly.py:91-116`、`case_store/monthly.py:85-96`，**已確認**）。SMTP 寄送同步執行，最長約 30 秒乘以連線步驟數（`mailer.py:28`、`:96-100`、`:109-110`）。LibreOffice 子行程可能殘留（`generators/_soffice.py:38-61`，**疑似**）。相對地，SMTP、webhook（`his_integration.py:57-67`，10 秒）、媒體工具（`ingest/media.py:57-70`）與 docx 轉換（`doc_converter.py:74-82`、`:123-127`）都有 timeout 與錯誤轉換（**已確認**）。

記憶體方面，`audit_batch()` 把全部 `CaseAudit` 保留在 list 中才篩選（`monthly_audit.py:637-656`），`page_size=500`（`:605`）只限制 DB 讀取，分頁形同虛設（**已確認**）。JSON 報告端點一次 jsonify 整批且無分頁（`api/routes/monthly.py:166-172`）。`inspect_zip_contents()` 對 ZIP 每個成員都執行 `zf.read()`，無大小上限（`ingest/zip_support.py:70-78`，被 `sampling.py:655`、`appeal.py:357` 呼叫，**已確認**；可利用性為**疑似**）。執行緒方面，`src/` 內沒有 threading 或背景工作（**已確認**）；`ingest/table_ocr.py:45-70` 的 `_engine` 惰性單例無 Lock（**已確認**；雙重初始化為**疑似**），`:59` 會修改環境變數。`server.py:42` 的 threaded 預設值未核對（**疑似**）。

## 結構與測試缺口讓每次修改都難以被攔截

結構上，業務邏輯大量落在路由層。`api/app.py` 的工廠與 `server.py` 很薄，業務模組也沒有依賴 Flask（只有 `auth.py:25` 例外，**已確認**），分層方向正確，缺的是 service 層。`api/routes/monthly.py:80-130`（上傳）、`:176-226`（寄信，`SMTP_FROM` 讀於 `:205`）、`:229-274`；`sampling.py:506-632`；`appeal.py:90-197`；`his_integration.py:112-242`（regex 萃取於 `:122-130`）與 webhook（`:57-68`，`HIS_WEBHOOK_URL` 讀於 `:266`）都是可搬移的候選。三個大型模組的切分點可直接對應現有區段：`unified_review_report.py`（860 行）的 CSS/JS 位於 `:48-192`，檢視模型 `:203-278`，縮圖 `:281-293`，兩套案件版面 `:584-722`。其中 `:593-722` 的月審風格路徑與 `:589-590` 的 SECTION_ORDER 路徑並存，在月審風格下縮圖路徑可能成為死碼（**推論**）；`monthly_audit.py`（657 行）的規則評估在 `:318-430`、報告納入政策 `:547-595`、批次 `:598-657`；`sampling.py`（752 行）的狀態推進輔助在 `:438-470`，`import_sampling_cases` 在 `:636-752`（內含 `os.remove` 於 `:722`）。`case_store/store.py`（591 行）與 `generators/appeal.py` 的 `build_appeal_draft`（`:370-547`，約 178 行）也偏大。根目錄扁平放置 18 個領域模組，`sampling_*` 與 `monthly_*` 可整理為子套件（**已確認**）。

重複是最明顯的維護成本。第 2、3 階檢視模型幾乎逐行相同（`api/routes/sampling.py:143-194` 的 `_stage2_view` 與 `api/routes/appeal.py:239-286` 的 `_stage3_view`），但 order_code 回退鍵不同（`sampling.py:173` 回退到 target_order_code 與 monthly_source，`appeal.py:265` 只回退 monthly_source），縮圖上限一處用具名常數 `_PREVIEW_THUMB_LIMIT = 24`（`sampling.py:73`），另一處寫死 `[:24]`（`appeal.py:251`）。報告 HTML 在 `unified_review_report.py` 與 `monthly_report_html.py` 之間重複：複製 SOAP 的 JS（`unified_review_report.py:146-175`、`monthly_report_html.py:50-71`）、vault-box CSS（`monthly_report_html.py:43-46`、`unified_review_report.py:138-141`）、案件標題（`monthly_report_html.py:279-301`、`unified_review_report.py:765-794`）、規則全文（`monthly_report_html.py:193-223`、`unified_review_report.py:653-677`）與佐證庫列表（`monthly_report_html.py:304-333`、`unified_review_report.py:603-624`）。ROC 民國日期解析至少散在八處以上（`monthly_audit.py:274-282`；`rule_repository/loaders/dates.py:26,29`；`parsers/totfa.py:117`；`evidence_vault.py:85`；`record_aggregator/providers.py:71`；`generators/sampling_xml.py:31`；`generators/appeal_print/field_mapping.py:66-67,77`；`generators/deduction_print/field_mapping.py:32,46`；`api/records.py:36-41` 與 `sampling_closed_loop.py:273-278`）。SOAP 範本讀寫至少四處，`generate_soap_advice` 有四個呼叫點（`sampling.py:592`、`appeal.py:173`、`his_integration.py:180`，以及經 `comparator/soap_advice.py:162` 的 `monthly_pregen`）。其他重複包括 batch ID 正規式（`sampling.py:359`、`monthly.py:49`）、分頁迴圈（`sampling_sampler.py:86-98`、`monthly_audit.py:639-649`）、串流存檔（`monthly.py:54-67` 上限 10 MB、`rules.py:34-47` 上限 64 MB，而 `api/uploads.py:18` 的 `save_upload` 未被使用）（**已確認**）。

隱性狀態也增加變更風險。`case_store/store.py:18` 與 `:119-120` 在 import 時綁定 `CASES_DB_PATH`，而 `evidence_vault.py:94-95`、`attachment_store.py:126-127`、`rule_repository/__init__.py:27`、`api/records.py:31-32` 則在呼叫時讀取設定，同一套設定有兩種語意（**已確認**）。`api/app.py:31` 預設 `migrate_legacy=True`，工廠內會寫庫（`:70-72`，`api/cases.py:123-157`），而 `app.py:3` 的註解卻宣稱匯入無副作用（**已確認**）。`auth.py:190-215` 的 `require_api_key` 在 src 內無引用（筆記記錄；但本次 grep 在 auth.py 中找不到該定義，需重新定位後再刪除）。業務規則常數散落於 `monthly_audit.py:547`、`:552`、`monthly_report_html.py:75-77`、`:418`、`unified_review_report.py:630`、`sampling.py:678`、`appeal.py:379`（**已確認**）。

測試的問題是看不見的缺口。專案沒有 coverage 設定（`pyproject.toml:44-50` 無 `--cov`，`uv.lock` 無 pytest-cov），以 import 比對估算約 23／103 個非 `__init__` 模組沒有直接測試（**推論**）。分支新增的 `appeal_linkage.py`（212 行）沒有任何直接 import，只被 `tests/test_phase20_stage_batch.py:191`、`:209`、`:249` 透過 API 間接覆蓋；其 `seed=None` 分支（`appeal_linkage.py:35`）、`duplicates` 回報與 RuleRepositoryError 傳遞都缺少定位能力（**已確認**）。`bridge_queue.py` 同樣只透過 `tests/test_bridge_api.py` 間接覆蓋。`api/routes/appeal.py`（450 行）與 `monthly.py`（326 行）沒有直接測試，`sampling.py`（752 行）也沒有 route 級專屬測試檔（**已確認**）。`evidence_vault.py` 的測試較完整（`tests/test_evidence_vault.py`，含 zip 炸彈與路徑穿越），但上限是以 `monkeypatch` 替換 `MAX_ZIP_MEMBERS` 等常數驗證（`:141-142`），而 code review 指出的「實際寫入位元組無上限」是否被覆蓋，未確認。

環境相依測試多數有 skipif，但有三類問題。第一，`tests/test_zip_import.py:38,52` 以相對路徑直接開啟 `data/TOTFA.zip` 且沒有 skip，在非專案根目錄執行會以 FileNotFoundError 失敗（**已確認**）。第二，`tests/test_monthly_reasoning.py:35` 與 `tests/test_totfa_rule_matching.py:46` 依賴約 63 MB 的 `data/db/rules.sqlite3`，缺檔時靜默跳過，乾淨 clone 會讓覆蓋率下降卻不報錯。第三，`tests/test_llama_smoke.py:39-43` 在 decorator 求值時（collection 階段）就做 HTTP 探測，即使被 `live_llm` 排除仍會發出請求，最長等待 3 秒（**已確認**）。`tests/conftest.py:118-141` 的 `_offline_llm` autouse fixture 設計良好。`tests/test_chroma_store.py:119-122` 與 `:176-179` 的 `skipif(True)` 永遠不會執行（**已確認**）。OCR 的 `table_ocr.py:60`（PPStructureV3 匯入）沒有測試，也沒有 importorskip（**已確認**）。LibreOffice 相關測試有 skip（如 `test_doc_converter.py:17`、`test_appeal_print.py:23`），但 CI 不存在，無法確認覆蓋（**已確認**）。

`doc/tests/` 共 26 個檔、約 108 個測試，不在 `pyproject.toml:45` 的 testpaths 內，預設 `pytest` 不會執行；`doc/tests/conftest.py:4` 註解要求另外執行，`AGENTs.md:86` 的指令有包含它（**已確認**）。專案沒有 `.github`、`.pre-commit-config.yaml`、`tox.ini`、`pytest.ini` 或 `Makefile`，也沒有 `[tool.ruff]`；`.ruff_cache/` 存在，代表曾以預設規則執行，而 `.gitignore` 未涵蓋 `.ruff_cache/`、`.pytest_cache/`、`.coverage`、`htmlcov/`（**已確認**）。依賴方面，`pypdf` 只在 dev 群組（`pyproject.toml:31-34`），但 `attachment_store.py:22` 與 `generators/evidence_packet/pdf_exporter.py:4` 在 runtime 頂層匯入，`uv sync --no-dev` 部署會 ImportError（**已確認**，未實際執行）。`Pillow` 完全未宣告，只因 `pillow-heif` 的間接依賴而可用（`attachment_store.py:20`、`generators/evidence_packet/image_processor.py:2`、`unified_review_report.py:283`，**已確認**）。`chromadb>=0.4.0`（`pyproject.toml:15`）範圍極寬，lock 為 1.5.9；OCR 的釘版（`pyproject.toml:24-29`）則是良好做法。測試品質上，沒有完全無 assert 的測試，但 `test_evidence_packet_pdf.py` 與 `test_attachment_store.py` 的 mock 比例偏高（**已確認**），`test_sampling_sampler.py:108` 以 `range(200)` 搜尋會被抽中的 seed，較為脆弱（**已確認**）。

## 四組矛盾需要使用者裁示，不能由研究代選

文件與程式之間的矛盾有十餘處。下表只列需要使用者決定的項目，研究不替任何一方選邊。

| 矛盾 | 來源 A | 來源 B | 需裁示的問題 |
|---|---|---|---|
| 認證政策 | `progress.md:75-76` 寫「2026-08-07 業務端點認證改為選填」；`README.md:114` 與豁免清單一致；`README.md:516`、`:518`、`:520`、`:522` 把四個端點標為選填 | `api/security.py:30-33` 寫「2026-09 部分強制」；`api/security.py:34-46` 的豁免清單不含 `/api/sampling/batch-audit`、`/api/appeal/sample-from-stage2`、`/api/appeal/cases/clear`、`/api/monthly/batch/<id>/clear`，程式為必填；`auth.py:30-33` 註解要求 PHI 讀取端點必填，但清單仍豁免 `monthly_batch_report` 與 `printing.*`（筆記記為 `auth.py:40-44`） | 哪一套為政策？若選必填，文件要改；若選選填，程式要改，並且 H1、H3 是否仍保留為例外。 |
| 豁免清單的檔案位置 | 安全筆記引用 `auth.py:34-46` 為 AUTH_EXEMPT_ENDPOINTS，並引用 `auth.py:190-215` 的 `require_api_key` | 文件筆記與本次 grep 顯示定義於 `api/security.py:34`；`auth.py` 中找不到該清單或 `require_api_key` | 這是事實校正而非政策問題：修改前需先確認實際檔案，避免改錯位置。 |
| W1 狀態轉換 | `.planning/STATE.md:94` 把 `imported→appealed` 列為需清理的非法轉換 | `case_store/states.py:48-51` 註解為 D-01 設計決定，列為合法 | 此邊是否合法？ |
| Phase 21 狀態 | `.planning/ROADMAP.md:40` 寫 0/3 plans | `packagers/nhi_case_packager.py`、`bridge_queue.py`、`api/routes/bridge.py`（docstring 標示 Phase 21-03）已存在 | 是文件落後，還是程式超前？ |
| 閉環是否流轉狀態 | `sampling_closed_loop.py:8`、`:214` 描述「狀態流轉」 | 閉環模組中 `transition`／`advance` 出現 0 次；`sampling.py:560` 只在單案 audit 路徑推進；`sampling_closed_loop.py:11-14` 仍寫 NotImplementedError 佔位，但實際已實作（`:119`、`:205`） | 閉環是否應推進狀態？批次與單案閉環的語意是否要統一？ |
| 測試基線數字 | `deepflash4improve.md:226` 為 277 passed；`:290` 為 374 passed／2 skipped | `progress.md:114` 為 458 passed／2 skipped（2026-08-11）；`.planning/STATE.md:36` 為 363 passed | 無法在靜態閱讀中驗證，需實際執行後以單一來源為準。 |
| 預設測試範圍與旁路 | `AGENTs.md:86` 的測試指令包含 `doc/tests`，且設定 `ELC_ALLOW_NO_AUTH_FOR_TESTS=1` | `pyproject.toml:45` 的 testpaths 只有 `tests`；安全建議移除正式路徑的測試旁路 | 預設 pytest 是否應包含 `doc/tests`？測試旁路應如何改由 conftest 提供？ |
| P0-3 完成度 | `deepflash4improve.md:197-199` 寫「使用者決定暫緩」 | `progress.md:165` 寫已補 `data/output/*`，且 `.gitignore:29-31` 確實已加 | 部分完成：`config/llama_config.json` 絕對路徑仍被追蹤，需由使用者確認優先度。 |
| 被追蹤的資料檔 | `.gitignore:45-47` 的意圖是不讓 XML 與 PHI 入版控 | `git ls-files` 顯示 `data/TOTFA.zip` 被追蹤 | 此 zip 是否應保留？（對應 P0-1） |
| 工具自動允許清單 | `reasonix.toml:2` 的 allow 清單 | 屬工具權限設定，非專案文件 | 是否應保留自動允許 `git push origin main` 與 `rm -rf data/uploads`？ |

另有不需裁示、只需同步的文件落後。`deepflash4improve.md` §7 的 `server.py` 行號已因工廠化而失效，且其中 judger 正則舊記為 `:33`，現為 `:44`（**已確認**）。`AGENTs.md` 的 blueprint 清單缺 bridge、his_integration、rules、vault 四個（**已確認**）。`SUMMARY.md` 其實是 Phase 13-02 的執行摘要，檔名容易被誤認為專案總覽。`progress.md:162` 說已移除 `.planning/HANDOFF.json`，但檔案仍存在（已被 `.gitignore:41` 忽略）。`.planning/STATE.md` 的 frontmatter（current_phase 20）、`:81-84`（v1.1 已完成）與 `:117-121`（尚未開始）彼此矛盾。另外，deepflash 與 progress 所列的多數 P0/P1 項目已在程式中落實，例如 `server.py` 工廠化、`get_rule` 系統性故障改拋 `RuleRepositoryError`（`rule_repository/__init__.py:117-120`）、`parse_flexible_date` 曆法驗證（`rule_repository/loaders/dates.py:49-80`）、`defusedxml` 的 `forbid_dtd=True`（`parsers/submission_xml.py:273`）（**已確認**，依文件與 grep）。仍未解決的包括 `judger` 正則、`DeductionRecord.raw` 的出生日期、病歷號進入 LLM prompt（`comparator/evidence.py:82-83`，本機 LLM，符合 D2 但仍屬 PHI 進入 prompt）、`server.py:28` 無 `app.secret_key`（低優先，**已確認**）、Local Gateway 七元件與 NHI_EIIAPI.DLL 尚未開工（外部條件，非程式待修）。

## 優先序清單：P0 先查證與止血，P1 修正功能，P2 重構與衛生

優先序依 PHI 與送審正確性風險排列，其次為功能正確性與可靠性，最後才是重構。P0 項目大多是小改動、可獨立寫成回歸測試；P0-8 是前提，不完成則 P0-2 與 P1-7 的修法方向無法定案。

| 優先 | 項目 | 主要依據 | 證據狀態 | 理由 |
|---|---|---|---|---|
| P0-1 | 查證 `data/TOTFA.zip` 內容；若為真實病患資料，停止追蹤並評估 git 歷史清除 | git 追蹤狀態；`.gitignore:45-47`；testing 筆記 Q2 | 追蹤已確認，內容未確認 | PHI 可能繞過 `.gitignore` 進入版控，外洩後不可逆 |
| P0-2 | `monthly.email_monthly_report` 移出豁免，並加 Origin 檢查與收件人限制 | `api/security.py:34-46`；`routes/monthly.py:175-206` | 已確認 | 任意收件人加跨站表單即可寄出全月病歷報告 |
| P0-3 | 前端移除硬編碼預設金鑰；確認 `ELC_API_KEYS` 是否已部署，必要時輪換 | `static/index.html:615`、`:2048`、`:2001-2005` | 已確認 | 頁面原始碼即可取得金鑰，等同公開 |
| P0-4 | 批次閉環在 LLM 失敗時改標 failed，不得寫 reviewed | `static/index.html:1638-1647`；`sampling_closed_loop.py:73-88`；`api/routes/sampling.py:232-250` | 已確認 | 違反 AGENTs.md §2.2 |
| P0-5 | 批次 XML 的 `t9`、`t17`、`t37` 改為實際件數 | `generators/sampling_xml.py:136-146` | 已確認 | 申報件數與 `<ddata>` 數不符 |
| P0-6 | 修正 TOTFA 篩選條件並補回歸測試，閾值收斂為具名常數 | `api/routes/sampling.py:656-693`（:678-680）；`api/routes/appeal.py:358-390`（:430-432） | 已確認（靜態推導） | 風險條件實際無作用 |
| P0-7 | 修正 `appeal.py` 的 `order_name` 未定義，且不得被 `except` 靜默吞掉 | `api/routes/appeal.py:175`、`:180-181` | 已確認 | 申復 LLM 建議恆為 None |
| P0-8 | 裁示認證政策，以及閉環狀態與 Phase 21 狀態 | 矛盾表前三列 | 需使用者決定 | 決定 P0-2 與 P1-7 的修法方向 |
| P1-1 | `list_pending` 改在 SQL 層以狀態過濾與分頁，取消 1000 筆視窗 | `bridge_queue.py:88-102`；`case_store/store.py:398-420` | 已確認 | 較新的 PENDING 任務永遠查不到 |
| P1-2 | 橋接加入 lease 逾時回收、FAILED 重試計數與 CAS 條件更新 | `bridge_queue.py:31-34`、`:105-130`；`store.py:512-524` | 已確認（狀態機與程式形狀）；重複傳送為疑似 | SENDING 卡死與重送 |
| P1-3 | `enqueue_job` 對 `target_id` 做 fullmatch 校驗並 URL 編碼 | `bridge_queue.py:47-53`、`:56-70` | 已確認 | 客戶端路徑注入 |
| P1-4 | 統一 SQLite 連線設定（WAL、busy_timeout），集中於 `get_connection` | `case_store/db.py:104-119`（:116-118）；`attachment_store.py:133`；`rule_repository/db.py:71-85` | 已確認 | 併發寫入的鎖競爭 |
| P1-5 | `update_payload`、`save_review` 的讀改寫包進單一交易或加版本條件 | `store.py:512-524`；`sampling_closed_loop.py:184-189` | 已確認（程式形狀） | lost update |
| P1-6 | 審查 `DeductionRecord.raw` 的序列化路徑（API、日誌、審計），遮罩出生日期 | `parsers/models.py:65`、`:95`；`comparator/evidence.py:82-83` | 未解決（文件與程式一致） | 出生日期與病歷號進入序列化或 LLM prompt |
| P1-7 | 審計 `path` 遮罩 vault_key；豁免端點的呼叫者可辨識化 | `api/security.py:119-127`、`:149-156`、`:152`；`audit_log.py:34-38` | 已確認 | 日誌成為新的 PHI 面，且無法歸屬 |
| P1-8 | 修正 judger JSON 解析（非貪婪或改用 `raw_decode`） | `comparator/judger.py:44`、`:57`（舊文件記為 :33） | 已確認 | 判定結果可能被誤解析 |
| P1-9 | 閉環不得以 template SOAP 作為判定依據；「查無規則」獨立為狀態 | `sampling_closed_loop.py:86-88`、`:163-176`、`:225-235`；`monthly_pregen.py:99-103` | 已確認 | 範本被當作病歷引文，狀態混淆 |
| P1-10 | 統一 `limit=1000` 的批次讀取，比對 count 並揭露截斷 | `api/routes/sampling.py:140`；`appeal.py:228`、`:307`、`:326`；`store.py:401-403` | 已確認 | 靜默截斷 |
| P1-11 | 統一規則查詢的 db_path 傳遞與例外策略（只降級 RuleRepositoryError） | `sampling.py:176`、`:182-183`；`appeal.py:124`、`:268`、`:274-275`；`api/cases.py:39`、`:42-43`、`:69`；`pipeline.py:89-132`；`monthly.py:249` | 已確認 | 同一 app 行為不一致，錯誤被掩蓋 |
| P1-12 | 移除各三處的 bare except | `sampling.py:665`、`:671`、`:676`；`appeal.py:366`、`:372`、`:377` | 已確認 | 會吞掉 KeyboardInterrupt |
| P1-13 | 將 `pypdf`、`Pillow` 移入 runtime dependencies | `pyproject.toml:31-34`；`attachment_store.py:20`、`:22`；`pdf_exporter.py:4`；`image_processor.py:2`；`unified_review_report.py:283` | 已確認 | `uv sync --no-dev` 部署會 ImportError |
| P1-14 | 建立最小工具鏈：`[tool.ruff]`、pytest-cov、CI（`uv sync --locked`、pytest、doc/tests、ruff） | `pyproject.toml:44-50`；`uv.lock`；`.github` 不存在 | 已確認 | 無自動化把關 |
| P1-15 | `doc/tests` 納入預設路徑或 CI | `pyproject.toml:45`；`doc/tests/conftest.py:4`；`AGENTs.md:86` | 已確認 | 約 108 個測試被忽略 |
| P1-16 | `test_zip_import.py` 改 fixture 或加 skip；`test_llama_smoke.py` 移出 collection 期探測；`test_chroma_store.py` 的 `skipif(True)` 改為 marker | `tests/test_zip_import.py:38,52`；`tests/test_llama_smoke.py:39-43`；`tests/test_chroma_store.py:119-122`、`:176-179` | 已確認 | 乾淨環境失敗，或誤以為通過 |
| P1-17 | 為 `appeal_linkage.py` 補單元測試（seed=None、duplicates、RuleRepositoryError） | `appeal_linkage.py:35`；`tests/test_phase20_stage_batch.py:191-249` | 已確認（無直接測試） | 回歸定位困難 |
| P1-18 | 修正統一報告的 onclick 注入（改 data 屬性加事件委派，或 `json.dumps`） | `unified_review_report.py:682-685`；`api/security.py:55-56` | 已確認（需惡意匯入資料） | CSP 允許 unsafe-inline，無法被擋 |
| P1-19 | ZIP 解壓加實際位元組上限；`inspect_zip_contents` 加成員數與總量上限 | `evidence_vault.py:221-234`；`ingest/zip_support.py:70-78` | 已確認 | 壓縮炸彈可耗盡磁碟或記憶體 |
| P1-20 | 移除 `config/llama_config.json:3` 的絕對路徑並清查歷史 | `config/llama_config.json:3`；`deepflash4improve.md:129-130` | 已確認 | 公開化前必須處理 |
| P1-21 | 正式啟動時拒絕 `ELC_ALLOW_NO_AUTH_FOR_TESTS`；測試旗標移到 conftest | `api/security.py:82-98`、`:92`；`AGENTs.md:86` | 已確認（設定風險） | 誤設即旁路認證 |
| P1-22 | 確認 `generators/appeal.py` 的 `_split_reason` 是否仍做字元硬切 | `generators/appeal.py:285-287`（舊行號） | 未確認 | 若存在，申復文字會在句中斷開 |
| P1-23 | 確認 `evidence_vault.py:192` 的 basename 寫入是否經 `safe_filename` | `evidence_vault.py:192` | 未確認 | 寫入路徑未驗證 |
| P1-24 | 使用者審視 `reasonix.toml` 的自動允許清單 | `reasonix.toml:2` | 內容已確認；風險判斷需使用者 | 含 `git push origin main`、`rm -rf data/uploads` |
| P2-1 | 拆分 `unified_review_report.py`、`sampling.py`、`monthly_audit.py`，並抽出 service 層 | 架構筆記第 1、3 節 | 規模已確認；切分為推論 | 降低單次修改的影響半徑 |
| P2-2 | 合併 `_stage2_view`／`_stage3_view`、ROC 解析、SOAP service、HTML partial；`_save_stream` 改用 `save_upload`；`_BATCH_RE` 單一來源 | `sampling.py:143-194`、`appeal.py:239-286`；`api/uploads.py:18`；`monthly.py:54-67`；`rules.py:34-47` | 已確認（重複） | 消除回退鍵等分歧 |
| P2-3 | `create_app` 改為注入 Config，`migrate_legacy` 預設改 False，模組統一為呼叫時讀設定 | `api/app.py:27-31`、`:62`、`:70-72`；`store.py:18`、`:119-120` | 已確認 | 測試需 monkeypatch 多處 |
| P2-4 | 確認位置後刪除 `require_api_key` 死碼 | `auth.py:190-215`（需重新定位） | 疑似（位置待確認） | 死碼增加認知負擔 |
| P2-5 | `get_rule` 以 db_path 為鍵做程序內快取；批次寫入改單一交易；N+1 批次化 | `rule_repository/__init__.py:45-118`；`case_store/monthly.py:83-96`；`monthly_audit.py:644-648`；`monthly_pregen.py:125-132` | 結構已確認；效能為推論 | 批次延遲隨案件數線性成長 |
| P2-6 | `audit_batch` 改為串流篩選，只保留 flagged 案件 | `monthly_audit.py:637-656` | 已確認 | 記憶體峰值與批次規模成正比 |
| P2-7 | `table_ocr._get_engine` 加 Lock | `ingest/table_ocr.py:45-70` | 無鎖已確認；雙重初始化為疑似 | 多請求同時首次呼叫 |
| P2-8 | 長時間 LLM 批次改背景工作與進度查詢；pregen 設總時限 | `api/routes/monthly.py:283-299`；`monthly_pregen.py:154-161` | 程式路徑已確認；觸發機率為疑似 | 理論上可阻塞約 2.5 小時 |
| P2-9 | 例外改記錄類別；`soap_advice` 不回傳 `str(exc)` | `comparator/soap_advice.py:198-205`；`judger.py:141-146`；`api/errors.py:58-61`；`printing.py:134` | 已確認 | 可觀測性不足，且 PHI 片段可能進 log |
| P2-10 | 安全衛生：`safe_filename` 改 fullmatch；innerHTML 改 textContent；拆 inline script 後移除 unsafe-inline；附件錯誤改固定訊息；xml.etree 改 defusedxml；`sync_latest_rules` 加表名白名單；失敗認證節流；Werkzeug 日誌遮罩 path | `safe_paths.py:25`；`static/index.html:1622-1624`；`api/security.py:55-56`；`attachments.py:82`；`attachment_store.py:70-98`；`deduction_print/odt_fill.py:66`、`appeal_print/odt_fill.py:264`、`appeal_print/template.py:125`；`sync_latest_rules.py:111` | 已確認（L8 為缺口） | 縱深防禦 |
| P2-11 | 將硬編碼的政策常數集中管理 | `monthly_audit.py:547`、`:552`；`monthly_report_html.py:75-77`、`:418`；`unified_review_report.py:630` | 已確認 | 政策變更需改多處 |
| P2-12 | 修復 `chroma_store` 永久 skip 與文件同步（deepflash §7 行號、AGENTs blueprint、STATE/ROADMAP、SUMMARY.md 更名、HANDOFF.json） | 文件筆記第 3、5 節；`tests/test_chroma_store.py:119-179` | 已確認 | agent 會依過時行號修錯位置 |
| P2-13 | 外部等待條件（非程式待修）：Local Gateway 七元件、NHI_EIIAPI.DLL、doctor-toolbox Provider、官方欄位契約 | `progress.md:69`、`:83-84`、`:121`、`:123`；`.planning/ROADMAP.md:60`、`:79` | 已確認（未開工） | 需先取得外部條件，不應列為近期工作 |

## 結論：先裁示，再以測試把靜態發現變成可重現的失敗

這次盤點最重要的洞察不在於單一漏洞，而在於失敗的處理方式。多數高風險問題都屬於「失敗時靜默」：LLM 失敗被標成已審查、橋接查詢靜默截斷、規則查詢失敗被 `pass` 吞掉、批次端點不揭露 limit、TOTFA 篩選看似存在卻不作用。這些問題指向同一種修法：失敗必須可見，應回 503、標 failed、揭露 count 或拋出例外，而不是由 `except` 或預設值吸收。以此原則處理，P0-4、P0-6、P0-7、P1-10、P1-11 與 P1-12 可以一併收斂。

另一個值得注意的模式是文件多次「修完未回填」。行號、狀態、測試基線與 Phase 狀態都已漂移，且所有結論都未經測試執行。因此建議的順序是：先由使用者完成 P0-8 的認證政策、閉環狀態與 Phase 21 的裁示，並查證 `data/TOTFA.zip`；接著執行一次 `pytest` 與 `pytest doc/tests`，建立可驗證的基線，把靜態發現轉為可重現的失敗測試；最後依 P0 逐項修復，再進入 P1 與 P2 的結構重構。
