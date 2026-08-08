# Phase 11: 紙本申復清單列印 - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-08
**Phase:** 11-paper-appeal-print
**Areas discussed:** 排版工具鏈, 三聯處理, 院所基本資料來源, 超行分頁

---

## 排版工具鏈

| Option | Description | Selected |
|--------|-------------|----------|
| LibreOffice/soffice 套版 | 延續 Phase 2 docx-tree 索引器的工具鏈慣例，直接拿現成 .odt 官方範本套版，用 soffice --headless 轉 PDF。優點：版面與官方範本保證一致、不引進新重量級 Python 套件。缺點：依賴 LibreOffice 二進制（已是現有依賴）。 | ✓ |
| Python PDF 套件（reportlab 等） | 用程式碼直接畫表格線條與文字定位。優點：不依賴外部二進制、完全控制排版細節。缺點：需手工重建複雜表格的每欄位置，與官方範本的視覺一致性需靠人工比對。 | |

**User's choice:** LibreOffice/soffice 套版（建議選項）
**Notes:** 延續專案既有工具鏈慣例，降低新增依賴風險。

---

## 三聯處理

| Option | Description | Selected |
|--------|-------------|----------|
| 一次列印三頁 | PDF 包含三頁，每頁對應一聯（第三聯多出「中央健康保險署填列」欄位，其餘兩聯相同欄位但不填值）。院所列印後自行裁切或用複寫紙列印。 | ✓ |
| 只產第一聯（院所存查聯） | 因為系統是院所端使用，實際寄交健保署的紙本仍需實體複寫紙，系統只提供院所自己存查的那一聯作為列印參考，實際送交仍需另外填寫實體複寫紙。 | |

**User's choice:** 一次列印三頁（建議選項）
**Notes:** 符合系統「一份 PDF 對應一案件」的既有慣例。

---

## 院所基本資料來源

| Option | Description | Selected |
|--------|-------------|----------|
| config 新增院所基本資訊設定 | 新增靜態設定檔（如 config/facility.json）存代號字碼、醫療院所名稱、地址、負責醫師等固定不變的院所層資訊。案件層欄位（審查科別、原申報類別/日期、年度月份頁數、流水號）則在生成 PDF 時作為參數傳入，從 AppealDraft/CaseStore 推導或人工輸入。 | ✓ |
| 全部作為呼叫時參數，不新增設定檔 | 不建立新的靜態設定檔，所有院所基本資訊都當成呼叫 PDF 生成函式時必填參數，由上層（未來的 server 端點或 CLI）負責提供。排版層保持無狀態，但未來接端點時每次都得重新傳這些固定值。 | |

**User's choice:** config 新增院所基本資訊設定（建議選項）
**Notes:** `AppealDraft.case_class` 對應官方「案件分類」欄，可直接沿用（源自 D-14d 欄位 5／申報 XML `d1`），不需額外設定。

---

## 超行分頁

| Option | Description | Selected |
|--------|-------------|----------|
| 自動分頁，每頁重複表頭 | 超過單頁容量時自動斷頁，每頁重複院所層欄位與表頭，頁數欄（官方表格本身有「頁數」欄）依序遞增。 | ✓ |
| 本 phase 只處理單頁（單醫令案件），超行列為後續缺口 | 先不實作分頁邏輯，若醫令行數超過單頁容量則報錯或截斷。範圍最小但實務上可能不夠用（申復案件常不止一條醫令）。 | |

**User's choice:** 自動分頁，每頁重複表頭（建議選項）
**Notes:** 符合官方紙本作業「多頁申復清單本來就常見」的實務慣例。

---

## Claude's Discretion

- 具體 config 檔案格式（JSON vs 環境變數 vs 沿用 `config/settings.py` 模式）
- 每頁容量行數（需由範本實測版面計算）
- `.odt` 範本套版的具體技術手法（LibreOffice macro／欄位取代／模板變數注入）
- 官方表格欄位與 `AppealDraft` 資料模型的完整逐欄對應表
- 第三聯「中央健康保險署填列」欄位留空的具體排版處理方式
- 是否新增列印用 API 端點，或僅提供背景腳本（比照 `scripts/build_appeal_xml.py`）

## Deferred Ideas

- **紙本抽審清單（非申復清單）的列印**——是否存在對應官方範本尚未確認，留待使用者未來提出時另開 phase。
- **第三聯健保署複核結果回填**——屬院所收到健保署回覆後的行政作業，非本系統範圍。
