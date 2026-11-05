# Plan 28-01 總結報告：當月申報 (TOTFA) 與每日門診語音 SOAP 自動比對入庫與資料庫持久化存取

## 執行成果概述
本計畫（Plan 28-01）成功建立當月申報檔 (TOTFA.zip) 與 Local Server 每日門診語音 SOAP 紀錄之自動比對關聯引擎（Reconciliation Engine）：
1. **解決費用申報檔無病歷文字痛點**：
   - TOTFA 僅包含健保點數、醫令藥令與診斷碼，缺乏門診 SOAP 病歷。
   - 建立 `src/elc_audit_engine/reconciliation/soap_reconciler.py`，以「醫事機構代碼 + 申報年月份 + 身分證號/病歷號 + 就醫日期」為複合主鍵，執行多源三層檢索（`CaseStore` kind=`his` $\rightarrow$ `PATIENT_DB` 本機門診庫 $\rightarrow$ `evidence_vault` 多媒體金庫）。
2. **入庫流程自動關聯注入**：
   - 更新 `src/elc_audit_engine/case_store/monthly.py`：在 `ingest_monthly_declaration` 解析匯入當月申報時，自動調用 `reconcile_case_soap` 將真實 SOAP、`vault_key` 與佐證檔案寫入案件 payload 並持久化存入資料庫。
3. **二階與三階工作台無縫繼承**：
   - 更新 `src/elc_audit_engine/sampling_sampler.py`：抽樣時不再寫死 `soap_text=""`，而是直接自案件 payload 繼承比對所得之 SOAP。
   - 更新 `src/elc_audit_engine/monthly_patient_service.py`：將當月申報轉入抽樣與申復清單時，自動帶入真實 SOAP 與佐證檔案清單（`multisource_evidence`），供醫師與 Qwen LLM 即時審查與申復備存。
4. **測試驗證**：
   - 新增 `tests/test_monthly_soap_reconciliation.py`（5 項測試全綠）。
   - 迴歸測試 `test_patient_import_from_monthly.py`、`test_stage2_3_buttons.py`、`test_soap_workbench_ui.py`（13 項測試全綠）。

## 產物清單
- `src/elc_audit_engine/reconciliation/__init__.py`
- `src/elc_audit_engine/reconciliation/soap_reconciler.py`
- `src/elc_audit_engine/case_store/monthly.py`
- `src/elc_audit_engine/sampling_sampler.py`
- `src/elc_audit_engine/monthly_patient_service.py`
- `tests/test_monthly_soap_reconciliation.py`
