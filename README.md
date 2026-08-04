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

### 1. 系統對接架構圖 (Integration Flow)

```
+----------------------------+      HTTP REST API / Python API      +-----------------------------------+
|  院方 HIS / EMR 門診系統   |  =================================>  |    Elcinsurrence Core Engine      |
|  (doctor-toolbox / 門診端)  |                                      |       (elc-audit-engine API)      |
+----------------------------+                                      +-----------------------------------+
                                                                                      |
                                       +----------------------------------------------+
                                       |                                              |
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

### 2. 核心 REST API 規格

> **案例清單端點**（`GET /api/sampling/cases`、`GET /api/appeal/cases`）：目前回傳**示範資料**（每個案例帶 `"demo": true`），供 UI 展示工作流；醫令名稱一律以規則庫為準（例：`64140C`＝甲床與手指重建術，曾誤標為「手腕韌帶縫合術」，2026-08-04 修正）。真實資料源（抽樣 CSV／核減明細 CSV 匯入端點）為 Phase 2 待辦。

#### 🔹 [POST] `/api/sampling/audit` — 抽樣事前預審支持度評估

呼叫真實引擎（`run_presubmission_check`）：查規則庫 ➔ Phase 3 `parse_soap_text` 分段 ➔ LLM 逐檢核項判定 ➔ 三級分類 ➔ 缺口候選補強。**需 llama.cpp server 可用**。

- **請求參數 (JSON)**：`order_code` 為必填；字串欄位上限 200 字，`soap_text` 上限 10,000 字，超出回 400。
  ```json
  {
    "order_code": "14050B",
    "order_name": "糖化血色素檢驗 HbA1c",
    "soap_text": "S: 糖尿病追蹤，無發燒不適。\nO: BP 120/80\nA: DM Type 2\nP: 開立 HbA1c 抽血追蹤",
    "record_no": "M1001"
  }
  ```
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
# 安裝依賴（含 flask）
uv sync

# 啟動 API 與 雙軌控制台 Web Server
uv run python server.py
```
啟動後打開瀏覽器造訪 `http://127.0.0.1:5000` 即可操作預審與申復介面。

**安全預設**：本服務會接觸病歷資料，故預設 **綁定 `127.0.0.1`、`debug=False`**，且不含認證機制。需對外提供時**務必置於反向代理／VPN 之後**，再以環境變數覆寫：

| 環境變數 | 預設 | 說明 |
|---|---|---|
| `ELC_SERVER_HOST` | `127.0.0.1` | 監聽位址 |
| `ELC_SERVER_PORT` | `5000` | 連接埠 |
| `ELC_SERVER_DEBUG` | 關閉 | 設為 `1`/`true` 開啟；**正式環境切勿開啟**（會回顯堆疊） |

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

目前基線：**207 passed / 1 skipped**。測試零 LLM 依賴（判定與生成皆以替身注入），故不需啟動 llama.cpp 即可全數執行。

---

## 📂 專案架構文件參考
- **開發進度與里程碑**：[`progress.md`](progress.md)
- **改進意見與架構分析**：[`deepflash4improve.md`](deepflash4improve.md)
