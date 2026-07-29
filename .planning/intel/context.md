# Context Intel (from DOC sources)

source: 電子抽審.md (DOC, precedence 2, high confidence)
Title: 雲端 HIS 系統整合健保電子抽審與電子申覆技術與實務實作指南

## Topic: 台灣健保署電子抽審/電子申覆背景
健保署電子抽審與電子申覆需橋接雲端架構與地端健保VPN封閉網路（需讀卡機與SAM卡）。雲端HIS無法直接把資料丟給健保署，需透過地端代理程式(Local Agent)呼叫NHI_EIIAPI.DLL（NHI_SendA/NHI_SendB）由本地硬體完成簽章加密後上傳。
source: 電子抽審.md §一

## Topic: 紙本作業流程 (As-Is)
健保抽審通知 → 列印清單 → 人工調閱紙本病歷 → 影印(病歷/檢驗/X光/超音波/CT/MRI/處方) → 人工整理 → 填寫送審封面 → 郵寄 → 等待審查 → 收到核減通知 → 人工撰寫申覆理由 → 再次郵寄。
source: 電子抽審.md §一(As-Is流程圖)
Relevance: motivates the automation this project provides (病歷補強 avoids manual reinforcement at submission time; 申復生成 avoids manual appeal-writing after denial)

## Topic: 電子抽審/申覆 To-Be 流程（doctor-toolbox 生態系參考）
電子抽審: 健保抽審通知(XML)→雲端HIS自動下載→自動整理(門診病歷/SOAP/檢驗/影像/醫囑/處方)→自動產生PDF→Agent下載→SAM卡簽章→VPN→健保署
電子申覆: 收到核減通知→雲端HIS→解析核減XML→醫師輸入申覆理由→系統自動產生XML→Agent→VPN→健保署→完成申覆
source: 電子抽審.md §二, §三
Relevance: this is the Phase 2 (HIS-integrated) end-state this project's Phase 1 engine will eventually plug into.

## Topic: 院所行政前置申請作業
VPN權限開通（醫事機構負責人憑證登入VPN，申請「電子化專業審查系統」）→試傳2~5筆虛擬測試資料，成功後2小時內電話確認→雙軌並行送審階段→確認影像品質後轉單軌無紙化。品質不良累計輔導兩次未改善會被取消電子送審資格半年。
source: 電子抽審.md §五
Relevance: Phase 2 operational/administrative prerequisite, not engineering scope.

## Topic: doctor-toolbox / DrtoolboxLocalServer 生態系
Referenced as the existing local-server tech stack this project reuses (D4) and the target Phase 2 HIS module host (D1). 電子抽審.md documents the broader Cloud HIS + Local Agent architecture (EMR/PACS/Billing/Claim/Appeal Engine in cloud; Job Scheduler/XML Validator/PDF-DICOM Checker/NHI_EIIAPI Wrapper/Retry Queue in Local Agent) that doctor-toolbox's HIS integration target resembles.
source: 電子抽審.md §5.6, §5.8

## Topic: UML/ER reference material (研究計畫附錄，非工程規格)
Use Case (醫師/護理師/醫事人員/Cloud HIS/Local Agent/NHI IDC), Activity Diagram (電子抽審/電子申覆流程), Sequence Diagram, Database ER Model (Patient/Encounter/MedicalRecord/Attachment/AuditCase/Appeal/TransmissionLog), FHIR/HL7 mapping table.
source: 電子抽審.md §5.1-5.8
Relevance: background research material for eventual Phase 2 Cloud HIS design; not required for Phase 1 local engine. Kept as reference context only.

## Topic: 建議研究計畫六階段
第一階段現況分析(As-Is)、第二階段雲端HIS架構設計、第三階段Agent與VPN橋接設計、第四階段XML/PDF/DICOM自動打包、第五階段電子申覆XML自動生成、第六階段試傳驗證與正式導入。
source: 電子抽審.md §五(表格)
Relevance: this describes a broader academic/HIS-vendor research roadmap distinct from (and larger scope than) the elc-audit-engine Phase 1/Phase 2 roadmap in progress.md — noted as background, not adopted as this project's roadmap.

## Topic: 紙本表單參考資料
專業審查作業紙本病歷替代方案申請書（申請範圍：全部電子送審 / 部分電子送審PACS）；紙本病歷替代方案流程（提出申請→健保署審核資格→VPN權限→安裝元件→試傳2~5筆→確認成功→正式電子送審→雙軌→全面無紙化）。
source: 電子抽審.md §四(1)(2)
