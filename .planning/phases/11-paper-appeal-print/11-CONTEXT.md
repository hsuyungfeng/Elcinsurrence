# Phase 11: 紙本申復清單列印 - Context

**Gathered:** 2026-08-08
**Status:** Ready for planning

<domain>
## Phase Boundary

從既有 `AppealDraft`（Phase 7 `src/elc_audit_engine/generators/appeal.py` 產出）生成符合官方三聯式「門診醫療費用點數申復清單」（105.04.01 修訂版）版式的可列印 PDF。這是既有電子申復流程（Markdown／JSON／申復 XML，Phase 7/9）之外新增的一條輸出通道，供未串接 HIS 或選擇紙本作業的院所使用。資料層（`AppealDraft`／`CaseStore`）不變，本 phase 只新增 render 輸出。

</domain>

<decisions>
## Implementation Decisions

### 排版工具鏈
- **D-01：採 LibreOffice/`soffice --headless` 套版**，延續 Phase 2（docx-tree 索引器）已驗證可用的工具鏈慣例，不引入新的重量級 Python PDF 套件（如 reportlab）。
- **D-02：直接拿現成官方 `.odt` 範本套版**——`officialdocument/電子申復文件格式/30396_1_1050105-1門診診療費用申復清單.odt`（可編輯版，ODF XML 可解析）作為排版依據來源，而非憑空用程式碼繪製表格框線。版面與官方 `30396_4_無刪除線1050105-PDF門診診療費用申復清單-.pdf` 範本逐欄核對一致（見 ROADMAP.md Phase 11 Success Criteria 1）。

### 三聯處理
- **D-03：一次列印產生三頁 PDF**，每頁對應官方一聯（第一聯醫療院所存查／第二聯衛生福利部中央健康保險署存查／第三聯代付款清單）。三聯共用相同的醫令明細內容；差異僅在第三聯多出「中央健康保險署填列」核定／複核／初核／審查委員欄位（該欄留空，屬健保署複核後填列，非系統產出範圍）。院所端列印後自行裁切或使用複寫紙列印，符合現行「一份 PDF 對應一案件」的系統慣例（比照 `write_appeal`／`write_report` 一案一檔案）。

### 院所基本資料來源
- **D-04：新增 config 設定檔**（如 `config/facility.json` 或比照 `config/settings.py` 的環境變數模式，交由 research/planner 決定具體形式）存放固定不變的院所層欄位：代號字碼、醫療院所名稱、地址、負責醫師姓名等。
- **D-05：案件層欄位（審查科別、原申報類別/日期、年度月份頁數、流水號等）由 `AppealDraft` 或 `CaseStore` 資料推導或作為生成函式參數傳入**，不寫死在 config——這些每案不同。`AppealDraft.case_class` 對應官方「案件分類」欄（源自 D-14d 欄位 5／申報 XML `d1`），可直接沿用。

### 超行分頁
- **D-06：醫令明細行數超過單頁容量時自動分頁，每頁重複院所層欄位與表頭**，頁數欄（官方表格本身就有「頁數」欄位）依序遞增。符合官方紙本作業「多頁申復清單本來就常見」的實務慣例，非系統自創行為。

### Claude's Discretion
- 具體 config 檔案格式（JSON vs 環境變數 vs 沿用 `config/settings.py` 模式）、每頁容量行數（需由範本實測版面計算）、`.odt` 範本套版的具體技術手法（LibreOffice macro／欄位取代／模板變數注入）留給 research/planner 決定。
- 官方表格欄位與 `AppealDraft` 資料模型的完整逐欄對應表（如「醫令序」「內容」「數量」「金額」「理由」如何從 `p1-p9` 段落與 `DeductionRecord` 取得）留給 planner 在 PLAN.md 中詳細列出。
- 第三聯「中央健康保險署填列」欄位（核定/複核/初核/審查委員）留空的具體排版處理方式（完全不印該區塊 vs 印出空白表格供人工填寫）留給 planner 決定，兩者皆符合「系統不產出健保署複核結果」的原則。

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 官方紙本範本（版面依據，MANDATORY）
- `officialdocument/電子申復文件格式/30396_4_無刪除線1050105-PDF門診診療費用申復清單-.pdf` — 官方三聯式範本 PDF（105.04.01 修訂版），版面欄位逐一核對基準
- `officialdocument/電子申復文件格式/30396_1_1050105-1門診診療費用申復清單.odt` — 可編輯 ODF 範本，套版依據來源（D-02）
- `officialdocument/電子申復文件格式/30396_2_1050105-1門診診療費用申復清單.pdf` — 另一版本 PDF 範本（供交叉核對欄位）
- `officialdocument/電子申復文件格式/30396_3_無刪除線1050105-OD-門診診療費用申復清單-.odt` — 無刪除線版 ODT

### 資料契約（Phase 7 產出，本 phase 消費）
- `src/elc_audit_engine/generators/appeal.py` — `AppealDraft`／`AppealSection` dataclass 定義（case_class/case_seq/order_seq/order_code/visit_date/fee_year_month/deduction_upper_bound/reason1/reason2/p6_points 等欄位）；`render_appeal_markdown`／`render_appeal_json`／`write_appeal` 為既有輸出通道的參考實作模式
- `src/elc_audit_engine/generators/appeal_xml.py` — 既有電子上傳 XML 輸出通道（tdata/ddata/pdata），供欄位對應參考，但**不是**本 phase 要修改或依賴的目標

### 工具鏈參考（D-01，Phase 2 既有慣例）
- `src/elc_audit_engine/rule_repository/docx_tree/doc_converter.py` — Phase 2 既有的 LibreOffice headless 批次轉檔實作，本 phase 的 soffice 呼叫方式應比照此檔案的 subprocess 呼叫慣例（逾時處理、錯誤語意等）

### 專案規劃文件
- `.planning/ROADMAP.md` Phase 11 — Goal／Depends on／Success Criteria（本 phase 的範圍與驗收標準）
- `.planning/REQUIREMENTS.md` REQ-paper-appeal-print — 完整需求敘述與驗收標準

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `AppealDraft`（`src/elc_audit_engine/generators/appeal.py:66`）：本 phase 唯一的資料輸入來源，dataclass 已含官方表格所需的絕大部分案件層與醫令層欄位（案件分類、流水號、醫令代碼、核減上界、申復理由等）
- `safe_filename()`（`src/elc_audit_engine/safe_paths.py`）：既有輸出檔名安全防線（P1-3），若本 phase 產出的 PDF 檔名含案件識別碼，應沿用此函式而非重新實作

### Established Patterns
- **一案一檔案輸出慣例**：`write_report`（Phase 6）、`write_appeal`（Phase 7）皆為「一個案件產生一個輸出檔」的模式，本 phase 的 PDF 產生器應延續此慣例，不额外設計批次輸出格式
- **LibreOffice headless 工具鏈**：Phase 2 `doc_converter.py` 已證明 `soffice --headless` 批次轉檔在本專案環境可靠運作，D-01/D-02 延續此路徑而非引入新工具鏈風險
- **誠實降級哲學**（貫穿全專案）：OCR 不猜欄位、核減紙本不硬結構化、故障不偽裝業務結論。本 phase 若遇到 `AppealDraft` 缺少院所層欄位或欄位對應不上官方格式時，應遵循同一哲學——明確報錯或標記待補，不得憑空填入不存在的資料

### Integration Points
- 輸入：`AppealDraft`（Phase 7，`build_appeal_draft` 產出，已存在）＋新增的院所基本資料 config（D-04）
- 輸出：新的 PDF render 函式（暫定命名留給 planner，比照 `render_appeal_markdown`／`render_appeal_json` 的命名慣例，如 `render_appeal_pdf` 或 `render_appeal_print`）
- 不涉及 `server.py` 任何既有端點的修改——本 phase 範圍是否新增列印用 API 端點，或僅提供背景腳本（比照 `scripts/build_appeal_xml.py` 的模式）留給 planner 決定，CONTEXT.md 未鎖定此點

</code_context>

<specifics>
## Specific Ideas

- 使用者原始需求：「已有數位版本可以使用影像排入與一般列印出紙本」——明確指向「排入官方表格版式」而非自由排版，這是 D-02（直接套用官方 `.odt` 範本）的直接依據。
- 使用者強調「一般紙本抽審與申復」是與「已建連結 HIS 啟用電子抽審與申復」並列的**兩種情境**，不是取代關係——因此本 phase 不修改任何既有電子流程程式碼，純新增輸出通道。

</specifics>

<deferred>
## Deferred Ideas

- **紙本抽審清單（非申復清單）的列印**——使用者原始需求提到「紙本抽審與申復」，但官方三聯式範本查到的是「申復清單」（核減後的申復流程）。若健保署對「抽審清單」本身（核減前的抽審通知）也有官方紙本格式且需要列印，這是本 phase 範圍外的另一個潛在需求，未在本次討論中確認是否存在對應官方範本。留待使用者未來提出時另開 phase 或擴充本 phase 範圍。
- **第三聯健保署複核結果回填**（核定/複核/初核/審查委員欄位）——本 phase 只負責院所端產出申復清單供列印寄送，健保署收到紙本後複核填寫、寄回第三聯的流程屬院所行政作業，非本系統範圍（呼應 ROADMAP.md「Out of Roadmap Scope」中「院所行政前置申請作業」的既有排除慣例）。

### Reviewed Todos (not folded)
None — no pending todos matched this phase (`gsd-sdk query todo.match-phase 11` returned 0 matches).

</deferred>

---

*Phase: 11-paper-appeal-print*
*Context gathered: 2026-08-08*
