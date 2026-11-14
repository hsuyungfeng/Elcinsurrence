# Phase 32 Plan 23 Summary: F2 雙版本說明文件（醫師一頁指引＋維運手冊）與 F6 舊 P0 結案核對

## 1. 任務概述
- **F2 醫師操作一頁指引**: 產出 `docs/CLINIC_QUICKSTART_DOCTOR.md`，以 A4 單頁為排版設計，國小理解度編排、零專有名詞，清楚圖解「三顆燈」（綠燈開始、紅燈結束、黃燈存檔）日常用法與三大自救招式。
- **F2 安裝與維運手冊**: 產出 `docs/CLINIC_DEPLOYMENT_GUIDE.md`，提供 Ubuntu 主機安裝、Windows 診間安裝、備份隨身碟設定，並特別加註 D-32-10 SmartScreen 警告繞過指引（「其他資訊」➔「仍要執行」）與 SHA-256 完整性檢查（T-32-23-01）。
- **F6 歷史 P0 項目結案核對**: 逐項核對 `codeimproveplan.md` 的所有 P0 事項（月報寄送停用、金鑰洩漏移除與網段認證、批次狀態正確性等），確認全數結案並更新 `Fable5.2improvplan.md` 第七節。

## 2. 成果與驗證
- **新增檔案**:
  - `docs/CLINIC_QUICKSTART_DOCTOR.md` (醫師版一頁式指南，含「三顆燈」與三招自救)
  - `docs/CLINIC_DEPLOYMENT_GUIDE.md` (現場安裝維運人員指引，含 SmartScreen 處理說明與網路 FAQ)
- **修改檔案**:
  - `Fable5.2improvplan.md` (更新 Section 7.3，確認各項目完工狀態)
- **驗證命令**:
  - `test -f docs/CLINIC_QUICKSTART_DOCTOR.md && grep -q "三顆燈" docs/CLINIC_QUICKSTART_DOCTOR.md && test -f docs/CLINIC_DEPLOYMENT_GUIDE.md && grep -q "SmartScreen" docs/CLINIC_DEPLOYMENT_GUIDE.md` PASS。

## 3. 威脅模型處置
- T-32-23-01 (Tampering): 部署手冊明確要求現場維運人員在執行未簽章之安裝檔前，先以 PowerShell 比對 SHA-256 雜湊值，防範傳輸或儲存媒介遭惡意替換。
