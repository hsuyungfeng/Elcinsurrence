# Phase 11: 紙本申復清單列印 - Research

**Researched:** 2026-08-08
**Domain:** ODT 模板套版 → LibreOffice headless PDF 渲染（LibreOffice 24.2.7.2 / Python 3.12 / uv / pytest）
**Confidence:** MEDIUM-HIGH（核心模板結構與工具鏈已實機驗證；布局壓縮參數與資料缺口為主要未定項）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### 排版工具鏈
- **D-01：採 LibreOffice/`soffice --headless` 套版**，延續 Phase 2（docx-tree 索引器）已驗證可用的工具鏈慣例，不引入新的重量級 Python PDF 套件（如 reportlab）。
- **D-02：直接拿現成官方 `.odt` 範本套版**——`officialdocument/電子申復文件格式/30396_1_1050105-1門診診療費用申復清單.odt`（可編輯版，ODF XML 可解析）作為排版依據來源，而非憑空用程式碼繪製表格框線。版面與官方 `30396_4_無刪除線1050105-PDF門診診療費用申復清單-.pdf` 範本逐欄核對一致（見 ROADMAP.md Phase 11 Success Criteria 1）。

#### 三聯處理
- **D-03：一次列印產生三頁 PDF**，每頁對應官方一聯（第一聯醫療院所存查／第二聯衛生福利部中央健康保險署存查／第三聯代付款清單）。三聯共用相同的醫令明細內容；差異僅在第三聯多出「中央健康保險署填列」核定／複核／初核／審查委員欄位（該欄留空，屬健保署複核後填列，非系統產出範圍）。院所端列印後自行裁切或使用複寫紙列印，符合現行「一份 PDF 對應一案件」的系統慣例（比照 `write_appeal`／`write_report` 一案一檔案）。

#### 院所基本資料來源
- **D-04：新增 config 設定檔**（如 `config/facility.json` 或比照 `config/settings.py` 的環境變數模式，交由 research/planner 決定具體形式）存放固定不變的院所層欄位：代號字碼、醫療院所名稱、地址、負責醫師姓名等。
- **D-05：案件層欄位（審查科別、原申報類別/日期、年度月份頁數、流水號等）由 `AppealDraft` 或 `CaseStore` 資料推導或作為生成函式參數傳入**，不寫死在 config——這些每案不同。`AppealDraft.case_class` 對應官方「案件分類」欄（源自 D-14d 欄位 5／申報 XML `d1`），可直接沿用。

#### 超行分頁
- **D-06：醫令明細行數超過單頁容量時自動分頁，每頁重複院所層欄位與表頭**，頁數欄（官方表格本身就有「頁數」欄位）依序遞增。符合官方紙本作業「多頁申復清單本來就常見」的實務慣例，非系統自創行為。

### Claude's Discretion
- 具體 config 檔案格式（JSON vs 環境變數 vs 沿用 `config/settings.py` 模式）、每頁容量行數（需由範本實測版面計算）、`.odt` 範本套版的具體技術手法（LibreOffice macro／欄位取代／模板變數注入）留給 research/planner 決定。
- 官方表格欄位與 `AppealDraft` 資料模型的完整逐欄對應表（如「醫令序」「內容」「數量」「金額」「理由」如何從 `p1-p9` 段落與 `DeductionRecord` 取得）留給 planner 在 PLAN.md 中詳細列出。
- 第三聯「中央健康保險署填列」欄位（核定/複核/初核/審查委員）留空的具體排版處理方式（完全不印該區塊 vs 印出空白表格供人工填寫）留給 planner 決定，兩者皆符合「系統不產出健保署複核結果」的原則。

### Deferred Ideas (OUT OF SCOPE)
- **紙本抽審清單（非申復清單）的列印**——使用者原始需求提到「紙本抽審與申復」，但官方三聯式範本查到的是「申復清單」（核減後的申復流程）。若健保署對「抽審清單」本身（核減前的抽審通知）也有官方紙本格式且需要列印，這是本 phase 範圍外的另一個潛在需求，未在本次討論中確認是否存在對應官方範本。留待使用者未來提出時另開 phase 或擴充本 phase 範圍。
- **第三聯健保署複核結果回填**（核定/複核/初核/審查委員欄位）——本 phase 只負責院所端產出申復清單供列印寄送，健保署收到紙本後複核填寫、寄回第三聯的流程屬院所行政作業，非本系統範圍（呼應 ROADMAP.md「Out of Roadmap Scope」中「院所行政前置申請作業」的既有排除慣例）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REQ-paper-appeal-print | 新增 PDF 排版輸出通道：直接消費既有 `AppealDraft`（不重建資料模型），版面與官方三聯式範本逐欄一致，三聯版式差異正確反映 | D-01/D-02 工具鏈與模板結構已實機驗證（見 Summary、Standard Stack、Code Examples）；三聯版式差異**發現與 CONTEXT D-03 描述相反**（實際為第二聯含核定欄，見 Open Questions #1）；資料契約缺口（姓名/身份證字號/傷病名稱/數量/金額）已查明來源選項（見 Open Questions #2） |

</phase_requirements>

## Summary

本 phase 是既有電子申復流程（Markdown/JSON/申復 XML）之外新增的一條**紙本輸出通道**：把 Phase 7 的 `AppealDraft`（＋院所層 config）排版成官方三聯式「門診醫療費用點數申復清單」可列印 PDF。工具鏈（D-01/D-02）已鎖定：`soffice --headless` + 官方 `.odt` 範本。

**本研究的核心事實（全部經由直接解開官方 .odt/.pdf 實證）：**

1. **官方 ODT 結構規整、無占位符/無欄位（field/variable）**——「套版」只能靠**直接編輯 content.xml 的表格單元格文本**。每聯＝「標題段 + 頭部資訊表(1列) + 主明細表(18列) + 說明表(4列)」共 3 個表格，聯與聯之間以 `text:soft-page-break` 分隔；主表結構固定為「row0 大標題 + row1 欄位表頭 + row2~row16 共 **15 個空資料列** + row17 合計列」。這直接回答兩個委託問題：**每頁容量＝15 行**，**分頁＝複製聯組結構並插入分頁符**。[VERIFIED: 本 session unzip + ET 解析]

2. **工具鏈建議：stdlib `xml.etree.ElementTree` + `zipfile` 直接編輯 content.xml，重打包 .odt 後交給 soffice 轉 PDF**——已實機 spike 驗證整條管線（注入院所/醫令文本 → PDF 文本層可提取）。不引入 odfpy（舊、重）、不用 UNO（headless 服務化易碎）、不碰 reportlab（D-01 已排除）。命名空間須先從根元素註冊 22 個前綴；`mimetype` 必須為 zip 首個條目且不壓縮。[VERIFIED: spike 實驗]

3. **重大版面風險：官方 ODT 直接轉 PDF 是 9 頁（每聯 3 頁），不是 3 頁**——官方 ODT 模板的資料列行高約 45~50pt、標題下有 3 個空段、頭部表前後有大量空隙，遠比官方 PDF 范本（30396_4，每聯 1 頁、資料列行高約 27pt）鬆散。D-03 的「三頁 PDF」必須靠**模板布局壓縮**達成。研究階段的壓縮實驗（固定行高 0.36in、字號 6pt、邊距 0.05in）仍得 9 頁——溢出點已定位（主表差約 1 行、說明表過高、無效空隙），但**精確壓縮參數需在實現階段以迭代實驗收斂**。這是本 phase 的最大技術風險。[VERIFIED: soffice 轉檔實驗]

4. **CONTEXT D-03 的「第三聯多出核定/複核/初核/審查委員欄」與實際模板相反**：兩個官方 ODT 與兩個官方 PDF 都顯示「核定/複核/初核/審查委員」空白列在**第二聯**（健保署存查聯）的說明表內，第三聯反而沒有。系統仍不填該欄（留空供人工），但 planner/discuss 需確認版式敘述。[VERIFIED: ODT+PDF 交叉比對]

5. **資料契約有缺口**：官方清單必填的「身份證字號/姓名/傷病名稱/審查科別」與醫令層「數量/金額」**不在 `AppealDraft` 中**；`DeductionRecord.id_number` 已被健保署遮罩後 4 碼。這些欄位存在於申報 XML 解析結果（`SubmissionCase.patient_name` d49、`primary_diagnosis` d19、`clinic` d8、`OrderRecord.total_qty` p10/`points` p12）或 `CaseStore.payload`，需在 PLAN 決定「從 CaseStore join」或「誠實降級留空」。[VERIFIED: models.py + server.py 讀碼]

**Primary recommendation:** 以「**官方 ODT →（一次性）布局壓縮基準模板 → 每次生成時 ET 注入 content.xml → zip 重打包 → soffice 轉 PDF**」為主架構；PDF 輸出目錄沿用 `data/output/`（已在 .gitignore），檔名經 `safe_filename()`（P1-3）校驗。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 院所層欄位（代號字碼/院所名稱/地址/負責醫師） | 資料層（config/facility.json） | — | 固定不變、每院所一份，非案件資料；JSON + env 可覆蓋路徑 |
| 案件層＋醫令層欄位組裝 | API/Backend（generators 層） | 資料層（CaseStore/AppealDraft） | 每個欄位有明確來源（AppealDraft/DeductionRecord/SubmissionCase/config），組裝邏輯屬 render 層職責 |
| ODT XML 注入（content.xml 編輯） | Backend（新 `render_appeal_pdf` 模組） | — | 純 Python、無網路、可單元測試 |
| ODT→PDF 轉換 | 外部工具（soffice headless） | — | D-01 鎖定；Phase 2 已驗證；subprocess 封裝比照 doc_converter.py |
| PDF 版面驗證 | Backend（測試層，pypdf） | 外部工具（pdftotext，開發機可用） | 測試斷言頁數/文本，不需人眼 |
| 輸出檔名安全（P1-3） | Backend（safe_paths.safe_filename） | — | 既有防線，直接沿用 |
| 列印入口 | CLI 背景腳本（scripts/build_appeal_print.py） | Flask API（可選擴充） | 比照 build_appeal_xml.py 先例；不強迫改 server.py |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `xml.etree.ElementTree` | 3.12（內建） | 讀寫 content.xml、注入文本 | 零依賴、spike 實測可行；ET 文本節點自動轉義（安全） |
| Python stdlib `zipfile` | 3.12（內建） | ODT 重打包 | 零依賴；注意 mimetype 首條目不壓縮 |
| LibreOffice `soffice` | 24.2.7.2 | ODT→PDF headless 轉換 | D-01 鎖定；本機已裝（24.2.7.2，orchestrator 已驗證） |
| `safe_paths.safe_filename` | 既有（P1-3） | PDF 檔名校驗 | 專案統一防線，禁止重造 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pypdf` | 6.15.0（PyPI 最新，本 session 確認存在） | 測試中提取 PDF 頁數/文本 | PDF 版面自動化斷言（需 `uv add --dev pypdf`；本次沙箱無法實裝驗證中文提取，見 Assumptions A2） |
| `pdftotext`（poppler-utils） | 24.02.0（本機已裝） | 開發機快速人工核對 PDF 文本 | 不需進 pyproject；CI 若無則以 pypdf 取代 |
| `lxml` | 6.1.1（.venv 現有，**ocr extra 的傳遞依賴**） | 高階 XML 處理（可選） | **不建議作為本 phase 主依賴**——目前未在 pyproject 主依賴，乾淨環境（不裝 ocr）會缺；若要用須顯式 `uv add lxml`。性能優於 stdlib ET，但 650KB XML 兩者皆 <1s |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 直接編輯 content.xml | odfpy（`odf.opendocument`） | odfpy 功能完整但專案依賴多、釋出節奏慢；模板結構已證實規整，ET 足夠 |
| 直接編輯 content.xml | LibreOffice UNO / pyuno 宏 | 需先啟動 `soffice --accept` socket 服務、批次/CI 易碎；模板無欄位可替換，UNO 優勢無從發揮 |
| soffice 轉 PDF | reportlab / weasyprint | D-01 已排除（重量級、需自繪框線） |
| 版面壓縮基準模板 | 每次生成動態壓縮 | 壓縮參數一旦調好應固化成範本入庫（比照 Phase 2 docx 預處理），與注入邏輯解耦、可人工複核 |

**Installation:**
```bash
uv add --dev pypdf        # PDF 驗證（測試用）
# soffice / pdftotext 為系統套件，不經 uv 管理
```

**Version verification:** `soffice 24.2.7.2`、`pypdf 6.15.0`（本 session 自 PyPI 下載確認）、`pdftotext 24.02.0`、`uv 0.9.16`、`pytest 9.1.1`、`Python 3.12.3`。lxml 6.1.1 已存在於 .venv（ocr extra 傳遞）。[VERIFIED: 本 session 環境探測]

## Architecture Patterns

### System Architecture Diagram

```
                    ┌────────────────────────────────────────────────────────────┐
                    │ 產生端（每案件一次）                                         │
  AppealDraft ──────► │ render_appeal_print(                                       │
  (Phase 7, .json)   │   appeal_json / CaseStore payload,                         │
  facility config ──► │   facility: FacilityConfig,                               │
  (config/facility.json)│   template_odt: path,                                    │
                    │   output_pdf: path) → pdf_path                              │
                    │  ┌──────────────────────────────────────────────────────┐  │
                    │  │ ① 欄位組裝（純函式，可單測）                          │  │
                    │  │   院所層 config + 案件層 AppealDraft/CaseStore        │  │
                    │  │   醫令行 → 15 欄 row dict；分頁決定（>15 行→續頁）     │  │
                    │  └──────────────────────────────────────────────────────┘  │
                    │  ┌──────────────────────────────────────────────────────┐  │
                    │  │ ② content.xml 注入（stdlib ET，可單測）              │  │
                    │  │   · 註冊 22 命名空間 → 找表格/列/單元格 → 設 text:p   │  │
                    │  │   · 分頁：複製聯組結構（標題+頭部表+主表表頭）        │  │
                    │  │   · 頁數欄遞增、合計/說明表僅末頁                     │  │
                    │  └──────────────────────────────────────────────────────┘  │
                    │  ┌──────────────────────────────────────────────────────┐  │
                    │  │ ③ zip 重打包（mimetype 首條目不壓縮）→ .odt          │  │
                    │  └──────────────────────────────────────────────────────┘  │
                    └──────────────────────────┬───────────────────────────────────┘
                                               ▼
                    ┌────────────────────────────────────────────────────────────┐
                    │ ④ soffice --headless --convert-to pdf（subprocess，         │
                    │    比照 doc_converter.py：-env:UserInstallation / timeout    │
                    │    / error 語意）→ 輸出 PDF（data/output/，safe_filename）    │
                    └────────────────────────────────────────────────────────────┘
                                               ▼
                    ┌────────────────────────────────────────────────────────────┐
                    │ ⑤ 驗證（測試層）：pypdf 斷言頁數=3×N、關鍵欄位文本出現       │
                    └────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure
```
src/elc_audit_engine/
└── generators/
    ├── appeal.py            # 既有（AppealDraft，不動）
    ├── appeal_xml.py        # 既有（電子上傳 XML，不動）
    └── appeal_print.py      # 新增：render_appeal_print + 欄位組裝
        ├── field_mapping.py # 新增：官方欄位 ← AppealDraft/CaseStore/config
        ├── odt_fill.py      # 新增：ET 注入 content.xml + zip 重打包
        └── (可選) template.py # 一次性「布局壓縮基準模板」產生器
config/
└── facility.json            # 新增：院所層欄位（D-04）
scripts/
└── build_appeal_print.py    # 新增：CLI 入口（比照 build_appeal_xml.py）
tests/
└── test_appeal_print.py     # 新增：Wave 0
```

### Pattern 1: content.xml 注入（spike 已驗證）
**What:** 用 stdlib ET 解析官方 ODT 的 content.xml，把資料寫入指定表格單元格的 `<text:p>`；序列化後重打包 ODT。
**When to use:** 模板無欄位/占位符時的唯一可靠做法（本模板 100% 屬此類——實測無 `text:placeholder`/`text:field`/`text:variable`）。
**Key points:**
- 解析前從根元素抓 `xmlns:*` 屬性逐一 `ET.register_namespace()`（22 個前綴），否則序列化會變 `ns0:ns1:` 前綴（語意合法但可讀性差）。
- 寫入值用 `p.text = value`（ET 自動轉義 `<>&`）——**嚴禁字串插值**（模板注入，見 Security）。
- 空的表格單元格＝`<table:table-cell><text:p text:style-name="Pxx"/></table:table-cell>`；設定 `cell.find('text:p')` 的 `.text` 即可，樣式屬性保留。
- zip 打包：`mimetype` 必須第一個寫入且 `ZIP_STORED`（不壓縮），其餘 `ZIP_DEFLATED`；否則部分讀取器/soffice 拒絕開啟。

### Pattern 2: soffice 轉換呼叫（比照 Phase 2 doc_converter.py）
**What:** `soffice -env:UserInstallation={profile_dir} --headless --norestore --nolockcheck --convert-to pdf --outdir {out} {odt}`。
**When to use:** 每次生成的最後一步；profile 目錄放輸出目錄下（測試用 tmp_path 自動隔離）。
**Key points:** 單檔轉換 timeout 120s；`soffice --version` 成功不代表 headless 轉檔可用——沿用 `soffice_is_functional()` 真轉檔探測作為測試 skip 條件（Phase 2 既有）。

### Pattern 3: 分頁（D-06）
**What:** 醫令 > 15 行時，在每聯內於「主表」之後複製「標題段 + 頭部表 + 主表表頭(2 行)」，新資料列填入複製的表格，`text:soft-page-break` 分隔；合計列與說明表只出現在該聯最後一頁；每頁「頁數」欄依序遞增（x/y）。
**When to use:** 一案件醫令明細超過單頁容量（每頁 15 行）。
**Key points:** 官方實務本就允許多頁清單（CONTEXT D-06）；頁數欄在頭部表最後兩個單元格。

### Anti-Patterns to Avoid
- **字串插值塞 XML**：`content.replace("{{order_code}}", order_code)` —— 惡意/特殊字元直接注入 ODF，破壞文件甚至產生非法 XML。一律 ET 文本節點。
- **把整份官方 ODT 當「純淨基準」反覆複製**：layout 壓縮應一次做好、固化成基準模板入庫，不要在每次生成時重複調參。
- **在 server.py 強加列印端點**：Phase 11 無既有端點修改需求；先出 CLI 腳本，API 端點留待用戶明確要求（見 Open Questions #6）。
- **假設官方 ODT 轉 PDF = 3 頁**：實測是 9 頁，必須先壓縮（見 Open Questions #3）。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ODT zip 打包 | 自寫 ODF 壓縮容器邏輯 | `zipfile` + mimetype 首條目不壓縮規則 | ODF 容器規範細節易漏（mimetype 位置/壓縮旗標），寫錯 soffice 直接拒開 |
| XML 字元轉義 | 自寫 `escape()`/replace | `xml.etree.ElementTree` 文本節點 | ET 自動處理 `&<>`，自寫轉義必漏邊角（如 `]]>`） |
| PDF 文本/頁數提取 | 自寫 PDF 解析 | `pypdf`（測試）、`pdftotext`（開發核對） | PDF 文字層提取是深坑（字體編碼/ToUnicode），不該自造 |
| PDF 排版/中文字體渲染 | 自寫繪表框線/嵌字 | 官方 ODT + LibreOffice | D-01/D-02 已鎖定；LibreOffice 已處理 CJK 字體與版面 |
| 檔名安全 | 重造 sanitize 函式 | `safe_paths.safe_filename`（P1-3） | 專案已踩過路徑穿越（P1-3），白名單校驗後拒絕是既定語意 |

**Key insight:** 本 phase 的價值全在「官方版式 + 資料正確填入」，而 ODF/PDF 底層全是「看起來簡單、邊角致命的格式」——每一層都該用現成可靠元件，自寫只會把風險堆回排版正確性上。

## Common Pitfalls

> 以下六類皆出自本 session 實測（soffice 轉檔/bbox 量測）與專案讀碼，非泛泛之談。

### Pitfall 1: 官方 ODT 渲染非每聯一頁
**What goes wrong:** 直接拿官方 ODT 轉 PDF 得到 9 頁（每聯 3 頁），不符合 D-03「三頁」。
**Why it happens:** 模板資料列行高（約 45~50pt）≈ 官方 PDF（約 27pt）的 1.7~1.9 倍；標題後 3 個空段、頭部表前後各約 90~170pt 空隙。
**How to avoid:** 一次性產出「壓縮基準模板」（縮邊距、刪空段、固定列高、說明表壓字號/縮 frame），先達成「官方 ODT 轉 PDF = 3 頁」再談注入。
**Warning signs:** `pdfinfo` 頁數 ≠ 3；合計列/說明表被推到下一頁。

### Pitfall 2: 模板注入 / XML 損毀
**What goes wrong:** 申復理由等自由中文含 `<`、`&` 時，字串插值會弄壞 content.xml，soffice 轉檔失敗或輸出被截斷的 PDF。
**Why it happens:** 欄位值來自病歷/核減檔（外部輸入），不可信。
**How to avoid:** 全部經 ET 文本節點寫入；序列化後做一次「soffice 真轉檔」驗證（fail-fast）。
**Warning signs:** 生成 PDF 空白、轉檔 exit 非 0。

### Pitfall 3: mimetype 未置首/被壓縮
**What goes wrong:** ODT 打不開或 soffice 報「corrupt file」。
**Why it happens:** ODF 規範要求 mimetype 為第一個條目且不壓縮。
**How to avoid:** 打包順序固定 mimetype 第一、`ZIP_STORED`；用 `zipfile.ZipFile.writestr('mimetype', ..., compress_type=ZIP_STORED)`。
**Warning signs:** soffice 轉檔回 non-zero。

### Pitfall 4: ET 命名空間未註冊
**What goes wrong:** 序列化後出現 `ns0:` 前綴；LibreOffice 通常仍能讀（URI 不變），但 diff/人工核對模板變難，且部分工具鏈（如 odfpy 消費者）可能挑剔。
**How to avoid:** 解析前從根元素註冊全部 22 個前綴。
**Warning signs:** 產出 XML 含 `ns0`/`ns1` 標籤。

### Pitfall 5: 資料缺欄位卻硬填
**What goes wrong:** 「身份證字號」「姓名」「數量」「金額」在 AppealDraft 中不存在，硬湊會輸出空白或錯誤資料。
**Why it happens:** Phase 7 資料模型只保留申復所需欄位（見 Open Questions #2）。
**How to avoid:** PLAN 明訂欄位來源（CaseStore.payload join / 參數注入）或誠實留空＋警告（誠實降級哲學）。
**Warning signs:** 產出清單的保險對象欄位全空。

### Pitfall 6: PHI 流入 git/日誌
**What goes wrong:** 生成的 PDF 含患者姓名/身分證字號，若輸出目錄未 gitignore 或錯誤訊息含欄位全文，個資進版控/日誌。
**Why it happens:** P0-3 教訓（data/output 曾未 gitignore）。
**How to avoid:** 輸出沿用 `data/output/*`（已 gitignore）；錯誤訊息比照 `AppealXmlEncodingError` 只記欄位名與碼位、不記全文。
**Warning signs:** `git status` 出現輸出檔。

## Code Examples

Verified patterns from this session's spike (pipeline 全通、PDF 文本層可驗證):

### 1. ODT 注入（stdlib ET，spike 實測成功）
```python
import xml.etree.ElementTree as ET
import re

# 註冊根元素上全部命名空間（22 個前綴）
raw = open("content.xml", encoding="utf-8").read()
root_el = re.search(r"<office:document-content[^>]*>", raw).group(0)
for m in re.finditer(r'xmlns:([A-Za-z0-9_]+)="([^"]+)"', root_el):
    ET.register_namespace(m.group(1), m.group(2))
for m in re.finditer(r'xmlns="([^"]+)"', root_el):
    ET.register_namespace("", m.group(1))

tree = ET.parse("content.xml")
root = tree.getroot()
body = root.find("office:body/office:text")  # 需以 {uri}tag 完整寫法
tables = body.findall("table:table")

def set_cell_text(cell, value: str) -> None:
    p = cell.find("text:p")
    if p is None:
        p = ET.SubElement(cell, "text:p")
    for span in p.findall("text:span"):  # 清掉舊的 span 殘留
        p.remove(span)
    p.text = value                       # ET 自動轉義 < & >（安全）

head = tables[0]  # 第一聯頭部表（17 cells）
cells = head.find("table:table-row").findall("table:table-cell")
set_cell_text(cells[1], facility.code)          # 代號字碼
set_cell_text(cells[3], facility.name)          # 醫療院所名稱
set_cell_text(cells[5], case_fields.clinic)     # 審查科別

main = tables[1]  # 第一聯主表（18 rows：0 標題/1 表頭/2-16 資料/17 合計）
datarow = main.findall("table:table-row")[2].findall("table:table-cell")
set_cell_text(datarow[0], draft.case_class)     # 案件分類
set_cell_text(datarow[1], draft.case_seq)       # 流水號
set_cell_text(datarow[5], order.code)           # 醫令序
# ... 依 15 欄順序填入
```

### 2. ODT 重打包（spike 實測成功）
```python
import zipfile
with zipfile.ZipFile("filled.odt", "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("mimetype", b"application/vnd.oasis.opendocument.text",
               compress_type=zipfile.ZIP_STORED)   # 首條目不壓縮
    z.write("META-INF/manifest.xml", "META-INF/manifest.xml")
    z.write("meta.xml", "meta.xml"); z.write("settings.xml", "settings.xml")
    z.write("styles.xml", "styles.xml")
    z.writestr("content.xml", ET.tostring(root, encoding="UTF-8",
                                          xml_declaration=True))
```

### 3. soffice 轉 PDF（比照 Phase 2 doc_converter.py 慣例）
```python
import subprocess, os
profile_dir = os.path.join(output_dir, ".lo_profile")
os.makedirs(profile_dir, exist_ok=True)
result = subprocess.run(
    ["soffice", f"-env:UserInstallation={Path(profile_dir).as_uri()}",
     "--headless", "--norestore", "--nolockcheck",
     "--convert-to", "pdf", "--outdir", output_dir, filled_odt],
    capture_output=True, timeout=120)
# returncode != 0 → 拋錯；輸出檔不存在 → 拋錯（比照 convert_doc_files）
```

### 4. 驗證（測試斷言）
```python
from pypdf import PdfReader
r = PdfReader(pdf_path)
assert len(r.pages) == 3            # D-03：三頁（每聯一頁；分頁時 = 3×N）
text = "".join(p.extract_text() or "" for p in r.pages)
assert "代號字碼" in text and "測試醫療院所" in text and "01015C" in text
```

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | [ASSUMED] 布局壓縮可達「官方 ODT 渲染每聯一頁」（溢出點已 VERIFIED，壓縮參數未收斂） | Summary / Open Q#3 | 若壓縮後仍無法每聯一頁，D-03 需重新詮釋（如「每聯可多頁但以 soft-page-break 分隔」）——溢出點已定位（主表差約 1 行、說明表過高），方向可信但參數未收斂 |
| A2 | [ASSUMED] pypdf 能提取 LibreOffice 產出 PDF 的中文文本層（pdftotext 路徑已 VERIFIED） | Standard Stack / Validation | 本次沙箱 .venv 唯讀無法實裝 pypdf 驗證；備案是 pdftotext（本機已驗證能提取）或改在 ODT XML 層斷言 |
| A3 | [VERIFIED] 每頁容量固定 15 行（row2~16 結構）；「壓縮後容量不變」為 [ASSUMED] | Architecture Patterns | 壓縮後若行高縮小，容量理論上可增，但官方版式即 15 行/頁，建議固定不增 |
| A4 | [ASSUMED] 資料缺欄位可經 CaseStore.payload join 取得 | Summary / Open Q#2 | 若 payload 未存 submission 層欄位，則只能誠實留空或要求使用者補輸入——影響驗收標準 1（「身份證字號/姓名/傷病名稱」欄） |
| A5 | [ASSUMED] `.odt` 模板屬版控資產、內容可信（模板現已 git-tracked，VERIFIED） | Security | 若模板被竄改（含惡意 ODT），注入層無法防——靠 git 版控＋生成前校驗模板 hash |

## Open Questions

1. **「核定/複核/初核/審查委員」欄位實際在第二聯而非第三聯（與 CONTEXT D-03 敘述相反）**
   - What we know: [VERIFIED] 官方 ODT 30396_1/30396_3 的**第二聯**說明表 row1 有該欄；官方 PDF 30396_2/30396_4 第二頁亦有（pdftotext 驗證）。第三聯反而無。
   - What's unclear: CONTEXT D-03 的敘述是否為使用者口誤或不同範本版本。
   - Recommendation: 實作以官方模板為準（系統不填、保留空白表格）；planner 在 PLAN 中註記此差異，PLAN 完成後由 verify/discuss 與使用者確認。

2. **官方清單必填欄位在 AppealDraft 中缺漏的來源**
   - What we know: [VERIFIED] `AppealDraft` 僅含 case_class/case_seq/order_seq/order_code/visit_date/fee_year_month/deduction_upper_bound/reason1/reason2/p6_points 等；無姓名/身分證字號/傷病名稱/數量/金額/審查科別。`DeductionRecord.id_number`（欄 9）已遮罩後 4 碼。`SubmissionCase` 有 patient_name(d49)/primary_diagnosis(d19)/clinic(d8)/orders（`OrderRecord.total_qty` p10、`points` p12）。`CaseStore.payload` 是上傳案件 JSON 快照（appeal 流程 `_to_appeal_case` 的 patient_name 為 None）。[VERIFIED: models.py + server.py 讀碼]
   - What's unclear: CaseStore 中 appeal 案件的 payload 實際存了哪些欄位；抽審/核減案件能否按 case_class+case_seq join 到申報資料。
   - Recommendation: PLAN 第一波先做「欄位來源盤點」任務：實測一份 appeal 案件在 CaseStore 的 payload 內容，決定 join 或降級；遵守誠實降級——**不得憑空填患者資料**。

3. **布局壓縮參數（官方 ODT → 每聯一頁）**
   - What we know: [VERIFIED] 官方 ODT 轉 PDF＝9 頁；溢出點：標題後 3 空段（約 170pt）、頭部表與主表間空隙（約 88pt）、主表差約 1 行、說明表含 7 條說明＋frame（高 2in）過高。實驗（固定列高 0.36in＋字號 6pt＋邊距 0.05in）仍 9 頁。
   - What's unclear: 精確的邊距/列高/字號/frame 組合。
   - Recommendation: 實現階段以「官方 PDF 30396_4 每聯一頁」為 Golden，用 bbox 測量迭代收斂；測試以「頁數=3」與「主表合計列與說明表同頁」為斷言。

4. **「原申報類別 □送核□補報」「原申報日期 年月日」如何填**
   - What we know: 頭部表含勾選式欄（□送核□補報）與「年月日」模板字樣。
   - What's unclear: 本系統抽審案件預設勾「送核」還是留白；原申報日期取 DeductionRecord.submit_date（欄 4）還是 fee_year_month。
   - Recommendation: 預設勾「□送核」（抽審即送核案件）並在 config 或參數提供覆寫；日期以 submit_date 為主、fee_year_month 備援。

5. **分頁後的「合計」與「說明表」位置**
   - What we know: D-06 要求每頁重複院所層欄位與表頭；主表 row17 是合計列。
   - What's unclear: 合計列與說明表應只出現在該聯最後一頁（研究建議），續頁僅重複「標題+頭部表+主表表頭+資料列」。
   - Recommendation: 採用「續頁不印合計/說明」；每聯最後一頁完整收尾。

6. **列印入口：CLI 腳本 vs Flask API 端點**
   - What we know: CONTEXT 明言不涉及 server.py 既有端點修改；`scripts/build_appeal_xml.py` 是既有 CLI 先例；server.py 已有 `/api/appeal/generate` 等端點模式。
   - What's unclear: 院所端是否要從 Web 介面觸發列印。
   - Recommendation: Phase 11 交付 CLI 腳本（可測、零 Flask 依賴）；API 端點列為可選 Wave（需使用者要求才做）。

7. **config 格式：JSON vs 環境變數**
   - What we know: `config/settings.py` 提供 env-var 覆寫路徑的先例（含 `load_llama_config()` 讀 JSON）；院所層欄位是結構化固定資料（約 5~8 欄）。
   - Recommendation: **`config/facility.json` + `settings.py` 增加 `FACILITY_CONFIG_PATH` env 覆寫 + `load_facility_config()`**（比照 llama_config 先例），JSON 適合多欄位結構、env 僅覆寫路徑。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| LibreOffice `soffice` | ODT→PDF（D-01） | ✓ | 24.2.7.2（本 session 再驗證） | 無——D-01 鎖定；缺則該功能測試 skip（`soffice_is_functional()` 真轉檔探測） |
| Python 3.12 + stdlib ET/zipfile | content.xml 注入/重打包 | ✓ | 3.12.3 | — |
| `pdftotext`（poppler-utils） | 開發核對 PDF 文本 | ✓ | 24.02.0 | pypdf（需加 dev 依賴） |
| `pypdf` | 測試斷言頁數/文本 | ✗（未安裝；本次沙箱 .venv 唯讀無法裝） | PyPI 最新 6.15.0 | `uv add --dev pypdf`（planner 列入 Wave 0） |
| `lxml` | （可選）XML 處理 | ✓（.venv 有 6.1.1，屬 ocr extra 傳遞依賴） | 6.1.1 | **不建議依賴**——須 `uv add lxml` 才可入主依賴 |
| odfpy / reportlab / pdfplumber / fitz | 不需 | ✗ | — | 不引進（D-01/D-02） |
| `uv` | 依賴管理 | ✓ | 0.9.16 | — |
| `pytest` | 測試 | ✓ | 9.1.1 | — |

**Missing dependencies with no fallback:** 無——本 phase 的核心工具（soffice/Python stdlib）齊備。pypdf 屬測試優化，加 dev 依賴即可。

**Missing dependencies with fallback:** `pypdf`（未裝）→ `uv add --dev pypdf`；若 CI 無 poppler 亦以 pypdf 覆蓋。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1（`pyproject.toml [tool.pytest.ini_options] testpaths=["tests"]`） |
| Config file | pyproject.toml（無 pytest.ini） |
| Quick run command | `uv run pytest tests/test_appeal_print.py -x` |
| Full suite command | `uv run pytest`（現行基線 374 passed / 2 skipped） |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REQ-paper-appeal-print | 欄位組裝純函式（官方欄 ← AppealDraft/CaseStore/config 對應正確；缺欄誠實降級） | unit | `pytest tests/test_appeal_print.py -k mapping -x` | ❌ Wave 0 |
| REQ-paper-appeal-print | content.xml 注入：院所欄/案件欄/醫令行/分頁複製/頁數欄/合計僅末頁（解析產出 XML 斷言） | unit（不觸 soffice，<30s） | `pytest tests/test_appeal_print.py -k odt -x` | ❌ Wave 0 |
| REQ-paper-appeal-print | 端到端：soffice 轉 PDF 後 pypdf 斷言**頁數＝3（×N）**、關鍵欄位文本（代號字碼/院所名稱/案件分類/流水號/醫令代碼）出現、身份證/姓名等 PHI 欄位依來源填入 | integration（soffice 不可用時 skip，比照 test_doc_converter `requires_soffice`） | `pytest tests/test_appeal_print.py -k e2e -x` | ❌ Wave 0 |
| REQ-paper-appeal-print | 三聯版式差異：第二聯說明表含「核定/複核/初核/審查委員」，第一/三聯無；系統不填該欄 | integration（PDF 文本） | `pytest tests/test_appeal_print.py -k copies -x` | ❌ Wave 0 |
| REQ-paper-appeal-print | 安全：欄位含 `<script>`/`&` 不破壞 ODT（轉檔成功）、檔名穿越被拒（safe_filename） | unit + integration | `pytest tests/test_appeal_print.py -k security -x` | ❌ Wave 0 |
| REQ-paper-appeal-print | config 載入：facility.json 缺檔 fail-fast、env 覆寫路徑 | unit | `pytest tests/test_appeal_print.py -k config -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_appeal_print.py -x`（或 `-k <task>`）
- **Per wave merge:** `uv run pytest`
- **Phase gate:** 全套件綠（含既有 374 基線）才 `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_appeal_print.py` — 上述全部測試檔（先紅後綠）
- [ ] `tests/conftest.py` 擴充 — `requires_soffice` skip 標記（比照 test_doc_converter.py 的 `soffice_is_functional()`）、`facility_config` fixture、`sample_appeal_draft()` fixture（構造 AppealDraft）
- [ ] 依賴：`uv add --dev pypdf`
- [ ] 基準資產：`officialdocument/電子申復文件格式/` 內加「壓縮基準模板」（`*_print_base.odt`，由一次性預處理腳本產出並入庫）——若模板預處理屬本 phase 範圍，則 Wave 0 需先產出該模板 + 其生成測試
- [ ] `config/facility.json` 範例檔（測試用 fixture，不落地正式 config）

## Security Domain

> `security_enforcement` 啟用（.planning/config.json 未顯式關閉）。

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | 否（CLI 腳本無網路面；若加 API 端點則沿用 server.py `require_api_key`/審計） | 本 phase 不新增端點 |
| V3 Session Management | 否 | — |
| V4 Access Control | 否（單機檔案輸出） | — |
| V5 Input Validation | **是** | 欄位值一律 ET 文本節點（防 ODF/XML 注入）；檔名 `safe_filename`（P1-3） |
| V6 Cryptography | 否 | — |
| V9 Logging | **是** | 錯誤訊息不含 PHI 欄位全文（比照 `AppealXmlEncodingError` 只記欄位名/碼位） |
| V12 File & Resources | **是** | 輸出目錄 gitignore（P0-3）；模板 hash 校驗（A5） |

### Known Threat Patterns for this Stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| ODT XML 注入（申復理由/病歷內容含 `<>&` 等 → 破壞 content.xml 或注入 ODF 結構） | Tampering | 全部值經 `ET` 文本節點寫入（自動轉義）；**嚴禁字串插值**；序列化後真轉檔驗證（fail-fast） |
| PHI 進 git（輸出 PDF 含姓名/身分證字號/病歷內容） | Information Disclosure | 輸出沿用 `data/output/*`（已 gitignore，`!data/output/.gitkeep`）；新輸出目錄必須同步 gitignore |
| PHI 進日誌（轉檔失敗訊息含欄位全文） | Information Disclosure | 錯誤訊息只記欄位名與失敗階段；不記錄 payload/欄位值 |
| 檔名路徑穿越（case_seq/order_seq 來自外部檔） | Tampering/Elevation | `safe_filename()` 校驗後拒絕（P1-3），不可清洗取代 |
| 身分證字號已遮罩（欄 9 後 4 碼）被誤當完整 | Integrity | 誠實降級：不猜測補全；PLAN 明訂「遮罩值照印」或「留空待人工」，不得重建完整字號 |
| 模板被竄改（供應鏈：官方 ODT 經版控） | Tampering | 模板入 git 版控；生成前校驗模板 sha256（與入庫值比對） |
| 輸出檔覆寫（同一 case_seq 多筆醫令共用檔名） | Integrity | 比照 `write_appeal` 的 `file_stem` 機制：`{case_seq}_{order_seq}` 或明確 overwrite 策略 |

## Sources

### Primary (HIGH confidence)
- **官方 ODT/PDF 模板（本機檔，直接解析）** — `officialdocument/電子申復文件格式/30396_1_1050105-1門診診療費用申復清單.odt`、`30396_3_無刪除線1050105-OD-門診診療費用申復清單-.odt`、`30396_2_1050105-1門診診療費用申復清單.pdf`、`30396_4_無刪除線1050105-PDF門診診療費用申復清單-.pdf`（unzip -l、ET 解析、pdfinfo/pdftotext 實測）
- **專案程式碼（本機，直接讀碼）** — `src/elc_audit_engine/generators/appeal.py`、`appeal_xml.py`、`src/elc_audit_engine/parsers/models.py`、`src/elc_audit_engine/safe_paths.py`、`src/elc_audit_engine/case_store/store.py`、`src/elc_audit_engine/rule_repository/docx_tree/doc_converter.py`、`config/settings.py`、`scripts/build_appeal_xml.py`、`server.py`、`.gitignore`、`pyproject.toml`
- **本 session 實機 spike** — ET 注入→zip 重打包→soffice 轉 PDF→pdftotext/pypdf 提取（/tmp/spike/*）

### Secondary (MEDIUM confidence)
- 無（本 phase 全為本機資產實測，無需外部 web 來源）

### Tertiary (LOW confidence)
- pypdf 中文文本提取能力（本次沙箱無法實裝驗證，標 A2）

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 核心工具鏈（ET/zipfile/soffice）已實機驗證；僅 pypdf 中文提取為 LOW（A2）
- Architecture: MEDIUM-HIGH — 模板結構與注入/分頁模式已確立；布局壓縮參數（A1/Q3）與資料缺口來源（Q2）未收斂
- Pitfalls: HIGH — 溢出版面、模板注入、mimetype、命名空間、PHI 五類均為本 session 實測/讀碼佐證

**Research date:** 2026-08-08
**Valid until:** 2026-09-07（30 天；LibreOffice/pypdf 為穩定件）
