# Decisions Intel (from ADR sources)

source: progress.md (ADR, precedence 0, LOCKED, high confidence)
All 12 decisions below are LOCKED — non-negotiable, authoritative over SPEC and DOC content.

## D1 — 兩階段路線 (Two-Phase Roadmap)
Phase 1: 檔案進出的獨立引擎（核心邏輯與資料來源解耦）。
Phase 2: 包成 doctor-toolbox HIS 模組。
source: progress.md §一 D1

## D2 — LLM 引擎
llama.cpp server（localhost:8080），Ornith-1.0-9B Q6_K_XL，n_ctx 32768，OpenAI 相容 API。病歷個資預設不出本機。**（2026-11-10 修訂：唯一例外為 D14 所定的加密夜間備份。）**
source: progress.md §一 D2
Elaborated by: docs/plans/2026-07-29-elc-audit-engine-design.md §2 (config/llama_config.json 模式)

## D3 — 功能範圍
病歷補強（送審前）＋ 申復生成（核減後）共用同一條比對管線，僅輸出不同。
source: progress.md §一 D3
Elaborated by: docs/plans/2026-07-29-elc-audit-engine-design.md §1

## D4 — 技術棧
沿用 `~/Desktop/DrtoolboxLocalServer`：Python + uv、Flask、python-docx、pandas、pageindex、SQLite。
source: progress.md §一 D4
Elaborated by: docs/plans/2026-07-29-elc-audit-engine-design.md §2 (Flask 標註為 Phase 2；ChromaDB 列為輔助棧)

## D5 — 病歷彙整
補強報告須整合近半年雲端病歷（就診紀錄/檢驗/檢查/影像清單），經 Provider 介面取得；未接雲端時以本地檔案頂替。
source: progress.md §一 D5
Elaborated by: docs/plans/2026-07-29-elc-audit-engine-design.md §2, §9 (M4)

## D6 — 規則庫檢索
PageIndex 為主（樹狀導航保留條文層級）＋ rule_mapping 預編譯快取（醫令↔條文離線對照，線上查詢零 LLM 呼叫）；ChromaDB 降為輔助（自由文字/類似案例查詢）。
source: progress.md §一 D6, §三 規則庫分層
Elaborated by: docs/plans/2026-07-29-elc-audit-engine-design.md §3.1-3.3

## D7 — 比對器設計
逐檢核項小問題判定（支持/部分支持/無記載＋引用原文），不讓 9B 模型寫大論文；醫令支持度三級：充分/薄弱/裸奔。
source: progress.md §一 D7
Elaborated by: docs/plans/2026-07-29-elc-audit-engine-design.md §4 (步驟1-3)

## D8 — 候選補強敘述
⚠️/❌ 缺口須生成 1~3 條候選補強敘述供醫師點取加入；只能基於既有病史線索擴寫、無線索時生成提示型候選（不憑空編造）、每條附規則出處。Phase 1 為 Markdown checkbox 檢核表，Phase 2 為 HIS 點選 UI。
source: progress.md §一 D8
Elaborated by: docs/plans/2026-07-29-elc-audit-engine-design.md §4 步驟3 (候選敘述約束1-3)

## D9 — 醫師審核流程
逐條審為主＋整稿確認收尾。逐條四狀態：採用/編輯後採用/略過/標記不符事實（幻覺回饋，品質監控指標）。組裝後整稿自由刪改再定稿。全程留審核軌跡 JSON（狀態、原文、編輯後文、時間）— 合規責任歸屬＋採用率數據飛輪。
source: progress.md §一 D9
Elaborated by: docs/plans/2026-07-29-elc-audit-engine-design.md §5

## D10 — 申復生成結構
p8/p9 組裝式四段：①案情摘要 ②醫療必要性（半年病史）③規則依據（條文原文）④病歷佐證＋醫師採用的補強敘述。每段分開生成、>2000字按 ④→② 優先裁剪、P6 不申覆強制填 0 程式硬檢查、每筆核減醫令獨立生成。
source: progress.md §一 D10
Elaborated by: docs/plans/2026-07-29-elc-audit-engine-design.md §6
Cross-confirmed (non-contradictory) by: 電子抽審.md §三 (p6 強制填0規則、p8/p9 ≤2000中文字長文字欄位定義來源)

## D11 — 錯誤處理與測試
故障分層降級（LLM 逾時→待人工不阻斷整案、病史缺→降級模式並標註）；硬性檢查全 pure function；測試五層：單元/規則庫驗收/LLM判定金標準30組/端到端3案例/真實樣本回放。
source: progress.md §一 D11
Elaborated by: docs/plans/2026-07-29-elc-audit-engine-design.md §7-8

## D12 — 自我學習與分享
三回饋訊號：逐條審狀態（採用率→prompt改進）、標記不符事實（自動長大的金標準測試集）、申復結果（終極ground truth）。成功案例入 ChromaDB 案例庫作 few-shot 範例；累積後走 LoRA（prepare_lora_data.py 路徑現成）。兩級隱私（**2026-11-10 修訂**）：病歷雲端僅存 D14 加密備份，伺服器不持有金鑰；rule_mapping/論述骨架/統計可經 doctor-toolbox 跨診所分享。
source: progress.md §一 D12

---

## System Architecture (LOCKED)
source: progress.md §二

```text
   輸入層                     共用比對引擎 (Core)                  輸出層
─────────────      ┌──────────────────────────────────┐    ─────────────
申報XML(抽審案件)──►│ ① 解析器: XML/核減檔/SOAP          │──► 病歷補強報告.md
核減清單檔      ──►│ ② 病歷彙整器: 近半年雲端病歷整合     │    · 醫令支持度缺口
                   │    (就診紀錄/檢驗/檢查/影像清單)     │    · 半年病史摘要
雲端病歷(半年) ──►│ ③ 規則庫: PageIndex+預編譯快取      │    · 附件建議清單
  Provider介面     │    +支付規定SQLite+ChromaDB輔助     │
                   │ ④ 比對器: 醫令↔規則↔病歷 三方比對   │──► 申復理由草稿
過去申復案例    ──►│ ⑤ 生成器: llama.cpp :8080          │    p8/p9 ≤2000字
                   └──────────────────────────────────┘    +申復XML欄位
```
Elaborated by (output detail addendum, non-contradictory): docs/plans/2026-07-29-elc-audit-engine-design.md §2 adds "候選補強敘述(逐條點選)" to 病歷補強報告.md output bullet list — consistent extension of D8, not a conflict.

## Rule Repository Layering (LOCKED)
source: progress.md §三
1. 結構化層（SQLite）: payment_rules ← 醫療服務給付項目251027準確板CSV；drug_rules ← 藥品項查詢項目檔260605 CSV
2. 條文層（PageIndex）: 語料 officialdocument/審查注意事項/*.doc(x)；rule_mapping 預編譯快取 (醫令代碼,科別,文件版本)→[條文位置,條文全文]
3. 輔助層（ChromaDB）: 自由文字/類似案例查詢
Elaborated by: docs/plans/2026-07-29-elc-audit-engine-design.md §3.1-3.3 (adds: metadata 檢索以就醫科別 d8 過濾; rule_mapping 更新與 DrtoolBox /medicalorderupdate 流程銜接)

---

## D14 — 雲端備份政策（2026-11-10 新增，修訂 D2、D12）
- 預設模式：本機模式（病歷與 SOAP 留在本機，維持醫師既有 HIS 習慣）。雲端只接收加密備份與無病患識別的校正結構；選用網頁版（DrToolbox 全雲端）不作為預設，須待法律確認與資料處理合約後由診所自行選擇。
- 範圍：local server 產生的病歷、SOAP、審核軌跡、校正設定；由 local server 夜間（預設 02:00）事後上傳。
- 加密：客戶端 AES-256-GCM 加密；每診所金鑰在本機產生並保存，雲端只存密文。金鑰遺失即不可還原，須有離線備份金鑰。
- 權限分離（2026-11-10 補充）：下載權限與解密金鑰分離。雲端以診所 local server 憑證控制下載；解密金鑰只存在本機，雲端永不持有。
- 離線金鑰匯出：診所可將解密金鑰匯出為離線檔（加密、由醫師保管），金鑰遺失時以離線檔還原。
- 還原流程：不依賴正在運作的 local server；提供獨立還原工具，可在無 local server 的機器上以離線金鑰還原。
- 授權：每台 local server 以診所專用、可撤銷的備份憑證上傳，僅能寫入本診所命名空間。
- 稽核：每次上傳寫審計紀錄（時間、筆數、雜湊），不含內容。
- 失效容忍：上傳失敗不影響看診，下次重試。
- 最小化：只備份必要欄位；不含病患識別的校正結構可不加密，但仍需授權。
- 合規：上傳前須完成個資法與醫療法確認；本決定不構成法律意見。
source: 使用者決定 2026-11-10；修訂 D2、D12

