# Phase 21: 健保電子抽審檔案打包器、批次申復 XML (t38/t39) 與 Local Agent 橋接介面

## 目標
1. **健保標準檔案打包器（Evidence Packager）**：
   - 檔名轉換：依健保 11 碼規範（第一階 2 碼 + 第二階 1 碼 + 案件分類 2 碼 + 案件流水號 6 碼，多張影像末尾加序號，如 `13B190123451.jpg`）將佐證庫檔案重命名。
   - 檔案過濾與安全：嚴格阻擋 ZIP/RAR/EXE，非 DICOM 接受 JPG/JPEG/PNG/BMP/TIFF/PDF/TXT。
   - 單案完整打包導出端點：`GET /api/sampling/cases/<case_id>/export-package`（輸出符合健保規格的送審目錄/檔案包，落實單案一次性送審，禁止分拆）。
2. **電子申復 XML 規格完整化（Appeal Batch XML & t38/t39）**：
   - 在 `generators/appeal_xml.py` 與 `routes/appeal.py` 補齊全批次導出 `GET /api/appeal/export-batch-xml`。
   - 補齊 `<tdata>` 之 `t38`（申復總件數）與 `t39`（申復總金額點數加總）加總節點。
   - 嚴格落實 `p6`（不申復醫令強制填 0）、`p7`（附件標記 Y/N）、`p8/p9`（四段式申復理由切分 ≤2000 中文字）、Big5 編碼與特殊字元（`<>&'"`）全形化轉換。
3. **雲端與地端 Local Agent 橋接 API（Bridge API for NHI_EIIAPI）**：
   - 設計專供地端 Local Agent 輪詢與下載的端點：
     - `GET /api/bridge/jobs/pending`：支援依 `sTypeCode`（`15`: 費用抽審 XML、`00`: 專業審查病歷影像、`07`: 申復 XML、`09`: 申復預檢）拉取待送任務。
     - `POST /api/bridge/jobs/<job_id>/status`：地端 Agent 呼叫 `NHI_SendA`/`NHI_SendB` 後回報 `sLocal_ID`、`sNHI_ID` 及 `NHI_Query` 狀態（如 `A12`、`A99`）。
