# Phase 28 Research: 當月申報與每日語音 SOAP 自動比對入庫暨 EMR 11 碼批次打包引擎深度研究

## 一、 現狀程式庫深度盤點 (Current Codebase Audit)

### 1. 申報匯入與案件生命週期鏈路
- **`src/elc_audit_engine/case_store/monthly.py`**：
  - 核心入口 `ingest_monthly_declaration(store, result)` 接收 `parse_totfa_zip` 之結果。
  - 目前其內部 helper `_payload(batch, case)` 產生的資料結構如下：
    ```python
    def _payload(batch: str, case: SubmissionCase) -> dict:
        return {
            "batch": batch,
            "case_class": case.case_class,
            "case_seq": case.case_seq,
            "record_no": case.record_no,
            "patient_name": case.patient_name,
            "birth_date": case.birth_date,
            "id_card": case.raw.get("d3", ""),
            "total_points": case.raw.get("d39"),
            "clinic": case.clinic,
            "doctor_code": case.raw.get("d30"),
            "visit_date": case.visit_date,
            "primary_diagnosis": case.primary_diagnosis,
            "secondary_diagnoses": list(case.secondary_diagnoses),
            "orders": [order.raw for order in case.orders],
            "warnings": list(case.warnings),
        }
    ```
  - **診斷發現**：完全沒有 `soap` 或 `vault_key` 欄位！這意味著當月申報匯入時，案件處於「純申報點數、無門診病歷」的孤立狀態。

- **`src/elc_audit_engine/sampling_sampler.py`**：
  - 抽樣取樣函式 `_record(payload, target_code)`：
    ```python
    def _record(payload: dict, target_code: str | None) -> SamplingCaseRecord:
        return SamplingCaseRecord(
            ...
            soap_text="",  # 硬編碼為空字串！
            source="monthly_batch",
        )
    ```
  - **診斷發現**：取樣時直接給定 `soap_text=""`，導致第二階工作台必須依賴後續人工手動鍵入或查詢補填。

- **`src/elc_audit_engine/monthly_patient_service.py`**：
  - 函式 `monthly_payload_to_appeal_case(payload)`：
    ```python
    "soap": "",
    "multisource_evidence": {"labs": [], "images": [], "cloud_sync": []},
    ```
  - **診斷發現**：轉入第三階申復時，同樣遺失日常看診的 SOAP 與影像/檢驗多源證據。

---

### 2. Local Server 上已有的每日門診語音 SOAP 與證據金庫
- **`src/elc_audit_engine/api/routes/his_integration.py`**：
  - 診間看診時由 SoapVoice（或診間前端）調用 `POST /api/his/soapvoice-ingest`：
    - 將音訊與截圖存入 `evidence_vault`（以 `vault_key = f"{id_card}-{yymm}"` 索引）。
    - 建立 `CaseStore` 記錄（`kind="his"`），其 payload 完整保存 `soap`（含 `subjective`, `objective`, `assessment`, `plan`）、`vault_key`、`vault_files`。
  - 同時維護 `PATIENT_DB`：內含「陳美玲」、「王大明」、「李阿土」等病患之完整門診歷程與真實英文/中文 SOAP 紀錄（如王大明 1120920 DM 看診、陳美玲 1120718 關節炎看診）。
- **`src/elc_audit_engine/evidence_vault.py`**：
  - 實作了依 `vault_key`（如 `A123456789-2307`）歸檔之多媒體檔案存儲：
    - `audio/`：門診錄音原檔（`.opus`, `.wav`）
    - `images/`：放射影像／超音波／截圖（`.webp`, `.png`, `.jpg`）
    - `reports/`：檢驗檢查報告（`.pdf`）
    - `records/`：門診病歷本文

---

### 3. 現有健保打包模組分析 (`nhi_case_packager.py`)
- 現有 `src/elc_audit_engine/packagers/nhi_case_packager.py` 僅實作基礎的 11 碼名稱生成 `build_base_name` 與單一案件 ZIP 容器。
- **對照規格說明書 (`emr-batch-packaging-naming-spec.md`) 的缺口**：
  1. **缺少四階層屬性分類自動識別引擎**：未能自動將 SOAP 轉為 `A`、影像轉為 `B`、檢驗報告轉為 `C`、同意書轉為 `D`。
  2. **缺少 500MB 動態分包機制**：未實作依機構代碼、系統日期與三碼流水號（`{HospID}_{Date}_{Seq}.zip`）命名，亦無 450MB 臨界裁切分包。
  3. **缺少 PDF 樹狀書籤 (Bookmarks)**：未提供 A 類病歷本文標準排版與樹狀書籤自動生成。
  4. **缺少源頭端品質驗證 (Validation-at-Source)**：未包含 11 碼半形英數字嚴格校驗、DICOMDIR 檢查與重複檔名阻斷。

---

## 二、 自動比對與關聯架構設計 (Reconciliation Design)

### 1. 複合比對鍵 (Multi-Key Composite Matching)
當上傳 `MONTHLY-202307` 時，每一筆申報資料 `case` 比對順序如下：
1. **主鍵正規化**：
   - 身分證字號 / 病歷號：統一轉大寫半形英數字。
   - 就醫日期：利用 `normalize_date_variants` 產生民國 7 碼（`1120718`）、西元 8 碼（`20230718`）等多種型態。
2. **多源三層檢索策略**：
   - **第 1 層（Local Server 本機資料庫）**：檢索 `CaseStore` 中 `kind="his"` 之案件，匹配 `id_card == case.id_card` 且 `visit_date in variants`。
   - **第 2 層（診所門診即時資料庫 PATIENT_DB）**：檢索本機 `PATIENT_DB` 中該病患的歷次就診 `encounters`，匹配 `visit_date in variants`。
   - **第 3 層（佐證金庫 Evidence Vault）**：計算 `vault_key = compute_vault_key(id_card, visit_date)`，調閱該金庫目錄下之檔案。
3. **資料寫入與資料庫備存**：
   - 提取匹配到的結構化 SOAP（轉為標準字串及 S/O/A/P 物件）。
   - 將 `soap`、`vault_key`、`vault_files` 寫入 `CaseStore` 之 `monthly` 案件 payload。
   - 同步提供服務層函式：當抽樣或申復帶入案件時，直接繼承已比對之真實 SOAP。

---

## 三、 11 碼標準檔名與 EMR 批次打包引擎架構設計

### 1. 核心類別劃分
- **`EmrClassifier`**：
  - 輸入：檔案類型、副檔名或表單標記。
  - 輸出：歸類為 `A`（病歷本文）、`B`（影像）、`C`（檢驗數據）、`D`（其他同意書）。
- **`Emr11CodeNaming`**：
  - 輸入：醫事類別（`11` 診所門診）、資料屬性（`A`/`B`/`C`/`D`）、案件分類（`01`~`09`）、案件流水號（6 碼）、擴充序號。
  - 輸出：如 `11A09001352.pdf`、`11B09001352-1.jpg`。
- **`StructuredSoapPdfBuilder`**：
  - 將比對完成之 SOAP、門診處方箋與病歷首頁排版為高解析 PDF，並自動寫入 PDF 樹狀目錄書籤（`outline`/`bookmarks`）。
- **`BatchZipPackager`**：
  - 監控檔案大小累計，於 450MB 自動分包。
  - 產出標準檔名 `{facility_code}_{roc_date}_{seq:03d}.zip`。
  - 內含 `MANIFEST.txt`、`SHA256_CHECKSUM.txt` 與標準資料夾結構。
- **`SourceQualityValidator`**：
  - 封包前預檢，攔截中文檔名、非許可副檔名、缺少 DICOMDIR 等異常。
