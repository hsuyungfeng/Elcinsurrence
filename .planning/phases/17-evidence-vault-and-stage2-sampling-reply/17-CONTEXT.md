# Phase 17: 二階抽審核實工作台與身分證佐證庫（Evidence Vault）

## 1. 業務背景與真實工作流（Real Workflow）
- **第一階（事前預審）**：送審前院所由申報總檔自動檢視高價醫令並預先修正病歷。
- **第二階（抽審回覆與多源核實）**：
  健保局下發 XML 抽審清單（如由申報檔篩出），院所需針對清單上的案件進行病歷 SOAP 與佐證核實。
  佐證檔案（影像、錄音、檢驗檢查報告、SOAP）統一放置於以 **`身分證字號-年份月份`（如 `A123625499-2605`）** 命名的專屬資料夾或壓縮包中。
- **第三階（事後申復）**：收到健保核減後的申復工作流。

## 2. 核心規範與設計決策
1. **佐證庫命名規範 (`Evidence Vault`)**:
   - 目錄結構：`data/evidence_vault/<id_number>-<yymm>/`（例如 `A123625499-2605`，YYMM 為民國年 2 碼 + 月 2 碼，或 4 碼西元月相容）。
   - 子目錄分類支援：
     - `images/`: `.jpg`, `.jpeg`, `.png`, `.dicom`, `.heic`
     - `audio/`: `.mp3`, `.m4a`, `.wav`, `.aac`
     - `reports/`: `.pdf`, `.txt`, `.csv`
     - `records/`: `soap.txt`, `soap.json`
   - 支援自動解壓 ZIP（例如使用者拖入 `A123625499-2605.zip` 自動歸檔入庫）。
2. **前後端整合**:
   - 後台提供 `GET /api/vault/<vault_key>` 與 `POST /api/vault/<vault_key>/upload` 及 `GET /api/vault/<vault_key>/files/<category>/<filename>`。
   - 前端第二階介面提供：
     - 身分證目錄自動匹配狀態與掛載。
     - 🎙️ 錄音檔直接內嵌播放。
     - 🖼️ 影像縮圖與點擊放大。
     - 📄 檢驗報告 PDF 內嵌或預覽。
3. **驗收資料**:
   - 以 `MONTHLY-202307.zip`（TOTFA.xml）為核心基準，進行抽審案件匹配與全流程走通驗證。
