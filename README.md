# Elcinsurrence 健保電子抽審與申復自動化輔助系統

`Elcinsurrence` 是一套專為健保門診抽樣與核減申復設計的自動化審核與申復輔助引擎（`elc-audit-engine`），提供雙軌處理介面（事前預審補強 ＋ 事後申復理由生成）與完整的 HIS 介面對接機制。

---

## 🌟 核心架構與雙軌工作流 (Dual-Workflow Architecture)

本系統支援兩大獨立運作介面與流程：

### 1. 📋 抽樣事前預審工作流 (Sampling Pre-audit Workflow)
- **目的**：於抽審清單送出健保署前，審核門診病歷並評估「醫令支持度」（✅ **充分** / ⚠️ **薄弱** / ❌ **裸奔**）。
- **流程**：導入抽樣 CSV 清單 ➔ 病歷 SOAP 解析 ➔ 三方邏輯比對 ➔ 自動提示病歷缺口與補強建議 ➔ 醫師完備病歷後送出抽審。

### 2. ⚖️ 核減事後申復工作流 (Appeal Post-processing Workflow)
- **目的**：針對健保署核減不予核銷之刪減醫令，啟動多源證據自動彙整並生成申復檔案。
- **流程**：導入核減明細 ➔ 多源證據提取（門診 SOAP ＋ 檢驗 Lab ＋ 影像 Radiology ＋ 健保雲端病歷 EHR） ➔ 4 段式申復理由自動組裝（≤2000 字控制） ➔ 導出申復 XML (p1~p9) / JSON 契約。

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
                                                                   +------------------+------------------+
                                                                   |                                     |
                                                        [Phase 2 規則庫 SQLite]               [Phase 5 三方比對器]
                                                        [ChromaDB 向量索引]                   [Phase 7 申復 XML 引擎]
```

### 2. 核心 REST API 規格

#### 🔹 [POST] `/api/sampling/audit` — 抽樣事前預審支持度評估
- **請求參數 (JSON)**:
  ```json
  {
    "order_code": "14050B",
    "order_name": "糖化血色素檢驗 HbA1c",
    "soap_text": "S: 糖尿病追蹤，無發燒不適。 O: BP 120/80 A: DM Type 2 P: 開立 HbA1c 抽血追蹤",
    "missing_reason": "病歷 SOAP A 欄僅記載簡寫 DM，未附上近三次血糖趨勢"
  }
  ```
- **回傳內容 (JSON)**:
  ```json
  {
    "status": "success",
    "order_code": "14050B",
    "support_level": "薄弱",
    "verdict": "部分支持",
    "reinforcement_advice": "建議補強：請醫師於 P 欄補充『病患上次 HbA1c 8.2%，本次為 3 個月例行評估』以達強支持。"
  }
  ```

#### 🔹 [POST] `/api/appeal/generate` — 核減多源證據申復草稿生成
- **請求參數 (JSON)**:
  ```json
  {
    "case_seq": "201",
    "order_code": "64140C",
    "order_name": "手腕韌帶縫合術",
    "deduct_amount": 3200,
    "deduction_reason": "病歷未載明肌腱撕裂之影像是項與術前評估",
    "evidence": {
      "images": [{"name": "Wrist MRI", "report": "Complete tear of TFCC ligament"}],
      "labs": [{"name": "CBC/WBC", "result": "11,500 /uL"}],
      "cloud_sync": [{"source": "健保雲端病歷", "note": "外院 X 光顯示右腕關節腔狹窄"}]
    }
  }
  ```
- **回傳內容 (JSON)**:
  ```json
  {
    "status": "success",
    "appeal_sections": {
      "section_1": "① 案情摘要...",
      "section_2": "② 醫療必要性 (含影像 MRI/檢驗/雲端病歷佐證)...",
      "section_3": "③ 規則依據 (支付規定與審查原則)...",
      "section_4": "④ 病歷佐證 (醫師申復說明)..."
    },
    "total_char_count": 420,
    "xml_p8_p9_valid": true
  }
  ```

#### 🔹 [Python 代碼直接對接]
HIS 後端若為 Python 架構，可直接呼叫管道入口 [`run_case_pipeline`](src/elc_audit_engine/pipeline.py)：

```python
from elc_audit_engine.pipeline import run_case_pipeline

result = run_case_pipeline(
    case=submission_case,
    soap_doc=soap_document,
    deduction_records=deductions,
    timeline=patient_timeline,
    output_dir="/path/to/output"
)
print("病歷補強報告：", result.report_path)
print("申復 XML / JSON 草稿：", result.appeal_paths)
```

---

## 🛠️ 開發與運作指南

### 1. 啟動 Web UI 雙軌控制台

```bash
# 啟動 API 與 雙軌控制台 Web Server
./.venv/bin/python3 server.py
```
啟動後打開瀏覽器造訪 `http://localhost:5000` 即可操作預審與申復介面。

### 2. 建置規則庫 (Phase 2 管線)

```bash
# 1) 來源 CSV -> SQLite（payment_rules / drug_rules）
./.venv/bin/python -m elc_audit_engine.rule_repository.scripts.build_sqlite

# 2) 審查注意事項 .docx -> 樹狀索引
./.venv/bin/python -m elc_audit_engine.rule_repository.scripts.build_docx_trees

# 3) docx 樹 -> ChromaDB 向量索引（輔助層）
./.venv/bin/python -m elc_audit_engine.rule_repository.scripts.build_chroma_index

# 4) LLM rule_mapping 快取編譯 (需啟動 llama.cpp server)
./.venv/bin/python -m elc_audit_engine.rule_repository.mapping.build_mapping
```

### 3. 執行單元與端到端測試套件

```bash
./.venv/bin/pytest -v
```

---

## 📂 專案架構文件參考
- **開發進度與里程碑**：[`progress.md`](progress.md)
- **改進意見與架構分析**：[`deepflash4improve.md`](deepflash4improve.md)
