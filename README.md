# Elcinsurrence 健保電子抽審與申復自動化輔助系統

`Elcinsurrence` 是一套專為健保門診抽樣與核減申復設計的自動化審核與申復輔助引擎（`elc-audit-engine`），提供雙軌處理介面（事前預審補強 ＋ 事後申復理由生成）與完整的 HIS 介面對接機制。

---

## 🌟 核心架構與雙軌工作流 (Dual-Workflow Architecture)

本系統支援兩大獨立運作介面與流程：

### 1. 📋 抽樣事前預審工作流 (Sampling Pre-audit Workflow)
- **目的**：於抽審清單送出健保署前，審核門診病歷並評估「醫令支持度」（✅ **充分** / ⚠️ **薄弱** / ❌ **裸奔**）。
- **流程**：導入抽樣 CSV 清單 ➔ 病歷 SOAP 解析 ➔ 三方邏輯比對 ➔ 自動提示病歷缺口與補強建議 ➔ 醫師完備病歷後送出抽審。
- **入口**：[`run_presubmission_check`](src/elc_audit_engine/pipeline.py) — **唯讀**，不產申復草稿、不寫檔（預審時尚無核減資料）。

### 2. ⚖️ 核減事後申復工作流 (Appeal Post-processing Workflow)
- **目的**：針對健保署核減不予核銷之刪減醫令，啟動多源證據自動彙整並生成申復檔案。
- **流程**：導入核減明細 ➔ 多源證據提取（門診 SOAP ＋ 檢驗 Lab ＋ 影像 Radiology ＋ 健保雲端病歷 EHR） ➔ 4 段式申復理由自動組裝 ➔ 導出申復 XML (p1~p9) / JSON 契約。
- **入口**：[`run_case_pipeline`](src/elc_audit_engine/pipeline.py) — 比對 ➔ 補強報告 ➔ 逐筆申復草稿，並寫出檔案。

> 兩條路徑共用 Phase 5 `compare_case`，故判定語意一致；分開的原因是**產出與副作用不同**（預審誤用整案管線會意外寫出申復草稿），對應目標架構圖 Cloud HIS 的 Review Service ／ Appeal Service 分離。

### ⚠️ 三種「非結論」狀態（呼叫端必須分辨）

系統故障不得偽裝成業務結論。`support_level` 為 `null` 時有兩種完全不同的成因：

| 狀態 | 判斷方式 | 意義 |
|---|---|---|
| ❌ **裸奔** | `support_level == "裸奔"` | 病歷**確實**未記載 — 這是業務結論 |
| ⏳ **待判定** | `support_level == null` 且 `undetermined == true` | 判定服務異常（LLM 逾時/解析失敗），**系統未能判定** |
| ❓ **查無規則** | `support_level == null` 且 `rule_found == false` | 規則庫無此醫令條文 |

**絕不可把「待判定」顯示為「裸奔」** — 那會讓醫師針對一個從未成功執行的判定，去補強根本不存在的缺漏。規則庫本身故障（DB 損毀/表遺失）則回 **HTTP 503**，同樣不偽裝成「查無規則」。

---

## 🔌 HIS 系統整合與 API 對接指南 (HIS Integration & API Protocol)

`elc-audit-engine` 提供標準 RESTful API 與 Python Package 雙重整合介面，方便嵌入 `doctor-toolbox`、Emr / HIS 門診系統或院內 VPN 上傳服務。

### 1. 系統對接架構與串接流程 (Architecture & Integration Steps)

```text
+----------------------------+      HTTP REST API (X-API-Key)       +-----------------------------------+
|  院方 HIS / EMR 門診系統   |  =================================>  |    Elcinsurrence Core Engine      |
|  (doctor-toolbox / 門診端)  |                                      |       (Flask / CaseStore)         |
+----------------------------+                                      +-----------------------------------+
                                                                                      |
                                       +----------------------------------------------+
                                       |                                              |
                        [事前預審 Review Service]                       [事後申復 Appeal Service]
                        run_presubmission_check()                        run_case_pipeline()
                        事前預審 · 唯讀 · 不寫檔                     事後申復 · 產出報告與草稿
                                       |                                              |
                                       +----------------------+-----------------------+
                                                              |
                                                   [Phase 5 三方比對器]
                                                              |
                              +-------------------------------+-------------------------------+
                              |                               |                               |
                  [Phase 2 規則庫 SQLite]        [Phase 3 解析器 XML/核減/SOAP]     [Phase 4 病歷彙整器]
                  [docx 樹狀索引 + ChromaDB]                                        [半年病史 Provider]
```

#### 💡 完整 HIS 串接四步驟 (End-to-End Workflow)

1. **環境設定與健康檢查 (Step 1: Auth & Healthcheck)**
   - HIS 發送探測請求：`GET /api/health`（不含病歷資料，豁免 API Key）。
   - 設定 Header `X-API-Key: <key>` 存取所有業務 API（於環境變數 `ELC_API_KEYS` 預先設定）。

2. **案件匯入與初始化 (Step 2: Ingest & Case Initialization)**
   - **抽審預審**：HIS 呼叫 `POST /api/sampling/import` 上傳 CSV/PDF。系統解析後寫入 `CaseStore` 持久化，狀態標記為 `imported`。
   - **核減申復**：HIS 呼叫 `POST /api/appeal/import` 上傳 D-14d 明細。系統建案並持久化 (狀態 `imported`)。
   - **案件查詢**：HIS 發送 `GET /api/sampling/cases` 或 `GET /api/appeal/cases` 取得目前儲存庫中的全數案件與最新狀態。

3. **預審比對與狀態推進 (Step 3: Audit & Workflow State Machine)**
   - **事前預審**：HIS 帶入 `case_id` 呼叫 `POST /api/sampling/audit`。系統進行 SOAP 分段與 LLM 三方比對，完成後案件狀態自動由 `imported` 推進至 `parsed` ➔ `reviewing` ➔ `reviewed`。
   - **事後申復**：HIS 帶入 `case_id` 呼叫 `POST /api/appeal/generate`。系統依 D10 四段式結構產出草稿，案件狀態自動推進至 `appealed`。

4. **申復 XML 匯出 (Step 4: XML Export / Package Builder)**
   - 呼叫 CLI 工具 `scripts/build_appeal_xml.py` 讀取 `appeal_{流水號}.json`，生成 Big5 編碼、特殊字元全形轉義之健保署標準申復 XML 檔 (tdata + ddata + pdata)。

### 2. 核心 REST API 規格

> **案例清單端點**（`GET /api/sampling/cases`、`GET /api/appeal/cases`）：未匯入資料時回傳**示範資料**（每個案例帶 `"demo": true`），供 UI 展示工作流；**匯入後優先回傳導入資料**（`source: "csv" / "paddle" / "ocr"`）。醫令名稱一律以規則庫為準（例：`64140C`＝甲床與手指重建術，曾誤標為「手腕韌帶縫合術」，2026-08-04 修正）。

#### 🔐 認證（2026-08-07 起：業務端點依使用者裁示改為選填，供直接 HIS 對接）

| 端點 | 是否強制 `X-API-Key` |
|---|---|
| `GET /` | 否（靜態頁） |
| `GET /api/health` | 否（健康檢查，供 HIS／監控探測，不含案件資料） |
| `GET /api/sampling/cases` | 否（選填——帶合法 key 時審計日誌會記錄真實 `caller_id`，否則記 `anonymous`） |
| `POST /api/sampling/audit` | 否（同上） |
| `POST /api/sampling/import` | 否（同上） |
| `GET /api/appeal/cases` | 否（同上） |
| `POST /api/appeal/generate` | 否（同上） |
| `POST /api/appeal/import` | 否（同上） |

- **背景**：Phase 9-01 原將六個業務端點設為強制認證；`fcde2c8`（2026-08-07）依使用者裁示改為選填，供未經 API Key 分發流程的 HIS 直接對接。認證**機制**（`resolve_caller`／`hmac.compare_digest`）仍在，只是不再強制擋。
- **機制**：服務間 API key（非 JWT／mTLS——呼叫方是 HIS 服務而非瀏覽器使用者，2026-08-05 使用者裁示）。
- **Header**：`X-API-Key: <key>`（選填，帶了會被解析用於審計）。
- **設定**：環境變數 `ELC_API_KEYS`，格式 `caller_id1:key1,caller_id2:key2`（多呼叫方，供審計日誌辨識「誰調閱了病歷」）；每組 key 須 >= 16 字元。**`ELC_API_KEYS` 未設定或格式錯誤時服務啟動即失敗**（fail-fast，即使業務端點不強制認證，key 表本身仍必須合法配置——用於審計辨識與 `/api/health` 之外所有端點的 caller 解析）。
- **比對**：`hmac.compare_digest`（constant-time），不使用 `==`（時序側通道）。
- **401 回應形狀**（`GET /api/sampling/cases` 之外的、未來若新增仍強制認證的端點適用）：`{"status": "error", "message": "認證失敗：缺少或無效的 API key"}`——與「查無資料」（200 + 空陣列）或 404 明確可區分，不得混淆。
- **真實 key 不得進版控**（`.env` 已在 `.gitignore`；`.env.example` 僅提供格式範例）。
- 新增端點時**預設受保護**（`before_request` 統一強制）；豁免需顯式列入 `server.py` 的 `_AUTH_EXEMPT_ENDPOINTS`。

#### 📝 存取審計日誌（Phase 9-01：零 PHI；2026-08-08 修復豁免清單誤用）

每次呼叫非 `_AUDIT_EXEMPT_ENDPOINTS`（`/`／`/api/health`／靜態檔）的端點，都會在審計日誌留下一列 JSON（JSON Lines 格式）：

- **路徑**：`AUDIT_LOG_PATH`（環境變數可覆寫；預設 `data/audit/access.log`，已 `.gitignore`）。
- **欄位（六個，固定）**：`ts`（UTC ISO 時間戳）、`caller_id`（呼叫方識別，或 `anonymous` 表示未帶／帶錯 key）、`method`、`path`、`status`。
- **明文聲明：不記錄 PHI。** 禁止欄位（`soap`／`soap_text`／`record_no`／`patient_name`／`id_number`／`birth_date`）與超長字串（>100 字）一律拒絕寫入（`AuditFieldError`），不會被靜默剔除——審計的目的是「誰在何時存取了什麼端點」，而非複製病歷內容。
- 審計寫檔失敗不會讓業務回應變成 500，但會記錄於 application log（不靜默無痕）。
- **⚠️ 2026-08-08 回歸修復**：`fcde2c8` 把六個業務端點加進認證豁免清單後，`_record_access_audit` 一度沿用同一份清單判斷是否寫審計，導致這六個接觸病歷資料的端點**完全停止寫審計日誌**——違反「認證可選、審計必留」的設計。已拆成 `_AUDIT_EXEMPT_ENDPOINTS`（僅 3 項）與 `_AUTH_EXEMPT_ENDPOINTS`（9 項）兩份獨立清單修復；`test_auth.py` 全數更新驗證。

#### 🔹 [POST] `/api/sampling/audit` — 抽樣事前預審支持度評估

呼叫真實引擎（`run_presubmission_check`）：查規則庫 ➔ Phase 3 `parse_soap_text` 分段 ➔ LLM 逐檢核項判定 ➔ 三級分類 ➔ 缺口候選補強。**需 llama.cpp server 可用**。

- **請求內容 (JSON)**：
  ```json
  {
    "order_code": "14050B",
    "order_name": "糖化血色素檢驗 HbA1c",
    "soap_text": "S: DM O: BP 120/80 A: DM P: HbA1c",
    "record_no": "M1001",
    "case_id": "SAMP-0001"
  }
  ```
  * `case_id`（選填）：提供時會嘗試觸發案件狀態機轉入 `reviewed` 狀態；未提供則維持無狀態行為（向後相容）。

- **回傳內容 (JSON)**:
  ```json
  {
    "status": "success",
    "order_code": "14050B",
    "support_level": "薄弱",
    "rule_found": true,
    "undetermined": false,
    "verdict": "部分支持",
    "quote": "糖尿病追蹤",
    "rule_location": "西醫基層-內科 > 一",
    "reinforcement_advice": "- 建議於 P 欄補充前次檢驗日期與數值",
    "candidates": [
      {"text": "建議於 P 欄補充前次檢驗日期與數值", "rule_location": "西醫基層-內科 > 一", "prompt_only": false}
    ],
    "records_degraded": true
  }
  ```
  > 上例為說明用的欄位形狀。實際 `support_level` 取決於規則庫是否收錄該醫令：
  > 目前 `rule_mapping` 13,942 碼中有 6,934 碼為「誠實無匹配」（語料本無對應條文，
  > 多為藥品碼），這些碼會回 `rule_found: false`。
- **狀態碼**：`400` 入參不合法／缺必填；`503` 規則庫故障（`RuleRepositoryError`）；`500` 其他（訊息已脫敏，不回傳 traceback）。
- ⚠️ `support_level` 可為 `null` — 請依上方「三種非結論狀態」表以 `undetermined` / `rule_found` 分辨，不可逕自視為「裸奔」。

#### 🔹 [POST] `/api/appeal/generate` — 核減多源證據申復草稿生成
呼叫真實產生器（`build_appeal_draft`）組裝 D10 四段。**「③ 規則依據」的條文全文一律取自規則庫 `get_rule`**；查無時回 `rule_found: false` 並誠實標示，不得自行拼造法規依據。

- **請求參數 (JSON)**：`case_seq`、`order_code` 為必填；`evidence` 為**字串陣列**（醫師採用的補強敘述，來自 Phase 6 審核軌跡）。
  ```json
  {
    "case_seq": "201",
    "order_code": "64140C",
    "deduct_amount": 3200,
    "claimed_points": 3200,
    "deduction_reason": "病歷未載明甲床損傷範圍與術前影像評估",
    "is_appealing": true,
    "has_attachment": false,
    "evidence": [
      "影像 Finger X-ray：Distal phalanx fracture with nail bed defect",
      "檢驗 CBC/WBC：11,500 /uL"
    ]
  }
  ```
- **回傳內容 (JSON)**：`appeal_sections` 為**依 D10 四段順序排列的陣列**。
  ```json
  {
    "status": "success",
    "case_seq": "201",
    "order_code": "64140C",
    "appeal_sections": [
      {"key": "case_summary", "title": "①案情摘要", "text": "..."},
      {"key": "necessity", "title": "②醫療必要性（半年病史）", "text": "..."},
      {"key": "rule_basis", "title": "③規則依據（條文原文）", "text": "..."},
      {"key": "evidence", "title": "④病歷佐證（醫師採用補強敘述）", "text": "..."}
    ],
    "reason1": "（p8 欄位文字）",
    "reason2": "（p9 欄位文字）",
    "p6_points": 3200,
    "total_char_count": 420,
    "rule_found": true,
    "xml_p8_p9_valid": true,
    "over_limit": false,
    "validation_errors": []
  }
  ```
- **字數規則**：依官方問答集 **Q15 — p8/p9 各 ≤1000 中文字**（非「合計 2000」）；超限時 `xml_p8_p9_valid: false`。裁剪優先序 ④→②，①③ 骨架不動。
- **硬檢查**：`is_appealing: false` 時 P6 強制填 0（Q13）；`claimed_points` 不得超過 `deduct_amount`（D-15）— 違反時列於 `validation_errors`。
- **狀態碼**：`400` 入參不合法；`503` 規則庫故障；`500` 其他（已脫敏）。

#### 🔹 [POST] `/api/sampling/import` 與 `/api/appeal/import` — 批次匯入清單（digital + paper）

接受 **CSV（digital）、PDF、JPEG/PNG 掃描影像（paper→OCR）**，multipart 欄位名 `file`，單檔上限 10MB。**一律本機處理**（PDF 文字層 pdftotext；掃描文件 PP-StructureV3 表格結構化，降級 tesseract；D2：個資不出本機），不呼叫雲端 API。

- **抽樣清單（`/api/sampling/import`）**：
  - CSV：自訂欄位契約（2026-08-04 裁示）— `流水號(case_seq)／病歷號(record_no)／病患姓名(patient_name)／醫令代碼(order_code, 必填)／醫令名稱(order_name)／就醫日期(visit_date)／科別(clinic)／SOAP(soap_text)`，表頭別名中英皆可、自動偵測，編碼 utf-8-sig→big5→cp950。
  - PDF／影像（紙本）：**優先 PP-StructureV3 表格結構化**（`source: "paddle"`，欄位級：表頭對齊 8 欄契約、日期正規化）；引擎不可用／無表格時**自動降級** tesseract 行解析（`source: "ocr"`，以醫令代碼為錨點結構化「代碼＋名稱」）。每筆保留原始辨識行供人工核對。
  - ⚠️ 表格結構化需 `uv sync --extra ocr`（paddlepaddle==3.2.2 釘版，見 deepflash4improve §8.2）；未裝則全程降級，功能不中斷。
- **核減清單（`/api/appeal/import`）**：CSV 走 D-14d 18 欄 parser（編碼/分隔符/表頭自動偵測）；**PDF／影像誠實降級- CaseStore 整合 (Phase 9-03)**：匯入解析成功後逐筆持久化至 `CaseStore` (state=`imported`)。若出現同名 `case_id` 重複匯入，不會靜默覆寫，而是明確於 `case_store_conflicts` 回報。
- **回傳**：`{status, media_type, source, imported, rejected, rejected_rows:[{row,reason,raw}], saved_to, case_store_persisted, case_store_conflicts}`；GET 案例端點優先讀取 CaseStore，並於伺服器啟動時一次性、冪等地將舊 `data/uploads/*.json` 遷移至 CaseStore。
- **狀態碼**：`400` 缺檔／不支援類型／超過 10MB／未匯入任何案件（含原因）；`500` 其他（已脫敏）。

#### 🔹 [CLI 工具] `scripts/build_appeal_xml.py` — Package Builder (申復 XML 序列化，Phase 9-04)

將 Phase 7 產出的 `appeal_{流水號}.json`（含 p1-p9 醫令段欄位）序列化為符合健保署申復格式之 XML 檔案。

- **用法**：
  ```bash
  python scripts/build_appeal_xml.py <appeal_json路徑> [輸出XML路徑]
  # 範例:
  python scripts/build_appeal_xml.py data/output/appeal_18.json data/output/appeal_18.xml
  ```
- **範圍聲明**：本次僅支援 **tdata + ddata + pdata**（單筆醫令申復），**不含** `edata`（統扣明細段）。若案件分類為統扣類（`0`），需待後續擴充。
- **tdata 加總欄位聲明**：單一案件情境下 `t6-t37` 加總欄位依官方規則無資料不輸出標籤。
- **編碼與特殊字元處理**：檔案固定以 `Big5` 編碼寫出；若遭遇 Big5 無法編碼之字元會 fail-fast 報錯。p8/p9 申復理由內之半形特殊字元 (`< > & ' "`) 會自動轉換為全形字元 (`＜ ＞ ＆ ＇ ＂`)。

#### 🔹 [Python 代碼直接對接]
HIS 後端若為 Python 架構，可直接呼叫 [`pipeline.py`](src/elc_audit_engine/pipeline.py) 的兩個入口：

```python
# ① 事前預審（唯讀，不寫檔）
from elc_audit_engine.pipeline import run_presubmission_check

result = run_presubmission_check(
    case=submission_case,
    soap_doc=soap_document,
    timeline=patient_timeline,   # None＝病歷缺席降級（C5）
)
for oj in result.comparison.order_judgments:
    print(oj.order_code, oj.support_level)   # None 代表待判定／查無規則
print("系統未能判定的醫令：", result.undetermined_orders)
```

```python
# ② 事後申復（比對→補強報告→逐筆申復草稿，會寫檔）
from elc_audit_engine.pipeline import run_case_pipeline

result = run_case_pipeline(
    case=submission_case,
    soap_doc=soap_document,
    timeline=patient_timeline,
    deduction_records=deductions,
    output_dir="/path/to/output",
)
print("病歷補強報告：", result.report_path)
print("申復 XML / JSON 草稿：", result.appeal_paths)
```

兩者皆可注入 `rule_lookup` / `judge_fn` / `narrative_fn` 替身（D-08），測試零 LLM 依賴。
規則庫故障會拋 `RuleRepositoryError`（D-06/P0-2 **穿透不吞** — infra 故障不得偽裝成「查無規則」），呼叫端須自行處理。

---

## 🛠️ 開發與運作指南

### 1. 啟動 Web UI 雙軌控制台

```bash
# 安裝依賴（含 flask；紙本表格結構化加 --extra ocr）
uv sync
uv sync --extra ocr   # 選用：PP-StructureV3 表格結構化（paddlepaddle==3.2.2 釘版）

# 啟動 API 與 雙軌控制台 Web Server
uv run python server.py
```
啟動後打開瀏覽器造訪 `http://127.0.0.1:5000` 即可操作預審與申復介面。

**安全預設**：本服務會接觸病歷資料，故預設 **綁定 `127.0.0.1`、`debug=False`**，且需 `X-API-Key` 認證（見下方「認證」小節；`ELC_API_KEYS` 未設定時服務啟動即失敗）。需對外提供時**務必置於反向代理／VPN 之後**，再以環境變數覆寫：

| 環境變數 | 預設 | 說明 |
|---|---|---|
| `ELC_SERVER_HOST` | `127.0.0.1` | 監聽位址 |
| `ELC_SERVER_PORT` | `5000` | 連接埠 |
| `ELC_SERVER_DEBUG` | 關閉 | 設為 `1`/`true` 開啟；**正式環境切勿開啟**（會回顯堆疊） |
| `ELC_API_KEYS` | 無（**必填**） | 服務間認證 key 表，格式 `caller_id1:key1,caller_id2:key2`；未設定時服務啟動即失敗 |
| `AUDIT_LOG_PATH` | `data/audit/access.log` | 存取審計日誌（JSON Lines，零 PHI）寫入路徑 |

> 預審端點的 LLM 判定需 llama.cpp server（`localhost:8080`）可用；未啟動時判定會降級為「待判定」（`support_level: null` + `undetermined: true`），而非「裸奔」。

### 2. 建置規則庫 (Phase 2 管線)

**須依序執行**（後一步依賴前一步的產物）：

```bash
# 1) 來源 CSV -> SQLite（payment_rules / drug_rules）
uv run python -m elc_audit_engine.rule_repository.scripts.build_sqlite

# 2) 審查注意事項 .doc/.docx -> 樹狀索引（需 LibreOffice headless 轉檔）
uv run python -m elc_audit_engine.rule_repository.scripts.build_docx_trees

# 3) docx 樹 -> ChromaDB 向量索引（輔助層，非阻斷）
uv run python -m elc_audit_engine.rule_repository.scripts.build_chroma_index

# 4) LLM rule_mapping 快取編譯（需啟動 llama.cpp server；支援增量與續跑）
uv run python -m elc_audit_engine.rule_repository.mapping.build_mapping
```

> 產物皆寫入 `data/`（已 gitignore）：`data/db/rules.sqlite3`、`data/db/docx_trees.json`、`data/rag/`。
> 步驟 4 具版本追蹤（`source_version`）與增量建置，中斷後可續跑，不需全部重來。

### 3. 執行單元與端到端測試套件

```bash
uv run pytest -q
```

目前基線：**458 passed / 2 skipped**（Milestone v1.1 全數完成，2026-08-11）。測試零 LLM 依賴（判定與生成皆以替身注入），故不需啟動 llama.cpp 即可全數執行；OCR 表格結構化測試以替身覆蓋，不需 GPU。

---

## ✅ Phase 9 追認：已完成範圍

下列工作已於 Phase 9 之前 commit，但未納入 GSD phase 管理；本節依 Phase 9 Success Criteria 第 1 項要求追認記錄：

| 範圍 | Commit | 內容 | 狀態 |
|---|---|---|---|
| Flask API 接真實引擎 | `b80cd08` | `/api/sampling/audit` → `run_presubmission_check`；`/api/appeal/generate` → `build_appeal_draft`；安全預設（綁 127.0.0.1／debug=False／錯誤脫敏／入參校驗） | 已完成，於 Phase 9 追認納管 |
| 批次匯入 | `56d9902` | `ingest/` 模組（media/sampling/ocr_rows）＋ `/api/sampling/import`、`/api/appeal/import`；落盤 `data/uploads/*.json` | 已完成，於 Phase 9 追認納管 |
| 紙本表格結構化 | `8c38a19` | `ingest/table_ocr.py` PP-StructureV3（可選依賴＋自動降級回 tesseract） | 已完成，於 Phase 9 追認納管 |
| 安全清尾 | `f6ac775` | P1-5 前端 XSS＋CSP／P1-2 prompt 定界／P1-3 路徑穿越 | 已完成，於 Phase 9 追認納管 |

---

## 🖨️ 紙本申復清單列印（Phase 11）

未串接 HIS 或選擇紙本作業的院所，可由 `appeal_{流水號}.json` 產出官方三聯式「門診醫療費用點數申復清單」可列印 PDF——與 Markdown／JSON／申復 XML **並行的輸出通道，不互相取代**。版式依官方 30396_1 模板（105.04.01 修訂版），輸出經 `config/facility.json` 院所層設定與（可選）case payload join 患者層欄位。

### 前置條件

- **本機 LibreOffice（soffice，D-01）**：CLI 以 headless 模式呼叫 `soffice --convert-to pdf` 將 filled ODT 轉成 PDF；soffice 缺席時轉檔階段會明確失敗（不靜默）。
- **`config/facility.json` 已填院所欄位**：`code`（代號字碼）／`name`（醫療院所名稱）為必填，另有 `address`（地址）、`physician_name`（負責醫師）。缺檔或缺必填欄位時 CLI fail-fast（`FileNotFoundError`／`ValueError`），不會以空值默默產出看似正常的 PDF；路徑可經環境變數 **`FACILITY_CONFIG_PATH`** 覆寫。

### 指令範例

```bash
# 基本：單一 appeal JSON → data/output/申復清單_{case_seq}_{order_seq}.pdf
python scripts/build_appeal_print.py data/output/appeal_001.json

# 帶 case payload join 患者層欄位（身份證字號/姓名/傷病名稱/審查科別/數量/金額）
python scripts/build_appeal_print.py data/output/appeal_001.json data/cases_payload.json

# 指定輸出 PDF 路徑（第三參數）
python scripts/build_appeal_print.py data/output/appeal_001.json data/cases_payload.json data/output/appeal_001.pdf
```

### 行為說明

- **三聯一次列印**：每聯 1 頁；醫令 >15 行時自動分頁為 3×N 頁（D-06）。
- **患者層欄位**：身份證字號照印遮罩值（`submission.id_number`）；join 不到的欄位（身份證字號／姓名／傷病名稱／審查科別／數量／金額）留空且**不捏造**，CLI 會於成功訊息後以「警告：」逐條列出缺欄欄位名（只印欄位名，不印值全文，T-11-03）。
- **第二聯「中央健康保險署填列」**：核定／複核／初核／審查委員欄留空，供健保署填寫（系統不產出健保署複核結果）。

### PHI 注意（P0-3）

PDF 輸出於 `data/output/*`（已 `.gitignore`，含 PHI 絕不進版控）。

---

## 📎 影像佐證上傳（Phase 12）

診所可透過 API 上傳超音波、X 光、處置照片等影像佐證，系統依案件流水號與醫令做命名關聯儲存，並由「實體檔案是否存在」真實驅動申復 XML 中的 `p7`（`has_attachment`）欄位。

### 安全設計
- **Magic Bytes 驗證**：PNG/JPEG/HEIC/PDF 各有 Header Bytes 硬性比對，副檔名偽造無效。
- **`safe_filename()` 路徑穿越防護**：白名單校驗（ASCII 英數＋`_-`＋CJK），包含 `../` 等穿越組件直接拒絕。
- **PHI-zero 審計**：附件操作記錄於存取日誌，**只記錄操作不留檔名內容**（T-12-03）。

#### 🔹 [POST] `/api/appeal/attachments/upload` — 上傳影像佐證

- **請求**：`multipart/form-data`，欄位 `file`（PNG/JPEG/HEIC/PDF，≤10MB）+ JSON body `case_seq`、`order_code`。
- **回傳**：
  ```json
  {
    "status": "success",
    "attachment_id": "uuid",
    "filename": "安全後檔名.jpg",
    "case_seq": "201",
    "order_code": "64140C"
  }
  ```
- **狀態碼**：`400` 格式不支援或 Magic Bytes 不符；`413` 超過 10MB；`500` 其他。

#### 🔹 [GET] `/api/appeal/attachments/<case_seq>` — 列出佐證附件

回傳指定案件流水號所有已上傳附件的元資料清單（不回傳二進位內容）。

#### 🔹 [DELETE] `/api/appeal/attachments/<case_seq>/<attachment_id>` — 刪除附件

刪除指定附件檔案，並從 `has_attachment` 計算中排除。

---

## 🗒️ 核減明細原格式列印（Phase 13）

匯入並解析健保核減資料後，可輸出與官方「門診醫療給付抽查核減明細表」紙本一致格式的 PDF，供診所留底或紙本對帳（RCPI2012R01 式樣）。

### 技術設計
- **ODT ElementTree 動態列複製**：以 `xml.etree.ElementTree` 操作 ODT ZIP 結構，動態複製 `<table:table-row>` 並注入各筆核減記錄，避免 XML/String Injection（T-13-01）。
- **soffice headless 轉 PDF**：在 `TemporaryDirectory` 沙盒中執行轉換，用後即刪（T-13-04）。

#### 🔹 [POST] `/api/deduction/print` — 核減明細 PDF 列印

- **請求 (JSON)**：
  ```json
  {
    "records": [
      {
        "case_seq": "201",
        "order_code": "64140C",
        "order_name": "甲床與手指重建術",
        "deduct_amount": 300,
        "deduction_code": "D01",
        "deduction_reason": "病歷未記載甲床損傷範圍",
        "visit_date": "2026-06-20",
        "fee_year_month": "11506"
      }
    ]
  }
  ```
- **回傳**：
  ```json
  {
    "status": "success",
    "pdf_url": "/output/核減明細_xxxxxxxx.pdf",
    "warnings": ["Row 1: 缺病患姓名"]
  }
  ```
- **CLI 替代方案**：`python scripts/build_deduction_print.py data/deduction.csv`
- **狀態碼**：`400` 缺必填欄位；`500` soffice 轉檔失敗（含錯誤說明）。

---

## 📦 審核軌跡＋申復佐證包列印（Phase 14）

將審核軌跡 JSON、病歷補強 Markdown 報告、申復理由草稿，以及上傳之影像佐證照片，合成為結構完整的「可列印佐證包 PDF」，供診所列印後隨同紙本申復清單合訂寄出。

### 技術設計
- **管線**：`python-docx`（A4 版面架構） → `soffice headless`（DOCX→PDF） → `pypdf`（合訂多段 PDF）。
- **影像處理**：`Pillow` + `pillow_heif`（HEIC 支援）＋ EXIF 自動旋轉＋A4 自動縮放；損毀圖片自動跳過並標紅色警示框（不中止整包生成）。
- **結構**：摘要封面→審核軌跡→病歷摘要→申復理由全文→影像佐證附錄（附錄每張圖自占一頁）。

#### 🔹 [POST] `/api/appeal/evidence-packet/print` — 佐證包 PDF 生成

- **請求 (JSON)**：
  ```json
  {
    "case_id": "APP-0001"
  }
  ```
  亦接受完整 payload（`case_seq`、`orders`、`sections` 等），`case_id` 優先從 `CaseStore` 讀取案件資料。
- **回傳**：
  ```json
  {
    "status": "success",
    "pdf_url": "/output/申復佐證包_201.pdf",
    "warnings": []
  }
  ```
- **CLI 替代方案**：`python scripts/build_evidence_packet.py --case-id APP-0001`
- **狀態碼**：`400` 缺案件資料；`500` 合成失敗（含錯誤說明）。

---

## 🌐 完整 REST API 端點一覽（v1.1）

| Method | 端點 | 功能 | 認證 |
|--------|------|------|------|
| `GET` | `/api/health` | 健康檢查 | 免認證 |
| `GET` | `/` | 控制台首頁（Web UI） | 免認證 |
| `GET` | `/api/sampling/cases` | 抽審名冊案件列表 | 選填 |
| `POST` | `/api/sampling/audit` | 事前預審支持度評估 | 選填 |
| `POST` | `/api/sampling/import` | 匯入抽審名冊（CSV/PDF/影像） | 選填 |
| `GET` | `/api/appeal/cases` | 申復草稿案件列表 | 選填 |
| `POST` | `/api/appeal/generate` | 核減申復草稿生成 | 選填 |
| `POST` | `/api/appeal/import` | 匯入核減清單 | 選填 |
| `POST` | `/api/appeal/attachments/upload` | 上傳影像佐證（Phase 12） | 選填 |
| `GET` | `/api/appeal/attachments/<case_seq>` | 列出佐證附件（Phase 12） | 選填 |
| `DELETE` | `/api/appeal/attachments/<case_seq>/<id>` | 刪除佐證附件（Phase 12） | 選填 |
| `POST` | `/api/deduction/print` | 核減明細原格式 PDF（Phase 13） | 選填 |
| `POST` | `/api/appeal/evidence-packet/print` | 佐證包 PDF 合成（Phase 14） | 選填 |

> **認證「選填」說明**：帶合法 `X-API-Key` 時審計日誌記錄真實 `caller_id`；未帶時記 `anonymous`。認證機制仍在，只是不強制擋（2026-08-07 政策調整，詳見「認證」小節）。

---

## 📂 專案架構文件參考
- **開發進度與里程碑**：[`progress.md`](progress.md)
- **改進意見與架構分析**：[`deepflash4improve.md`](deepflash4improve.md)
