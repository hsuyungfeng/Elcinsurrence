# Phase 28-02 Summary: 健保 11 碼標準檔名編碼與 EMR 批次 500MB ZIP 分包引擎

## 執行概述
本階段完成依據健保署最新 EMR 電子病歷審查規格（`emr-batch-packaging-naming-spec.md`）產製之標準批次打包引擎，達成以下關鍵成果：
1. **11 碼標準檔名自動化編碼引擎**：
   - 結構：`[第1階 2碼 11:西醫基層門診] + [第2階 1碼 A/B/C/D] + [案件分類 2碼 09] + [流水號 6碼 000001~999999] + [-N 擴充]`。
   - 嚴格半形英數字命名規範，禁止包含中文字元或特殊符號。
2. **四大資料屬性分類器 (A/B/C/D)**：
   - A: 病歷本文類（SOAP 病歷紀錄、處方箋、病歷首頁）。
   - B: 影像類（X 光、超音波、臨床處置照片、DICOM）。
   - C: 非影像檢驗報告（CBC、HbA1c、生化檢查）。
   - D: 其他書類/同意書（手術同意書、事前核准函）。
3. **A 類病歷本文高畫質 PDF 樹狀書籤生成**：
   - 自動生成三頁式標準病歷單（Page 1: 病歷首頁、Page 2: 處方箋、Page 3: 門診 SOAP 紀錄單）。
   - 自動嵌入 PDF 樹狀書籤（`病歷首頁`、`門診處方箋`、`門診 SOAP 紀錄單`）與醫師電子簽章驗證區。
4. **500MB ZIP 批次封包與動態裁切分包**：
   - 封包檔名符合規格：`{機構代碼 10碼}_{民國日期 7碼}_{序號 3碼}.zip`（例如 `3503250461_1151105_001.zip`）。
   - 超過 450MB 動態臨界點時自動分割為第二包、第三包。
   - 封包內自動產製並包含 `MANIFEST.txt` 與 `SHA256_CHECKSUM.txt` 數位防竄改清單。
5. **源頭端品質驗證 (Validation-at-Source)**：
   - 檔名合規性、格式副檔名白名單/阻斷清單、DICOMDIR 引導目錄完整性檢驗。
6. **RESTful API 端點與完整測試**：
   - `POST /api/emr/batch-package`
   - `GET /api/emr/packages`
   - `GET /api/emr/download/<filename>`

## 驗證結果
- `tests/test_emr_batch_packaging.py` 6/6 全數通過。
- `tests/test_monthly_soap_reconciliation.py` 5/5 全數通過。
- 全套回歸測試（48 項測試）100% 通過（0 failed, 0 error）。
