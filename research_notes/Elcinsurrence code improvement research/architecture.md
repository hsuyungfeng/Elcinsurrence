# Elcinsurrence 程式架構與結構改善研究

路徑慣例：下文所有路徑皆以 repo 根目錄 `/home/hsu/Desktop/Elcinsurrence/` 為基準（例如 `src/elc_audit_engine/unified_review_report.py:860` 即 `/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/unified_review_report.py` 第 860 行）。

研究範圍：`src/elc_audit_engine/`（約 123 個 `.py` 檔）、`src/elc_audit_engine/api/`（含 `routes/`）與 `server.py`。分支 `feat/phase-17-evidence-vault`。未執行測試，也未以工具做完整 import-cycle 分析；所有行號皆由讀檔或 grep 直接取得。`graphify-out/GRAPH_REPORT.md` 僅作導覽，其 `Built from commit: 98f5f31c`（`graphify-out/GRAPH_REPORT.md:14-15`）與目前 HEAD（`6ea9be6`）不同，圖譜可能過時，因此所有結論都以原始碼為準。

---

## 1. 哪些模組過大、職責過多，自然切分點在哪

### Takeaway
最大的結構問題集中在三個模組：`unified_review_report.py`（860 行）把 CSS/JS、檢視模型、欄位對映、縮圖 I/O 與兩套案件版面混在同一檔；`api/routes/sampling.py`（752 行）同時承擔流程編排、業務篩選與 HTML/JSON 組裝；`monthly_audit.py`（657 行）混合規則評估、報告納入政策與批次持久化。三者都有清楚的內部切分線，可各自拆成 2–4 個子模組，不需要改動對外契約。

### Cited Findings
- 檔案規模（`wc -l`）：`src/elc_audit_engine/unified_review_report.py` 860 行（38.4 KB）；`src/elc_audit_engine/api/routes/sampling.py` 752 行；`src/elc_audit_engine/monthly_audit.py` 657 行（25.5 KB）；`src/elc_audit_engine/case_store/store.py` 591 行；`src/elc_audit_engine/generators/appeal.py` 580 行；`src/elc_audit_engine/api/routes/appeal.py` 450 行；`src/elc_audit_engine/monthly_report_html.py` 433 行（20.5 KB）；`src/elc_audit_engine/api/routes/monthly.py` 326 行；`src/elc_audit_engine/api/routes/his_integration.py` 279 行。測試端 `tests/test_appeal_print.py` 1218 行。
- `unified_review_report.py` 的切分線（已逐段核對）：
  - 樣式與腳本以字串常數內嵌：`_CSS` 於 `unified_review_report.py:48-142`（約 95 行）、`_SCRIPT` 於 `:145-192`。
  - 檢視模型：`RuleBlock` `:203-209`、`ReviewCaseView` `:212-278`（欄位 40 餘個）。
  - 影像縮圖（含 PIL I/O）：`make_thumbnail_data_uri` `:281-293`，PIL 於 `:283` 函式內匯入。
  - 欄位對映：`build_review_case_view` `:296-411`（116 行，含 monthly_source 解析與 order 單價/點數回填 `:361-378`）。
  - HTML 區塊：`_section_*` `:426-566`；`_SECTION_BUILDERS` `:574-581`。
  - 兩套案件版面：`_case_body_html` `:584-722`，其中 `:589-590` 走 `SECTION_ORDER` 路徑，`:593-722`（約 130 行）走「月審風格」路徑。
  - 文件組裝與輸出：`_document` `:725-738`、`render_unified_review_html` `:741-757`、`_case_summary_line` `:765-794`、`_case_item_html` `:797-812`、`render_aggregated_review_html` `:815-847`。
- `monthly_audit.py` 的切分線：
  - 常數與政策混在最上方：`RESTRICTION_MARKERS` `:44`、`_KIND_PATTERNS` `:47-53`、ICD 規則 `:57-58`、占位字 `:64-66`、狀態字串 `:69-81`。
  - 資料型別 `Evidence` `:89`、`OrderFinding` `:104`、`CaseAudit` `:138`、`BatchAudit` `:176`、序列化 `_finding_to_dict` `:193`。
  - 單醫令規則評估：`_resolve_flags_with_official_price` `:318-338`、`evaluate_order` `:341-430`（90 行）。
  - 報告納入政策（與審計本身不同關注點）：`CASE_TOTAL_POINTS_MIN` `:547`、`EXCLUDED_ORDER_CODES` `:552`、`report_view` `:571-595`；檔頭 `:545-546` 註解也承認「審計結果保留所有旗標，報告才過濾」。
  - 批次持久化與分頁：`audit_batch` `:598-657`，其中 `store.set_artifact(...)` 寫庫於 `:646-647`，分頁迴圈 `:640-649`。
- `routes/sampling.py` 的職責分布：
  - 流程編排：`batch_audit_sampling` `:197-229`、`closed_loop_single_sampling_case` `:232-250`、`audit_sampling_case` `:506-632`（126 行，含狀態轉換 `:560-565`、review 寫回 `:569-578`、LLM 呼叫 `:580-600`、回應組裝 `:602-632`）。
  - 狀態機輔助函式直接放在路由模組：`advance_sampling_case` `:438-470`（公開名稱，供其他模組 import 的風險見第 4 節）。
  - 展示與提示文字：`_advice` `:491-503`、`_evidence_context` `:473-488`。
  - 業務篩選：TOTFA 高風險抽樣邏輯 `:656-693`（見第 2 節）。
  - 檔案 I/O：`import_sampling_cases` `:636-752` 內直接 `os.remove(path)`（`:722`）與多種格式分派。
  - 影像縮圖在路由內呼叫：`_stage2_view` `:160` 呼叫 `make_thumbnail_data_uri`。
- `routes/appeal.py` 同樣的情形：`generate_appeal_draft` `:90-197`（108 行，含規則查詢、LLM 呼叫 `:173-179`、artifact 寫入 `:186-187`）；匯入 TOTFA 篩選 `:358-390`。
- `case_store/store.py`：`class CaseStore` 於 `:116`，公開方法包含 `create` `:126`、`transition` `:216`、`advance` `:234`、`list_by_state` `:365`、`list_all` `:398`、`list_by_batch` `:422`、`get_soap_template` `:455`、`put_soap_template` `:486`、`update_payload` `:512`；另由 `graphify-out/GRAPH_REPORT.md:273` 的 god node 排行可見 `CaseStore` 有 92 條邊、為全專案最高（僅供佐證，見檔頭說明）。
- `generators/appeal.py`：`build_appeal_draft` `:370-547`（約 178 行）同時做驗證（`validate_appeal_claim` `:258`）、段落裁切（`_trim_sections` `:336`）與文字組裝；`_build_rule_basis` `:166`。
- 扁平根目錄的模組混放：`src/elc_audit_engine/` 根目錄直接放 18 個領域模組（`monthly_audit.py`、`monthly_pregen.py`、`monthly_reasoning.py`、`monthly_report_html.py`、`sampling_closed_loop.py`、`sampling_preview.py`、`sampling_sampler.py`、`appeal_linkage.py`、`evidence_vault.py`、`attachment_store.py`、`unified_review_report.py` 等），但同時又有 `case_store/`、`comparator/`、`generators/`、`parsers/` 等子套件。`sampling_*` 與 `monthly_*` 明顯可各自成為子套件。

### Inferences
- 三個大型模組的切分點可以直接對應現有的註解段落與常數區，屬於「搬移」而非「重寫」：
  - `unified_review_report.py` 可拆為 `review/view_model.py`（`:203-278`＋`:296-423`）、`review/thumbnails.py`（`:281-293`）、`review/sections.py`（`:426-566`）、`review/case_body.py`（`:584-722`）、`review/document.py`（`:725-847`），樣式與腳本可獨立為 `review/assets.py`。
  - `monthly_audit.py` 可拆為 `monthly/rules_eval.py`（`:226-430`）、`monthly/aggregate.py`（`:484-541`）、`monthly/report_policy.py`（`:544-595`）、`monthly/batch.py`（`:598-657`）；資料型別 `:88-192` 保留於 `monthly/models.py`。
- `unified_review_report.py` 的 `:589-590` 與 `:593-722` 兩條路徑，以及 `ReviewCaseView` 內的 `kpis`、`thumbnails` 欄位，可能有一部分已不被使用（見第 2 節「死碼／未使用的渲染路徑」）。
- `monthly_audit.py` 的「審計」與「報告納入」應分開命名，目前 `audit_batch`（`:598`）回傳的 `BatchAudit` 再由 `report_view`（`:571`）過濾，兩者的語意差異靠呼叫端記得呼叫 `report_view`，屬於容易漏掉的隱性契約（見 `api/routes/monthly.py:166`、`monthly_report_html.py:373`）。

### Gaps
- 未逐行閱讀 `case_store/store.py` 的交易與查詢細節（僅確認方法清單），無法評估其內部拆分性。
- 未閱讀 `generators/appeal_print/`、`generators/deduction_print/`、`api/routes/printing.py`（141 行）與 `api/routes/attachments.py` 的實作細節。
- 行數與位元組數以 `wc -l` 與 `ls -la` 取得；`unified_review_report.py` 的 38.4 KB 與 `monthly_audit.py` 的 25.5 KB 與使用者提供的數字一致。

---

## 2. 邏輯在哪些模組重複（sampling、monthly、appeal、evidence 等）

### Takeaway
重複最嚴重的有五類：(a) 第 2 階與第 3 階審查檢視模型幾乎逐行相同；(b) TOTFA 高風險篩選邏輯在 sampling 與 appeal 各寫一份，且篩選條件實際上失效；(c) 報告 HTML 片段（案件標題、佐證庫列表、規則全文、複製 SOAP 的 JS/CSS）在 `unified_review_report.py` 與 `monthly_report_html.py` 之間重複；(d) ROC 民國日期解析散落至少 8 處；(e) SOAP 範本快取與 LLM 建議組裝在 3–4 處各寫一次。

### Cited Findings
- **(a) 第 2 / 第 3 階檢視模型重複**：
  - `src/elc_audit_engine/api/routes/sampling.py:143-194` 的 `_stage2_view` 與 `src/elc_audit_engine/api/routes/appeal.py:239-286` 的 `_stage3_view` 結構相同：vault_key 推導與 `list_vault_files` 清單（sampling `:151-156`、appeal `:244-249`）、縮圖迴圈（sampling `:157-162`、appeal `:250-254`）、attachments（sampling `:163`、appeal `:255`）、`fallback_soap` 範本降級（sampling `:165-169`、appeal `:257-261`）、`get_rule` 規則區塊（sampling `:171-183`、appeal `:263-275`）、最後都呼叫 `build_review_case_view`。
  - 差異：sampling 的 `order_code` 會回退到 `target_order_code` 與 `monthly_source.order_code`（`sampling.py:173`），appeal 只回退到 `monthly_source.order_code`（`appeal.py:265`）。這種不一致很可能是複製後分歧所致（推論）。
  - 縮圖上限：sampling 使用具名常數 `_PREVIEW_THUMB_LIMIT = 24`（`sampling.py:73`、`:159`），appeal 直接寫死 `[:24]`（`appeal.py:251`）。
- **(b) TOTFA 高風險篩選重複，且條件失效**：
  - `src/elc_audit_engine/api/routes/sampling.py:656-693`（sampling 匯入 TOTFA zip）與 `src/elc_audit_engine/api/routes/appeal.py:358-390`（appeal 匯入 TOTFA zip）為幾乎相同的迴圈，包含 `d39`、點數 `pts >= 350`、單價 `price >= 5.0`、上限 `len(records) < 50`、`seen_cases` 去重。
  - 閾值 `1000`、`350`、`5.0`、`50` 在上述兩處各寫一次（`sampling.py:678`、`appeal.py:379`），與 `src/elc_audit_engine/parsers/totfa.py` 的 `is_points_over`、`is_drug_over_price` 判斷（`monthly_audit.py:31-36`、`:285-293` 透過 helper 使用）並存，產生三處閾值來源。
  - 條件失效（由程式流程推導，未執行驗證）：外層條件 `if (tp > 1000 and (pts >= 350 or price >= 5.0)) or len(records) < 50:`（`sampling.py:678`）中，`len(records) < 50` 為真時外層必過；內層 `if c.case_seq not in seen_cases and len(records) < 50:`（`sampling.py:679`）只看去重與筆數，不看風險條件。當 `len(records) >= 50` 時內層又不再加入。因此風險條件 `pts >= 350` 與 `price >= 5.0` 永遠不影響結果，最終輸出等同「檔案順序前 50 個不重複 case_seq」。註解 `sampling.py:658` 寫的是「取前50筆高風險項」，與程式行為不符。`appeal.py:379-380` 完全相同。
- **(c) 報告 HTML 片段重複**：
  - 複製 SOAP／開啟範例病歷的 JS：`unified_review_report.py:146-175`（`copySoap`、`openSoapModal`）與 `monthly_report_html.py:50-71`（同名同功能，程式幾乎相同）。
  - CSS 重複定義：`.vault-box`／`.vault-title`／`.vault-files`／`.vault-file-item` 在 `monthly_report_html.py:43-46` 與 `unified_review_report.py:138-141`；`button.btn-copy` 在 `unified_review_report.py` 內定義兩次（`:78` 與 `:135`）。
  - 案件標題九段式欄位清單：`monthly_report_html.py:279-301`（`_case_header`）與 `unified_review_report.py:765-794`（`_case_summary_line`）的 `segments` 清單完全相同。
  - 規則全文區塊：`monthly_report_html.py:193-223`（`_rule_fulltext_html`）與 `unified_review_report.py:653-677`（`_case_body_html` 的規則段）結構相同。
  - 佐證庫列表：`monthly_report_html.py:304-333`（`_case_vault_html`，含 `cat_icons` `:314-319`）與 `unified_review_report.py:603-624`（同樣 `cat_icons` 於 `:604-609`，但與 `_VAULT_LABELS` `:38-42` 標籤不同）。
- **(d) ROC 民國日期解析重複**（以 `+1911`、`-1911` 或 `_ROC_OFFSET` 形式出現）：
  - `src/elc_audit_engine/monthly_audit.py:274-282`（`roc7_to_date`）
  - `src/elc_audit_engine/rule_repository/loaders/dates.py:26`（`_ROC_EPOCH_OFFSET`）與 `:29` 的 `parse_flexible_date`（已有通用版本）
  - `src/elc_audit_engine/parsers/totfa.py:117`
  - `src/elc_audit_engine/evidence_vault.py:85`（`vault_key_for_case` 內）
  - `src/elc_audit_engine/record_aggregator/providers.py:71`（`_parse_date`）
  - `src/elc_audit_engine/generators/sampling_xml.py:31`
  - `src/elc_audit_engine/generators/appeal_print/field_mapping.py:66-67`、`:77`（`_fmt_roc_date_iso`）與 `src/elc_audit_engine/generators/deduction_print/field_mapping.py:32`、`:46`（同名同實作的第二份）
  - 就醫日解析：`src/elc_audit_engine/api/records.py:36-41`（`parse_visit_date`）與 `src/elc_audit_engine/sampling_closed_loop.py:273-278`（`_parse_visit_date`）功能相同，兩者都呼叫 `parse_flexible_date`。
- **(e) SOAP 範本快取與 LLM 建議重複**：
  - 範本讀寫至少在四處：`src/elc_audit_engine/api/routes/his_integration.py:131-133`（讀）與 `:204`（寫）、`src/elc_audit_engine/monthly_pregen.py:79`、`:99`、`:129`、`:151`、`src/elc_audit_engine/sampling_closed_loop.py:134`（`fallback_soap`）。
  - `generate_soap_advice` 有 4 個呼叫點：`api/routes/sampling.py:592`、`api/routes/appeal.py:173`、`api/routes/his_integration.py:180`、`monthly_pregen.py`（經 `comparator/soap_advice.py:162` 定義）。
  - 病史脈絡文字的組裝重複：`sampling.py:583-590` 與 `appeal.py:165-172` 都以 `timeline.events[:5]` 組 `- [date] category: summary`。
- **其他重複**：
  - 批次 ID 正規式：`api/routes/sampling.py:359`（`_SAMPLE_BATCH_RE`）與 `api/routes/monthly.py:49`（`_BATCH_RE`），內容相同 `^MONTHLY-\d{6}$`。
  - 分頁讀取迴圈：`src/elc_audit_engine/sampling_sampler.py:86-98`（`_all_monthly_payloads`）與 `src/elc_audit_engine/monthly_audit.py:639-649`（`audit_batch`）完全相同的 `offset += len(...)` 模式。
  - 串流存檔與大小上限：`api/routes/monthly.py:54-67`（`_save_stream`，上限 10 MB）與 `api/routes/rules.py:34-47`（同名函式，上限 64 MB），而 `api/uploads.py:18` 已有 `save_upload`，但 monthly 與 rules 未使用它。
  - `api/routes/sampling.py:78-86`（`_sampling_case_or_404`）與 `api/routes/appeal.py:293-298`（同類檢查，手寫）。

### Inferences
- TOTFA 高風險篩選應收斂為單一函式（例如放在 `monthly_audit.py` 或 `parsers/totfa.py`），閾值以具名常數表示；修正後應同時補上測試以覆蓋「風險條件會影響結果」。目前的測試若未覆蓋此分支，就不會發現篩選失效（推論；未檢查 `tests/` 內對應案例）。
- 第 2 / 第 3 階的 `_stage2_view`／`_stage3_view` 應合併為單一 `build_stage_view(stage, record, *, with_thumbnails, order_code_keys)`，把「回退鍵」差異改成參數，可消除 `:173` 與 `:265` 的分歧。
- `unified_review_report.py` 與 `monthly_report_html.py` 應抽出共用 partial（案件標題、佐證庫、規則全文、複製 JS、CSS token），兩份 HTML 只保留版面差異。
- ROC 解析應統一到 `rule_repository/loaders/dates.py` 的 `parse_flexible_date`（已支援民國七碼，見 `:55` 註解）或新增單一 `utils/roc.py`，其餘 7 處改為呼叫它。
- SOAP 範本快取與 LLM 建議應抽成 `soap_service.py`（讀範本、生成、寫回、組病史脈絡），三個路由與 `monthly_pregen` 共用。

### 死碼／未使用的渲染路徑（由程式結構推導）
- `unified_review_report.py` 中，縮圖只會經由 `_gallery_html`（`:478-493`）輸出；`_gallery_html` 只被 `_section_vault_panel`（`:500`）呼叫，`_section_vault_panel` 只被 `_section_core`（`:518`）呼叫，`_section_core` 只在 `SECTION_ORDER` 路徑（`:590`）中出現。而 `:593-722` 的月審風格路徑完全不呼叫這些函式，改用自己的 `vault_part`（`:603-624`）。
- 因此凡 `order_code`、`primary_diagnosis` 或 `secondary_diagnoses` 任一存在，`has_monthly_style`（`:587`）即為真，縮圖就不會被渲染；但 `sampling.py:157-162` 與 `appeal.py:250-254` 仍在路由內對最多 24 張影像做 PIL 解碼。sampling 與 appeal 的案件 payload 通常都帶有 `order_code`，所以這些縮圖工作很可能大多被丟棄（推論；需以實際資料驗證）。
- 同一原因下，`SECTION_ORDER`（`:195`）與 `_SECTION_BUILDERS`（`:574-581`）的常規路徑可能只剩「無醫令資料」的少數情境使用。

### Gaps
- 未檢查 `tests/` 是否覆蓋 TOTFA 篩選或縮圖渲染分支。
- 未確認 `his_integration.py` 內 `soap_enhance` 是否與 `monthly_pregen.pregen_template` 的快取判斷在細節上一致（僅確認兩者都讀寫 `soap_templates`）。
- 「篩選條件失效」結論由程式流程推導，未以執行或單元測試驗證。

---

## 3. routes（`api/routes/` 與 `server.py`）是否薄，是否內嵌業務邏輯

### Takeaway
`server.py` 與 app factory 是薄的，`api/` 的分層（app factory、context、errors、validation、security、blueprints）設計良好；但 `api/routes/` 內的路由普遍內嵌業務流程（規則查詢、LLM 呼叫、狀態轉換、檔案寫入、報告組裝）。business 模組反向不依賴 Flask，分層方向正確，缺的是 service 層。另有一組明確的行為缺陷與不一致，集中在路由中。

### Cited Findings
- `server.py` 僅 `:24` 匯入 `create_app`、`:26` 的 `app = create_app()`，以及 `:39-42` 的啟動參數與 `app.run`，屬薄入口（檔案共 42 行，其中大部分為註解與 docstring）。
- `src/elc_audit_engine/api/app.py:27` `create_app(...)`：依賴注入 `case_store`（`:30`）與 `migrate_legacy`（`:31`）；`:62` 無注入時 `CaseStore()`；`:70-72` 預設在工廠內執行 `migrate_legacy_uploads`（一次寫入資料庫的副作用）。`app.py:3` 的模組註解宣稱「匯入本套件不產生任何副作用」，但工廠呼叫本身有寫入。
- `src/elc_audit_engine/api/context.py:16` `EXTENSION_KEY = "elc"`、`:24-25` `case_store()` 經 `current_app.extensions` 取得、`:28-29` `caller_id()` 經 `flask.g`。
- `src/elc_audit_engine/api/routes/__init__.py` 以 `ALL_BLUEPRINTS` 集中註冊 10 個 blueprint，結構清楚。
- 業務模組不依賴 api：在 `src/elc_audit_engine/` 中搜尋 `flask`／`current_app`／`elc_audit_engine.api`，只有 `src/elc_audit_engine/auth.py:25` 匯入 `flask`（`g`、`request`）。`sampling_closed_loop.py:217-218` 的註解亦明確寫「由呼叫端注入，避免本模組依賴 api 套件」。`monthly_audit.audit_batch`（`:598`）、`monthly_pregen`、`sampling_sampler.sample_monthly_batch`（`:101`）都以 `store` 作為參數注入。
- 路由內的業務流程（節錄）：
  - `api/routes/monthly.py:80-130`（`upload_monthly`）：解析 → 冪等匯入 → `audit_batch(persist=True)`（`:98-103`）→ 複製原始 zip 到 `ELC_UPLOAD_DIR`（`:105-109`）→ 渲染 HTML 並寫入 `ELC_OUTPUT_DIR`（`:111-116`）→ `finally` 清暫存（`:117-119`）。
  - `api/routes/monthly.py:176-226`（`email_monthly_report`）：SMTP 設定判斷與開發模式寫 `.eml`（`:204-217`），並在路由內讀取環境變數 `SMTP_FROM`（`:205`）。
  - `api/routes/monthly.py:229-274`（`monthly_soap_template`）：規則查詢（`:249`）與 LLM 結果狀態映射（`:263-274`）。
  - `api/routes/sampling.py:506-632`（`audit_sampling_case`）：規則查詢、狀態轉換（`:560-565`）、review 寫回（`:569-578`）、LLM 呼叫（`:580-600`）、回應組裝（`:602-632`）。
  - `api/routes/appeal.py:90-197`（`generate_appeal_draft`）：規則查詢（`:122-130`）、附件查詢（`:138-145`）、草稿（`:150-159`）、狀態推進（`:160`）、LLM（`:163-181`）、artifact 寫入（`:186-187`）。
  - `api/routes/his_integration.py:112-242`（`soap_enhance`）：約 130 行，內含 regex 萃取主診斷（`:122-130`，`import re` 在 `:123`）、範本快取（`:131-133`）、規則查詢（`:159`）、LLM（`:180`）、範本寫回（`:204`）。
  - `api/routes/his_integration.py:57-68`（`_deliver_webhook`）：直接使用 `urllib.request` 發送 HTTP，並於 `:266` 讀取環境變數 `HIS_WEBHOOK_URL`。
  - `api/routes/printing.py:68`、`:126` 每次請求呼叫 `settings.load_facility_config()`（檔案讀取）。
- 路由內的行為缺陷與不一致（均以程式碼直接核對）：
  - **未定義變數導致 LLM 建議恆為 None**：`src/elc_audit_engine/api/routes/appeal.py:175` 使用 `order_name or order_code`，但整個 `appeal.py` 中 `order_name` 只出現此一處、無任何定義（grep 結果）。`generate_appeal_draft` 的參數為空（`:91`），因此執行到 `:173-179` 時會拋出 `NameError`，被 `:180-181` 的 `except Exception` 吞掉並只記 warning。推論：此端點的 `soap_advice` 恆為 `None`（建議以測試驗證）。
  - **closed-loop 不推進狀態，但文件宣稱會**：`src/elc_audit_engine/sampling_closed_loop.py` 中 `transition`／`advance` 字樣為 0 次（grep）。但 `:8` 與 `:214` 的文字都說「狀態流轉」。`sampling.py:560` 的 `advance_sampling_case` 只在 `audit_sampling_case` 呼叫；`batch_audit_sampling`（`sampling.py:197-229`）與 `closed_loop_single_sampling_case`（`:232-250`）都不推進狀態。兩條入口的狀態語意不同。
  - **過時的模組文件**：`sampling_closed_loop.py:11-14` 寫「`run_closed_loop`、`fallback_soap` 以 NotImplementedError 佔位」，但兩者實際已實作（`:119`、`:205`）。
  - **規則 DB 路徑不一致**：`monthly.py:249`、`monthly_audit.py:621`、`his_integration.py:159` 會傳入 `db_path=current_app.config.get("ELC_RULES_DB_PATH")`；而 `sampling.py:176`、`appeal.py:124`、`appeal.py:268`、`api/cases.py:39`、`api/cases.py:69` 以及 `pipeline.py:89-132`（`run_presubmission_check`，無 `db_path` 參數）都使用預設路徑。同一個 app 的設定在不同端點生效情況不同。
  - **吞掉所有例外**：`sampling.py:182-183`、`appeal.py:274-275`（`_stage2_view`／`_stage3_view` 內規則查詢失敗即 `pass`），與同檔 `sampling.py:547-551`、`appeal.py:124-127` 對規則庫故障回 503 的 P0-2 原則互相矛盾。`api/cases.py:42-43` 同樣吞掉所有例外，而同檔 `:72-73` 只吞 `RuleRepositoryError`。`monthly_report_html.py:311-312` 對 evidence_vault 的任何例外回空字串。
  - **裸 except**：`sampling.py:665`、`:671`、`:676` 與 `appeal.py:366`、`:372`、`:377` 使用 `except:`（會吞掉 `KeyboardInterrupt` 等）。
  - **request 解析方式不一致**：`json_body(request)`（`sampling.py:116`、`:390`、`:513`；`appeal.py:97`；`his_integration.py:73`、`:115`、`:246`；`printing.py:37`、`:82`）與直接 `request.get_json(silent=True)`（`appeal.py:218`、`monthly.py:185`、`monthly.py:236`、`bridge.py:32`）並存。前者會拋 `ApiError`，後者靜默回 `None`。
  - **無效 kind 的回應碼不一致**：`sampling.py:84-85` 回 404；`appeal.py:297-298` 回 400；`sampling.py:525-526` 回 409。
  - **批次端點靜默截斷**：`sampling.py:140`、`appeal.py:228`、`appeal.py:307`、`appeal.py:326` 皆以 `limit=1000` 讀取，無 count 比對；而 `case_store/store.py:401-403` 的 docstring 明文要求呼叫端「應以 count 取得總數並揭露給使用者，避免超過 limit 時靜默截斷（A-WR-12）」。
  - **N+1 規則查詢**：`api/cases.py:37-43`（`to_sampling_case` 內對每筆記錄查 `get_rule`），而 `sampling.py:407`、`:724` 以迴圈呼叫它；`sampling.py:320` 的 `sampling_batch_report` 對每案呼叫 `_stage2_view`，後者再查一次 `get_rule`（`sampling.py:176`）與 vault 清單。

### Inferences
- 路由層的主要改善方向是新增 service 層（例如 `services/sampling_service.py`、`services/appeal_service.py`、`services/monthly_service.py`、`services/his_service.py`）。路由只做「解析請求 → 呼叫 service → 序列化回應」，service 回傳 dataclass／dict，不直接依賴 `flask.request`。
- 第一批最值得搬移的函式：`import_sampling_cases` 的 TOTFA 分支（`sampling.py:656-693`）、`audit_sampling_case` 的主體（`:506-632`）、`upload_monthly`（`monthly.py:80-130`）、`soap_enhance`（`his_integration.py:112-242`）、`generate_appeal_draft`（`appeal.py:90-197`）。
- 行為缺陷應先修再重構：`appeal.py:175` 未定義變數、TOTFA 篩選失效（`sampling.py:678`、`appeal.py:379`）、closed-loop 狀態語意（`sampling_closed_loop.py:214` 與 `sampling.py:560`）、規則 DB 路徑不一致、`limit=1000` 截斷。這些都有明確的檔案與行號可以寫成回歸測試。
- 統一 request 解析（全面改用 `json_body`）、統一 kind 錯誤碼、統一例外策略（只吞 `RuleRepositoryError` 並明確降級，其餘上拋），三項都可以在 service 抽出後一次完成。

### Gaps
- 未逐行閱讀 `api/routes/printing.py`、`attachments.py`、`vault.py`、`bridge.py`、`his_integration.py:160-242` 的完整分支，只確認其結構與關鍵呼叫。
- 未檢查 `api/security.py` 之 `register_security` 內 `after_request` 的完整行為（`security.py:133`、`:142`）。
- 未驗證 `store.list_all` 之 `limit` 參數在 SQL 層的實際上限（僅依 docstring）。

---

## 4. 全域變數、單例與隱性狀態，對測試與變更的風險

### Takeaway
隱性狀態集中在五處：(1) `current_app.extensions` 與 `flask.g` 的 service locator，屬可接受的設計，但所有路由都隱性依賴它；(2) `create_app` 的預設 `CaseStore()` 與啟動期資料遷移；(3) `settings` 的讀取時機不一致（import-time 綁定與 call-time 讀取並存）；(4) 規則 DB 路徑的預設值經由 `settings.DB_DIR` 隱性決定；(5) 少數 process-global 副作用（OCR 單例、環境變數寫入、測試用環境變數旁路）。其中 (3) 與 (4) 直接造成「測試要不要 monkeypatch 哪個物件」的困擾。

### Cited Findings
- **service locator**：`src/elc_audit_engine/api/context.py:16`、`:24-25`、`:28-29`。路由以 `case_store()` 取得服務，因此單元測試必須經 `create_app(case_store=...)` 或 monkeypatch `current_app.extensions`，不能直接 import 路由內的服務。
- **工廠的預設副作用**：`api/app.py:31` 預設 `migrate_legacy=True`；`:62` 預設 `CaseStore()`；`:70-72` 在工廠內寫入資料庫。`api/cases.py:135-157`（`migrate_legacy_uploads`）每次建立 app 都會掃描 `data/uploads/*.json`（`api/cases.py:123-132`）。
- **import-time 綁定 vs call-time 讀取**：
  - `src/elc_audit_engine/case_store/store.py:18`：`from config.settings import CASES_DB_PATH`，於模組匯入時綁定；`store.py:119-120` 的 `CaseStore.__init__` 預設值就使用此綁定值。測試若修改 `config.settings.CASES_DB_PATH`，已匯入的模組不會生效。
  - 相對地，`src/elc_audit_engine/evidence_vault.py:94-95`（`vault_root()`，docstring 明寫「每次呼叫時讀取 settings，便於測試替換 DATA_DIR」）、`src/elc_audit_engine/attachment_store.py:126-127`（`_db_path()`）、`src/elc_audit_engine/rule_repository/__init__.py:27`（`settings.DB_DIR`）、`src/elc_audit_engine/api/records.py:31-32`（`settings.RECORDS_DIR`）都是 call-time 讀取。同一套設定有兩種語意。
- **規則庫隱性預設**：`src/elc_audit_engine/rule_repository/__init__.py:45` `get_rule(code, db_path=None)`，未傳 `db_path` 時經 `:27` 使用 `settings.DB_DIR/rules.sqlite3`。路由與 pipeline 的呼叫點是否傳入 `db_path` 不一致（見第 3 節），導致同一個 app 的測試與正式行為可能不同。
- **process-global 單例**：`src/elc_audit_engine/ingest/table_ocr.py:45` `_engine = None`；`:51` `global _engine, _engine_failed`（惰性單例，失敗旗標也是全域）；`:59` `os.environ.setdefault("PADDLE_PDX_CACHE_HOME", _CACHE_HOME)` 會修改程序環境變數。
- **測試用旁路留在正式程式**：`src/elc_audit_engine/api/security.py:92` 讀取 `ELC_ALLOW_NO_AUTH_FOR_TESTS == "1"` 時允許以空 API key 表啟動；docstring 雖標示「僅限測試」（`security.py:83-89`），但旗標本身屬於正式程式碼路徑，若環境誤設即為無認證。
- **環境變數散落**：`api/security.py:77`（`ELC_ALLOWED_HOSTS`）、`api/routes/monthly.py:205`（`SMTP_FROM`）、`api/routes/his_integration.py:266`（`HIS_WEBHOOK_URL`）、`rule_repository/mapping/llm_client.py:49`（`ELC_ALLOW_REMOTE_LLM`）、`rule_repository/scripts/sync_latest_rules.py:117`（`RULES_DIR`）。其中 `mailer.py:49` 已採「注入 env dict」的良好做法，與其他位置不一致。
- **死碼與重複的認證機制**：`src/elc_audit_engine/auth.py:190-215` 的 `require_api_key` 裝飾器在 `src/` 內無任何引用（grep 只找到定義）；`auth.py:199` 的註解亦寫明本專案實際採 `before_request` 統一強制（`api/security.py:107-108`）。`auth.py:25` 另在核心模組匯入 `flask`。
- **core 模組依賴 `config.settings` 的範圍廣**：`audit_log.py`、`evidence_vault.py`、`attachment_store.py`、`case_store/store.py`、`rule_repository/__init__.py` 與多個 scripts 皆直接 `from config import settings`（或 `config.settings`），業務模組與設定耦合。
- **業務規則常數寫死在程式與文字中**：`monthly_audit.py:547`（`CASE_TOTAL_POINTS_MIN = Decimal(1000)`）、`:552`（排除代碼）；`monthly_report_html.py:75-77`（旗標文字 `> 350`）與 `:418`（說明文字 `> 1000`、`> 350`、`> 5`）；`unified_review_report.py:630`（`"醫令點數 > 350"`）；`sampling.py:678`、`appeal.py:379` 的 `350`、`5.0`、`1000`、`50`。修改政策需要同時改多處。
- **路由內的檔案讀取**：`api/routes/printing.py:68`、`:126` 每次請求呼叫 `settings.load_facility_config()`；`api/routes/misc.py:41` 直接以 `settings.OUTPUT_DIR` 提供下載。

### Inferences
- 建議統一為「請求期由 app 注入所有路徑與服務」：`create_app` 接受一個 `Config` dataclass（含 `case_db_path`、`rules_db_path`、`data_dir`、`records_dir`、`output_dir`），由 `app.extensions` 傳給服務；`settings` 只在 `create_app` 的預設值中被讀一次。這能同時解決 import-time 與 call-time 不一致、規則 DB 路徑不一致、以及測試需要 monkeypatch 多個模組的問題。
- `create_app` 的 `migrate_legacy` 預設值建議改為 `False`，改由 `server.py` 或 CLI 明確呼叫；如此工廠本身不寫庫，測試也不必每次都傳 `migrate_legacy=False`。
- 刪除 `auth.py:190-215` 的 `require_api_key` 前，應先確認 `tests/` 與外部腳本沒有使用；`auth.py:25` 的 flask 依賴可隨之移除。
- 把 `ELC_ALLOW_NO_AUTH_FOR_TESTS` 移到測試專用的 conftest 或 app 設定，避免正式程式碼路徑保有此旁路。
- `ingest/table_ocr.py` 的單例可改為由 `create_app` 持有的依賴，或至少把 `os.environ.setdefault` 移到函式呼叫的一次性初始化區段。

### Gaps
- 未實際執行測試，也未確認 `tests/` 內 monkeypatch 的目標（例如是否大量 patch `settings`）。
- 未檢查 `audit_log.py` 的寫入路徑與 `bridge_queue.py` 的全域佇列狀態（僅從 grep 確認其讀取 `settings`）。
- 未檢查 `rule_repository/__init__.py:30` `is_effective_on` 與 `comparator/` 內是否另有快取。

---

## 5. 跨主題的優先順序建議（推論）

以下排序依「風險」與「改動成本」綜合判斷，屬於推論，不是已驗證的結論。

1. **先修行為缺陷（小改動、可回歸測試）**
   - `src/elc_audit_engine/api/routes/appeal.py:175` 未定義的 `order_name`（使 LLM 建議恆為 None）。
   - TOTFA 高風險篩選條件失效：`sampling.py:678-679`、`appeal.py:379-380`。
   - closed-loop 與 audit 的狀態語意不一致：`sampling_closed_loop.py:214` 文件與實作不符，`sampling.py:560` 與 `:232-250` 行為不同。
   - 規則 DB 路徑在 `sampling.py:176`、`:547`、`appeal.py:124`、`:268`、`api/cases.py:39`、`:69`、`pipeline.py:89-132` 未傳遞。
   - 批次端點 `limit=1000` 靜默截斷（`sampling.py:140`、`appeal.py:228`、`:307`、`:326`）。
   - 吞例外與裸 except（`sampling.py:182-183`、`:665`、`:671`、`:676`；`appeal.py:274-275`、`:366`、`:372`、`:377`；`api/cases.py:42-43`）。
2. **再抽 service 層**：依第 3 節列出的五個路由函式逐步搬移；路由行數目標為每個 handler 約 20–40 行。
3. **消除重複**：TOTFA 篩選、第 2/3 階檢視模型、ROC 日期解析、SOAP 範本與 LLM 建議、報告 HTML 共用 partial、`_save_stream`（改用 `api/uploads.py:18` 的 `save_upload`）、`_BATCH_RE` 單一來源。
4. **拆大型模組**：`unified_review_report.py` 與 `monthly_audit.py` 依第 1 節切分點拆分；`sampling_*`、`monthly_*` 根目錄模組可整理為子套件。
5. **收斂隱性狀態**：統一 config 注入、移除 `require_api_key` 死碼、移除正式路徑的測試旁路、讓 `create_app` 不再預設寫庫。

### Gaps（整體）
- 未執行 import-cycle 工具。graphify 報告稱「None detected」（`graphify-out/GRAPH_REPORT.md:297`），但該圖譜版本過時，未獨立驗證。
- 未閱讀 `comparator/`、`parsers/`、`record_aggregator/` 的實作細節，因此無法評估其內部重複與耦合程度。
- 未驗證 `tests/` 的覆蓋率，因此所有「測試不足」的推論都僅為推論。
- 行為類結論（例如 `appeal.py:175` 的 `NameError`、TOTFA 篩選失效）為由程式碼推導，建議以單元測試驗證後再據以修改。
