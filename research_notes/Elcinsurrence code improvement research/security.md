# 安全與輸入安全性研究（elc-audit-engine）

研究範圍：`/home/hsu/Desktop/Elcinsurrence`（分支 `feat/phase-17-evidence-vault`）
方法：本地讀取程式碼，逐一以 file:line 佐證；未執行服務、未測試工具。`.venv/`、`graphify-out/` 已排除。
`.env` 僅確認變數名稱與「某字串是否存在」，未輸出任何金鑰值。

---

## 一、摘要

| 編號 | 嚴重度 | 狀態 | 主題 |
|---|---|---|---|
| H1 | 高 | 已確認 | 免認證的 `/api/monthly/batch/<id>/email` 可把含 PHI 的批次報告寄到任意信箱；無 CSRF 防護 |
| H2 | 高 | 已確認 | 預設開發金鑰字串同時存在於 `.env` 與 `static/index.html`，頁面自動寫入 localStorage，等同對外公開金鑰 |
| H3 | 高 | 已確認 | 多個 PHI 寫入／上傳端點免 API Key（附件上傳、匯入、列印產出），可在無身分下寫入案件佐證 |
| M1 | 中 | 已確認 | 存取審計的 `path` 欄位含身分證字號（`vault_key`），違反審計 PHI 白名單原則 |
| M2 | 中 | 已確認 | 免認證端點的審計列一律記為 `anonymous`，PHI 存取無法歸屬到呼叫方 |
| M3 | 中 | 已確認 | 免認證的 PHI 讀取端點（批次報告、批次清單）與 `download_output` 的政策自相矛盾 |
| M4 | 中 | 已確認（設定風險） | `ELC_ALLOW_NO_AUTH_FOR_TESTS=1` 可整體關閉認證，只有 log warning，無阻擋 |
| M5 | 中 | 已確認 | `bridge` 的 `target_id` 未校驗即嵌入回傳給地端 Agent 的下載路徑 |
| M6 | 中 | 疑似（未完整讀取） | LLM 自由文字（narratives、soap_advice）無引文比對即進入報告與申復草稿 |
| M7 | 中 | 疑似 | 病歷快照與 TOTFA 原檔長期留存於 `data/uploads/`（PHI 保留政策未見文件化） |
| L1 | 低 | 已確認 | `safe_filename` 以 `^…$` 比對，允許結尾換行字元 |
| L2 | 低 | 已確認 | 前端 CSP 含 `'unsafe-inline'` 的 script-src，且 API Key 存於 localStorage，削弱縱深防禦 |
| L3 | 低 | 已確認 | 未處理例外以 `logger.exception` 記錄完整 traceback，可能含 PHI 片段 |
| L4 | 低 | 已確認 | 附件驗證錯誤把第三方函式庫的例外訊息回傳前端 |
| L5 | 低 | 已確認 | 三處 `xml.etree` 解析內部 ODT 模板（非 defusedxml），來源固定，風險低但不一致 |
| L6 | 低 | 已確認 | `pypdf` 只宣告在 dev 群組，但 runtime 直接 import（部署可能失敗） |
| L7 | 低 | 已確認 | `sync_latest_rules._db_codes` 使用 f-string 組 SQL（表名由固定呼叫端傳入，無注入路徑） |
| L8 | 低 | 已確認 | 無 API Key 暴力嘗試的速率限制（本次未見實作，列為缺口） |

---

## 二、路由認證盤點

認證機制：`api/security.py:108-131` 的 `before_request` 統一強制 `X-API-Key`；豁免清單在 `auth.py:34-46`（`AUTH_EXEMPT_ENDPOINTS`）。**新增端點預設受保護**（符合設計）。豁免的端點仍會寫審計（`security.py:143-159`），但 caller 會記為 `anonymous`（見 M2）。

### 2.1 免認證（豁免）端點，共 14 條

| Endpoint | Method / Path | 檔案:行 | 是否含 PHI | 風險 |
|---|---|---|---|---|
| misc.index | GET `/` | routes/misc.py:21 | 否 | 無 |
| misc.health | GET `/api/health` | routes/misc.py:26 | 否 | 無 |
| static | GET `/static/*` | app.py:47 | 否 | 無 |
| appeal.generate_appeal_draft | POST `/api/appeal/generate` | routes/appeal.py:90 | 是（接收案件內容、回傳草稿） | 中（見 H3、M2） |
| appeal.import_appeal_cases | POST `/api/appeal/import` | routes/appeal.py:342 | 是（寫入核減明細） | **高**（H3） |
| sampling.audit_sampling_case | POST `/api/sampling/audit` | routes/sampling.py:506 | 是（送病歷給 LLM） | 中（M2） |
| sampling.import_sampling_cases | POST `/api/sampling/import` | routes/sampling.py:635 | 是（寫入抽樣案件） | **高**（H3） |
| attachments.upload_appeal_attachment | POST `/api/appeal/attachments/upload` | routes/attachments.py:58 | 是（寫入影像佐證） | **高**（H3） |
| printing.generate_deduction_print | POST `/api/deduction/print` | routes/printing.py:34 | 是（產出含 PHI 的 PDF） | 中（M2、H3） |
| printing.generate_evidence_packet_print | POST `/api/appeal/evidence-packet/print` | routes/printing.py:79 | 是 | 中（M2、H3） |
| monthly.upload_monthly | POST `/api/monthly/upload` | routes/monthly.py:79 | 是（TOTFA 全檔） | **高**（H3） |
| monthly.list_monthly_batches | GET `/api/monthly/batches` | routes/monthly.py:133 | 否（批次計數） | 低（M3） |
| monthly.monthly_batch_report | GET `/api/monthly/batch/<id>/report` | routes/monthly.py:140 | **是**（每案推理樹與 SOAP 清單） | **高**（M3） |
| monthly.email_monthly_report | POST `/api/monthly/batch/<id>/email` | routes/monthly.py:175 | **是**（HTML 報告寄出） | **高**（H1） |

豁免理由註解（auth.py:30-33）寫明「批次讀出 PHI 的端點（案件清單、附件清單、列印產出下載）必須帶 X-API-Key」，但清單實際上仍豁免了 `monthly_batch_report`、`email_monthly_report`、`printing.*`，與註解的政策不一致。

### 2.2 強制認證端點

| Blueprint | Path | 檔案:行 |
|---|---|---|
| appeal | GET `/api/appeal/cases`；POST/DELETE `/api/appeal/cases/clear`；POST `/api/appeal/sample-from-stage2`；GET `/api/appeal/cases/<id>/preview-html`；GET `/api/appeal/batch-report`；GET `/api/appeal/export-batch-xml` | appeal.py:56, 200, 212, 289, 303, 320 |
| attachments | GET `/api/appeal/attachments/<case_ref>`；DELETE `/api/appeal/attachments/<case_ref>/<attachment_id>` | attachments.py:90, 103 |
| bridge | POST `/api/bridge/jobs`；GET `/api/bridge/jobs/pending`；POST `/api/bridge/jobs/<id>/status`；GET `/api/bridge/jobs/<id>` | bridge.py:45, 61, 72, 98 |
| his | POST `/api/his/v1/cases/push`；POST `…/soap-enhance`；POST `…/<case_id>/approve-callback` | his_integration.py:70, 112, 243 |
| misc | GET `/api/output/<name>` | misc.py:32 |
| monthly | POST `/api/monthly/template`；POST `/api/monthly/batch/<id>/pregen`；POST/DELETE `/api/monthly/batches/clear`；POST/DELETE `/api/monthly/batch/<id>/clear` | monthly.py:229, 277, 302, 314 |
| printing | （無，兩條皆豁免） | — |
| rules | POST `/api/rules/upload`；POST `/api/rules/sync` | rules.py:49, 85 |
| sampling | PUT `…/cases/<id>/evidence`；POST `/api/sampling/batch-audit`；POST `…/closed-loop`；GET `/api/sampling/export-batch-xml`；GET `…/export-package`；GET `/api/sampling/batch-report`；GET `…/preview-html`；GET `…/export-xml`；POST/DELETE `/api/sampling/cases/clear`；POST `/api/sampling/sample-batch`；GET `/api/sampling/cases` | sampling.py:112, 197, 232, 253, 275, 315, 330, 342, 372, 384, 432 |
| vault | GET `/api/vault/<vault_key>`；POST `…/upload`；GET `…/files/<category>/<filename>` | vault.py:36, 46, 79 |

---

## 三、關鍵問題的回答

**Q1：所有使用者提供的路徑在檔案系統存取前是否都已校驗？**
大致是，主要路徑有校驗：
- 佐證庫：`vault_key` 以 `fullmatch` 校驗（evidence_vault.py:25, 98-103）；檔名拒絕分隔符與 `..`（:113-127）；讀取時以 `realpath` + `commonpath` 二次確認（:147-153）。
- 附件：`case_seq`／`order_seq`／`case_id` 經 `safe_filename` 白名單（attachment_store.py:200-201）；副檔名必須通過 magic bytes（:60-102）。
- 規則上傳：檔名只看 basename 且通過 fnmatch 樣式（sync_latest_rules.py:44-55）。
- 列印輸出：`download_output` 限定 `.pdf` 並由 `send_from_directory` 做 safe_join（misc.py:39-41）。
- 月報：`batch_id` 以 regex 校驗（monthly.py:49）；TOTFA 的 `batch` 由 `t3` 以 regex 生成（parsers/totfa.py:107-121）。
- 例外：`bridge` 的 `target_id` 只檢查「非空」（bridge_queue.py 約 :62-64），並直接嵌入 `download_path`（:52），見 M5。

**Q2：SQL 是否以 f-string 或字串串接組成？**
- `case_store/store.py` 全部使用 `?` 參數（已逐條檢視 159–584 行的 `execute` 呼叫）；動態條件是在固定的 SQL 字串中選擇，無使用者輸入內插。
- `rule_repository/db.py:128-147` 以白名單 `_ALLOWED_TABLES` 與 `_SELECT_BY_CODE_QUERIES` 字典控制表名，code 以 `?` 傳入。
- `rule_repository/loaders/_csv_table.py:15-25` 的 `_INSERT`／`_DELETE` 為常數字典。
- **唯一的 f-string SQL**：`rule_repository/scripts/sync_latest_rules.py:111` `conn.execute(f"SELECT code FROM {table}")`，`table` 只來自 :175-176 兩個常數呼叫，無注入路徑（L7）。

**Q3：哪些路由缺少認證？**
見第二節。結論：14 條免認證端點，其中 5 條（H1、H3 所列）會接觸或寫入 PHI，應改為強制認證。

**Q4：病患資料是否寫入 log、錯誤頁或未清理的暫存檔？**
- 錯誤頁：未處理例外回傳固定訊息（errors.py:57-61），**沒有**回傳 traceback；`server.py:41` 預設 debug 關閉。良好。
- log：審計 `detail` 有禁止欄位與長度限制（audit_log.py:34、48 起）良好，但 `path` 未受限（M1）。`errors.py:60` 與 `printing.py:134` 以 `logger.exception` 記錄例外（L3）。
- 暫存檔：TOTFA 原檔（monthly.py:118-119）、匯入的 CSV／PDF（sampling.py:721-722、appeal.py:421-423）、ZIP 內 CSV（appeal.py 約 :398-404，`delete=False` 寫入系統 `/tmp`，finally 清除）皆有清理。
- 永久留存：`monthly.py:108-109` 把整份 TOTFA.zip 保留到 `data/uploads/`；`data/uploads/` 已列入 `.gitignore:33`，但其中的 `sampling_*.json` 快照檔含 `patient_name` 欄位（僅計數，未讀內容）（M7）。

**Q5：LLM prompt 的防護是否在每個呼叫點都套用？**
是。`prompt_safety.fence` 與 `DATA_ISOLATION_NOTICE` 在四個 LLM 呼叫點都有套用（詳見第四節表格）。仍需注意 prompt_safety.py:12-16 自己標明的限制：這是降低成功率的緩解，不是保證；真正的邊界是 verdict 白名單與引文校驗。

---

## 四、Prompt 注入防護：呼叫點盤點

| 呼叫點 | 不可信輸入 | fence 標籤 | DATA_ISOLATION_NOTICE | 下游校驗 |
|---|---|---|---|---|
| comparator/judger.py:116-141 | `rule_text`、病歷段落 `evidence` | `rule`、`record`（:127、:129） | 系統提示含（:34、:41） | verdict 白名單（:68-79）；`_verify_quote` 要求引文出現在原文（:82 附近） |
| comparator/narratives.py:87-104 | `rule_location`、`rule_text`、`evidence` | `rule_location`、`rule`、`record`（:96-100） | :33 | **無**引文比對（M6） |
| comparator/soap_advice.py:171-180 | `soap_text`、`patient_history`、`rule_text` | `soap`、`history`、`rule`（:174-176） | :125 | `validate_soap_quality`（由 his_integration 呼叫） |
| rule_repository/mapping/prompts.py:52-59 | `code`、`name`、`category_hint`、`candidates_block`（來自 docx 規則樹） | `code`、`name`、`category_hint`、`candidates`（:53-56） | :17 | build_mapping 後續有 spotcheck（未深入） |
| llm_client.smoke_test（llm_client.py:124-125） | 無（固定字串） | 不需要 | 不需要 | — |

另：`llm_client.py:43` `assert_local_llm_url` 確保病歷不送到非私有網段（D2 紅線），良好。
缺口：未逐行確認 `monthly_pregen.py` 是否直接經 `soap_advice` 呼叫（推論為是，未讀全文）。

---

## 五、詳細發現

### H1（高，已確認）免認證端點可把含 PHI 的報告寄到任意信箱，且可被跨站表單觸發
- 證據：
  - `auth.py:45` 將 `monthly.email_monthly_report` 列入 `AUTH_EXEMPT_ENDPOINTS`。
  - `routes/monthly.py:175-190` 接受 JSON 或表單的 `email`，無認證即可執行；`:194-206` 渲染完整批次 HTML 報告（含每案 SOAP 與推理）並 `build_report_email(to=email, ...)`。
  - 全專案 `grep` 未見 CSRF token、`Origin`／`Referer` 檢查（`security.py` 僅設定 CSP／X-Frame-Options 等回應標頭）。Flask 的 `request.form` 也接受 `application/x-www-form-urlencoded` 的簡單跨站 POST。
- 影響：只要本機瀏覽器（同一台機器的員工）開啟惡意網頁，即可跨站 POST 到 `http://127.0.0.1:5000/api/monthly/batch/MONTHLY-YYYYMM/email` 把全月病歷報告寄到攻擊者信箱。`batch_id` 為 `MONTHLY-YYYYMM` 可猜測。
- 建議：移出豁免清單，改強制 `X-API-Key`；收件人白名單或以設定檔限定；對所有非 GET 的豁免端點加上 `Origin` 檢查或 `Content-Type: application/json` 強制。

### H2（高，已確認）預設開發金鑰同時存在於 `.env` 與前端，並自動寫入瀏覽器
- 證據：
  - `.env`（未入版控，`.gitignore:20`）的 `ELC_API_KEYS` 內含一組 key，其字串與 `static/index.html:612` 與 `:2000` 的 `dev_api_key_for_local_development_1234567890abcdef` **完全相同**（以精確字串比對確認；金鑰值未輸出）。
  - `static/index.html:611-613` `getApiKey()` 在無輸入時回退到此字串；`:2001-2005` 在首次載入時把它寫入 `localStorage('elc_api_key')`。
- 影響：任何能連到此頁面的人都會拿到這把金鑰（頁面原始碼即可讀到）；`ELC_API_KEYS` 形同對外公開。若將 `.env` 的設定用於部署，認證實質失效。`server.py:30-37` 與 `auth.py` 的 fail-fast 只防「沒設定」，不防「設定成公開值」。
- 建議：前端移除硬編碼預設金鑰，改為未設定時要求輸入；`load_api_keys` 增加「拒絕已知弱值／與前端預設相同值」的檢查；文件要求部署前輪換金鑰。

### H3（高，已確認）多個寫入與上傳端點免認證，可在無身分下寫入 PHI 或佐證
- 證據：`auth.py:36`（`sampling.import_sampling_cases`）、`:38`（`appeal.import_appeal_cases`）、`:39`（`attachments.upload_appeal_attachment`）、`:42`（`monthly.upload_monthly`）。
- 特別是 `attachments.py:58-87`：免認證即可把影像寫入任一案件（`resolve_attachment_case` 允許以唯一的 `case_seq` 查找，attachments.py:33）。附件會被佐證包與報告讀取（`attachments.py:90-100` 的清單、`unified_review_report.py` 的佐證區塊）；是否直接併入送審資料夾（`sampling.py:275` `export-package` 註解提及「送審 XML＋佐證庫檔案」）本次未逐行確認。
- 影響：完整性風險（偽造或污染佐證），且無法追溯呼叫方（M2）。
- 建議：全部移出豁免，或至少附件上傳與匯入強制認證；`attachments` 上傳需同時驗證 `case_id`（不接受 `case_seq` 模糊對應）。

### M1（中，已確認）審計日誌的 `path` 欄位會寫入身分證字號
- 證據：`api/security.py:149-156` `audit_log.record_access(..., path=request.path, ...)`；`evidence_vault.py:25` 的 `vault_key` 格式為「身分證字號-年月」（如 `A123625499-2605`）；`routes/vault.py:20` 與 `:36`、`:79` 把它放在 URL path 中。
- `audit_log.py:34-38` 的 `_FORBIDDEN_KEYS` 只檢查 `detail` 的鍵，不檢查 `path`。
- 影響：與 audit_log.py 模組 docstring 宣告的「零 PHI」矛盾；日誌檔成為新的洩漏面。
- 另（疑似）：`server.py` 以 `app.run` 啟動，Werkzeug 預設會把完整請求行寫到 stderr，同樣包含 vault_key（本次未見日誌設定覆寫）。
- 建議：審計寫入前把 `path` 中符合 `vault_key` 格式的段落遮罩（例如以 hash 或 `[vault]` 取代）；Werkzeug 日誌改為不含 path 或在部署層處理。

### M2（中，已確認）免認證端點的審計列一律為 `anonymous`
- 證據：`security.py:119-127` 在豁免端點只在「有帶合法 key」時才設定 `g.caller_id`；`security.py:152` `getattr(g, "caller_id", "anonymous")`。
- 影響：`monthly.email_monthly_report`、`monthly.monthly_batch_report` 等 PHI 存取不可歸屬，違反 auth.py:26-28 設計意圖（審計必留、且應可辨識呼叫方）。
- 建議：隨 H1、H3 一併處理（移出豁免即自然解決）；或為豁免端點要求可選的 `X-Caller-Id` 並記錄 IP。

### M3（中，已確認）PHI 讀取端點免認證，與註解政策矛盾
- 證據：`auth.py:30-33` 註解：「批次讀出 PHI 的端點（案件清單、附件清單、列印產出下載）必須帶 X-API-Key」。但 `auth.py:43-44` 豁免了 `monthly.list_monthly_batches` 與 `monthly.monthly_batch_report`，後者回傳「每案推理樹與 SOAP 清單」（`routes/monthly.py:142`）。`printing.*`（`auth.py:40-41`）產出的 PDF 也是免認證下載，而 `download_output` 卻要求認證（misc.py:36-37）。
- 建議：依註解政策修正清單；讓豁免理由與清單同步，並加入測試保證。

### M4（中，已確認，設定風險）`ELC_ALLOW_NO_AUTH_FOR_TESTS=1` 會關閉整個服務的認證
- 證據：`api/security.py:82-98`（`load_api_keys_or_fail`）。設此旗標時 `ELC_API_KEYS` 會成為空表。依 `resolve_caller` 的實作（空表時對任何 key 都拋 `AuthenticationError`），非豁免的業務端點實際上會全部回 401，因此並非「全部放行」。風險主要在於旗標名稱與 log 語意具誤導性，且若日後 `resolve_caller` 對空表的處理改變，就會變成真正的認證繞過。
- 建議：旗標僅應在測試環境設定；`server.py` 啟動時若偵測到此旗標應直接拒絕啟動，或把空表改為明確的啟動錯誤。
- 註：`tests/conftest.py:18` 的測試金鑰為測試用途，已確認不在正式設定中。

### M5（中，已確認）`bridge` 的 `target_id` 未校驗即嵌入下載路徑
- 證據：`bridge_queue.py:47-53` `download_path` 對 `s_type_code == "00"` 直接回傳 `f"/api/sampling/cases/{target_id}/export-package"`；`enqueue_job`（約 :56-70）只檢查 `target` 非空，未限制字元。
- 影響：地端 Agent 以 API Key 依此路徑下載（`bridge.py:61` 註解），`target_id` 含 `../` 或 `?` 會讓 Agent 請求非預期路徑（客戶端路徑注入）。需具備 API Key 才能建立任務，故風險為中。
- 建議：對 `target_id` 以 `safe_filename` 或 `fullmatch` 校驗；`download_path` 以 `quote(target_id, safe="")` 編碼。

### M6（中，疑似）LLM 自由文字未經引文比對即進入報告與申復草稿
- 證據：`comparator/comparator.py:170` `narratives = generate(check_item, evidence, support_level)`；`comparator/narratives.py:104` `chat_completion(...)` 的回應直接成為候選補強文字。judger 有 `_verify_quote`，但 narratives 與 soap_advice（僅有 `validate_soap_quality`）是否有等效的內容比對，本次未完整讀取全文，因此列為疑似。
- 影響：prompt injection 的效果不會造成 HTML 注入（報告以 `escape` 輸出，見 unified_review_report.py 多處與 monthly_report_html.py:150），但可能使申復草稿內容偏離事實。依 D2 原則應由人工審核。
- 建議：對 narratives 的輸出做 verdict 與引文比對，或在 UI 標示「LLM 生成，需人工核對」。

### M7（中，疑似）PHI 留存政策未見文件化
- 證據：`monthly.py:108-109` 永久保存 TOTFA.zip；`data/uploads/sampling_*.json` 含 `patient_name` 欄位（計數確認）；`data/output/` 保存報告 HTML。
- 建議：在 `.env.example`／文件中定義保留期限與清理指令；`/api/output` 之外的 HTML 不應被服務直接讀取（目前未見直接路由，良好）。

### L1（低，已確認）`safe_filename` 允許結尾換行
- 證據：`safe_paths.py:25` `_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9_\-㐀-䶿一-鿿]+$")`，以 `re.match`；Python 的 `$` 會匹配字串結尾前的換行，故 `"A1\n"` 會通過。
- 影響：可產生含換行字元的目錄或檔名，非路徑穿越（`/`、`.`、`\` 仍被拒絕），影響低。依 Python 正規表示式語意判斷，未實際執行驗證。
- 建議：改用 `re.fullmatch` 或 `\Z`。

### L2（低，已確認）CSP 含 `'unsafe-inline'`，且金鑰存於 localStorage
- 證據：`api/security.py:55-56`；`static/index.html:943`、`:2001-2005` 把金鑰寫入 localStorage。
- 影響：一旦發生 XSS，金鑰會被直接讀出。`static/index.html:1622` 的 `pText.innerHTML` 把 `caseId` 直接插入樣板；`caseId` 來自伺服器產生的內容雜湊（`api/cases.py:45` `content_case_id("SAMP", rec)`），目前風險低，但寫法本身不安全。整體屬縱深防禦缺口，未發現可直接利用的 XSS。
- 建議：拆出外部 JS 後移除 `'unsafe-inline'`；金鑰改由 sessionStorage 或每次輸入。

### L3（低，已確認）未處理例外記錄完整 traceback
- 證據：`api/errors.py:58-61` `current_app.logger.exception("unhandled error: %s", exc)`；`routes/printing.py:134` 同。
- 影響：例外訊息若含病歷片段（例如 XML 解析錯誤的上下文），會進入 application log。
- 建議：對 PHI 相關端點記錄例外類別而非完整訊息。

### L4（低，已確認）附件錯誤把第三方例外訊息回傳前端
- 證據：`attachments.py:82` `raise ApiError(str(exc))`；`attachment_store.py:70`、`:80`、`:90`、`:98` 把 PIL／pypdf／pillow_heif 的例外訊息放入回傳字串。
- 影響：資訊洩漏程度低，但與 `import_error_message`（api/uploads.py:41-52，A-WR-02）的脫敏原則不一致。
- 建議：統一改為固定訊息，細節只進日誌。

### L5（低，已確認）內部 ODT 模板以 stdlib ElementTree 解析
- 證據：`generators/deduction_print/odt_fill.py:66`；`generators/appeal_print/odt_fill.py:264`；`generators/appeal_print/template.py:125`。模板路徑為固定常數（`routes/printing.py:26-31`）。
- 正面對照：外部申報 XML 已使用 `defusedxml` 並 `forbid_dtd=True`（`parsers/submission_xml.py:273`）。
- 建議：三處統一改用 `defusedxml.ElementTree` 以維持一致性。

### L6（低，已確認）`pypdf` 只在 dev 群組，但 runtime 會 import
- 證據：`pyproject.toml:33` 將 `pypdf` 放在 `dependency-groups.dev`；runtime import 於 `attachment_store.py:22` 與 `generators/evidence_packet/pdf_exporter.py:4`。
- 影響：`uv sync --no-dev` 部署時，附件驗證會 ImportError（可用性問題，非直接安全問題）。
- 建議：移入 `dependencies`。

### L7（低，已確認）`_db_codes` 的 f-string SQL
- 證據：`rule_repository/scripts/sync_latest_rules.py:111`；呼叫端 :175-176 皆為常數表名。
- 建議：比照 `rule_repository/db.py:128-147` 加白名單，避免未來誤用。

### L8（低，缺口）無速率限制
- 本次未在程式碼中找到 rate limit 實作（未做全面 grep），以 `X-API-Key` 的暴力嘗試在 LAN 暴露時是可能的攻擊面。`resolve_caller` 的 constant-time 比對本身良好，但無節流。
- 建議：在 `before_request` 對失敗認證加入計數與退避。

---

## 六、已確認的良好做法（無須修改）

- 認證：`auth.py` 的 `resolve_caller` 以 `hmac.compare_digest` 比對且迴圈不提前返回；缺 header 與錯 key 回應相同（固定訊息 `_AUTH_FAIL_MESSAGE`）；金鑰表 fail-fast 且拒絕過短金鑰（`_MIN_KEY_LEN = 16`）。
- Host 白名單防 DNS rebinding（security.py:101-104、115-116）。
- 安全標頭：CSP、`X-Frame-Options: DENY`、`nosniff`、`Referrer-Policy: no-referrer`（security.py:133-140）。
- 無 CORS 中介層，跨來源讀取被瀏覽器阻擋（但見 H1，CSRF 另案）。
- `server.py:39-42` 預設綁定 `127.0.0.1`、debug 關閉。
- SQL 全數參數化（第三節 Q2）。
- XML：外部申報 XML 使用 `defusedxml` 並 `forbid_dtd=True`（submission_xml.py:273）。
- 上傳大小上限：全域 11MB（app.py:24）；附件 10MB（attachment_store.py:27）；規則 CSV 64MB（rules.py:34-46）；ZIP 單檔、數量與總量限制（evidence_vault.py:38-40）。
- ZIP 穿越：拒絕絕對路徑與 `..`（evidence_vault.py:229-231）；取 basename 攤平（:229）。
- 佐證庫：`_resolve_inside` 以 realpath 防符號連結（:147-153）；`_unique_target` 不覆寫既有檔案（:156-164）。
- HTML 報告：`escape` 一致套用（monthly_report_html.py:150；unified_review_report.py 多處；sampling_preview.py:58）。
- 前端：大多數使用者字串以 `textContent` 寫入（static/index.html:628、1143 註解）。
- LLM 位址：`assert_local_llm_url` 限制為 localhost／私有網段（llm_client.py:43-66）。
- 外部 webhook：目的地只來自環境變數，不接受請求指定（his_integration.py:8-10 註解、:53-65）。
- 審計：禁止 PHI 欄位與長字串，明確拋錯而非靜默剔除（audit_log.py:34-45）。
- 申報 XML 的 `batch` 名稱由 regex 生成（parsers/totfa.py:107-121），不直接使用原始字串做檔名。

---

## 七、缺口與未完成的檢查

1. 未完整讀取 `comparator/narratives.py`、`comparator/soap_advice.py` 全文與 `monthly_pregen.py`，M6 的結論為疑似。
2. 未逐一檢視 `generators/evidence_packet/pdf_exporter.py` 與 `ingest/media.py` 的 `TemporaryDirectory` 是否確實自動清理（僅見 `rmtree`／`os.remove` 的 finally 片段）。
3. 未檢視 `his_integration.py` 的 `soap-enhance` 與 `approve-callback` 全部分支（僅讀到 push 與 webhook）。
4. 未檢視 `case_store/monthly.py`、`appeal_linkage.py` 的輸入欄位 max_len；`validation.py` 只對 `clean_str` 有效。
5. 未檢視 `ingest/media.py` 外部工具（pdftotext、tesseract）的參數是否可被檔名影響（`_run` 以 list 呼叫，應為安全；未逐行確認）。
6. `static/index.html` 只檢視了 XSS 相關片段（innerHTML、localStorage、authFetch），未做全檔審查。
7. 未檢視 `config/settings.py` 的預設路徑是否會因環境變數而指到敏感位置。
8. 未進行任何動態測試；所有結論皆來自靜態讀取。

---

## 八、建議優先順序

1. H1、H3：將 `monthly.email_monthly_report`、`monthly.monthly_batch_report`、`monthly.upload_monthly`、`monthly.list_monthly_batches`、`sampling.import_sampling_cases`、`appeal.import_appeal_cases`、`attachments.upload_appeal_attachment`、`printing.*` 移出豁免清單；同時為所有非 GET 的豁免端點補上 Origin 檢查。
2. H2：移除前端硬編碼的預設金鑰；部署前輪換 `.env` 中的 `ELC_API_KEYS`；`load_api_keys` 增加弱值檢查。
3. M1、M2：審計 `path` 遮罩 vault_key；豁免端點的審計 caller 可辨識化。
4. M3、M5：修正免認證清單與註解的一致性；`target_id` 校驗。
5. 其餘低與疑似項目依排程處理。
