# 診所區域網路 AI 自動化與電子病歷/健保申報系統全域實作計畫書 (plan-v4.md)

## 1. 系統總體概述與商業戰略定位 (System Overview & Trojan Horse Strategy)

本計畫書（`plan-v4.md`）旨在構建一套專為台灣基層診所（醫療院所）量身打造的**區域網路（LAN）分布式 AI 自動化與電子病歷/健保申報系統**。系統深度整合十大核心組件與專案——包含 **SoapVoice**（臨床語音轉 SOAP 與醫療知識圖譜）、**Elcinsurrence**（健保電子抽審與申復自動化引擎）、**agent-desktop**（桌面型 GUI 自動化 CLI/MCP）、**WebBrain**（網頁型 AI 代理與 MCP Bridge）、**PageIndex + llama.cpp + SQLite**（雙軌檢索與自動更新）、**雙欄響應式審查介面**（HTML5 申覆與影像連動）、**STAR HIS 大容量歷史病歷 ETL**，以及**健保局 EDI/XML 申報格式對接**。

### 1.1 「特洛伊木馬」切入戰略 (Trojan Horse Strategy)
傳統醫療資訊系統（HIS）市場具備極高的舊系統鎖定效應（Lock-in Effect）。診所醫師習慣於既有 HIS（如展望、志氏、耀聖）的操作介面，更換整體 HIS 面臨龐大的學習成本與資料遷移風險。
* **非侵入式 AI 助手切入**：本系統不強迫診所替換原有 HIS，而是將 **Little B 懸浮面板 GUI** 與 **SoapVoice 語音採集用戶端** 作為「特洛伊木馬」外掛於現有 Windows 桌面。
* **雙軌 UI 自動化寫入**：利用 `agent-desktop` 模擬點擊與鍵盤輸入，自動將 SOAP 病歷與 ICD-10 診斷碼寫入展望等傳統桌面 HIS；利用 `WebBrain` 自動化預讀健保雲端 2.0 藥歷與操作網頁型 HIS。

### 1.2 自費醫療市場與健保雙軌營運模式
基層診所面臨健保總額點值壓抑（點值約 0.8~0.9），轉向高毛利「自費醫療市場」（如醫美、微創、高階保健、皮膚科、骨科自費療程）是財務永續的關鍵：
* **自費與健保收據雙軌拆單**：支援「一張健保收據 + 一張自費專用收據」，診所可自訂自費單項金額並記憶上次列印選項。
* **LINE 24h 智慧櫃檯與病患關懷**：結合 `Doctor Toolbox` 智慧衛教問答與預約導流，利用真實醫病對話數據訓練個案衛教機器人，在候診期預先完成問診表單，引導患者回診。
* **商業保險時效提示**：SOAP 語音摘要自動識別外傷與車禍事件，當事故超過 2 年常見理賠時效時，主動於 Little B 面板提示醫師提醒病患。

### 1.3 商業模式與階段性獲利架構
* **診所訂閱方案**：以單診所年費約 NT\$ 30,000 / 年（或基本安裝 NT\$ 12,000 + 每月使用量抽成）進入市場，目標首年導入 20+ 連鎖診所（年營收 NT\$ 60 萬+），第二年擴展至 1,000+ 診所生態圈（年營收 NT\$ 3,000 萬+）。
* **B2B 生態系集成**：整合自費耗材、高價藥品、診所 PACS 醫療影像（手持超音波、外傷照片）與檢驗所平台，作為平台整合商（Aggregator）獲取分潤。

---

## 2. 區域網路分布式 Server/Client 拓撲與自動尋址 (LAN Topology & ZeroConf)

系統採用「一機多端」的區域網路（LAN）架構，確保**所有特種個人醫療資訊（PHI）完全不離開診所內網**，達成 PHI Zero-Cloud Leak 的最高資安標準。

### 2.1 節點職責與架構拓撲

```
               +-------------------------------------------------------+
               |            診所區域網路 (LAN: 192.168.x.x)             |
               +-------------------------------------------------------+
                                           |
                                           v
                     +-------------------------------------------+
                     |    Server 端 (診所中央伺服器 / 主機)      |
                     |  - Elcinsurrence Core (Flask Port 5000)   |
                     |  - SoapVoice Engine (FastAPI Port 8010)   |
                     |  - llama.cpp Server (GPU/CPU Inference)   |
                     |  - 三層 SQLite (medical_kb/cases/attach)  |
                     |  - ZeroConf / mDNS Broadcast Daemon       |
                     +-------------------------------------------+
                                  /                 \
                                 /                   \ (mDNS / UDP Discovery)
                                v                     v
      +----------------------------------+   +----------------------------------+
      |  Client 端 (診間醫師工作站)      |   |  Client 端 (櫃檯工作站)          |
      |  ClinicClientInstaller.exe       |   |  ClinicClientInstaller.exe       |
      |  - Little B Floating GUI         |   |  - Little B Check-in GUI         |
      |  - SoapVoice WASAPI Recorder     |   |  - WebBrain Node.js & MCP Bridge |
      |  - agent-desktop.exe (UI Auto)   |   |  - 健保卡/IC卡雙卡讀卡機對接      |
      |  - 桌面 HIS (展望/志氏/耀聖)     |   |  - 網頁 HIS / 健保雲端 2.0        |
      +----------------------------------+   +----------------------------------+
```

### 2.2 節點硬體與軟體組態規範

| 節點類型 | 硬體需求 | 關鍵軟體模組 | 核心職責 |
| :--- | :--- | :--- | :--- |
| **Server 端 (診所中央主機)** | Windows 10/11 / Linux<br>(建議 GPU: RTX 2080 Ti / 3060 12GB 或高階多核 CPU) | 1. Elcinsurrence Core Server (Flask Port 5000)<br>2. SoapVoice Engine (FastAPI Port 8010)<br>3. `llama-server` (Gemma 4 E4B / Qwen2.5-7B)<br>4. 3-Tier SQLite Databases<br>5. Zeroconf Server Service | - 門診對話 ASR 與 SOAP 病歷生成<br>- 健保事前預審三方邏輯比對<br>- 申復 XML/PDF 導出與 CaseStore 案件管理<br>- 局域網廣播與 API Key 認證過濾 |
| **Client 端 (診間醫師工作站)** | Windows 10/11<br>(無需獨立 GPU) | **`client.exe` (單一安裝包)**：<br>1. Little B GUI + SoapVoice Recorder Client<br>2. LAN Auto-Discovery Module<br>3. `agent-desktop.exe` CLI/FFI DLL | - 採集診間醫病對話音檔<br>- 接收 SOAP 病歷與健保預審燈號<br>- 自動定位並寫入桌面型 HIS 視窗 |
| **Client 端 (櫃檯工作站)** | Windows 10/11<br>(接健保卡讀卡機) | **`client.exe` (單一安裝包)**：<br>1. Little B UI (櫃檯掛號報到模組)<br>2. WebBrain Node.js Bundle & MCP Server<br>3. 健保卡/醫事人員卡 (HCA/HC) 讀卡機 | - 門診掛號與健保 IC 卡讀取<br>- 自動化操作健保雲端 2.0 預讀藥歷<br>- 重復開藥與過敏提醒發送 |

### 2.3 零設定自動尋址與握手協定 (ZeroConf / mDNS)
為達成診所「開箱即用、免設定 IP」之體驗，`client.exe` 啟動時執行多層次自動發現：
1. **mDNS 多播廣播**：`client.exe` 開機啟動後發送 mDNS 查詢（`_elc-soap._tcp.local.`）。
2. **Server 端響應**：伺服器回應其局域網 IP（如 `192.168.1.100`）與服務 Ports（5000 / 8010）。
3. **UDP 廣播備援 (UDP Broadcast Fallback)**：若診所路由器封鎖 mDNS 多播（Multicast），`client.exe` 自動改發 UDP 廣播封包（Port 5001），Server 收到後回應握手資訊。
4. **HealthCheck 探測與雙向認證**：Client 呼叫 `GET /api/health`（免 Key 健康檢查），確定服務正常後帶入 Header `X-API-Key: <secret_key>` 完成安全驗證與連線綁定。
5. **離線緩衝區 (Offline Buffer)**：若局域網短暫中斷，`client.exe` 將採集的音檔與預審請求暫存於本地 SQLite 緩衝庫，待網路復原後自動重傳。

---

## 3. SoapVoice 語音病歷與雙軌檢索/更新引擎 (Voice-to-SOAP & Hybrid RAG Engine)

### 3.1 語音採集、ASR 與詞彙熱度校正
* **語音採集**：Client 端透過 Little B 面板調用 Windows WASAPI / PyAudio 進行高採樣率音訊錄製。
* **ASR 語音辨識**：Server 端採用 `faster-whisper-medium` 或 `whisper.cpp` 進行中英文混合語音識別。
* **詞彙熱度校正 (`keywords.json`)**：整合 `DrtoolboxLocalServer` 臨床圖譜中的 2.6 萬個醫療實體節點（疾病、症狀、處置、藥名），加載至 ASR 字典中，防止專科術語（如「琥乙紅黴素」、「Triamcinolone」）被誤判為口語詞彙。

### 3.2 LLM 結構化 SOAP 生成與臨床合規防線 (ClinicalComplianceGuard)
由 `llama.cpp` 載入 **Gemma 4 E4B (Q4_K_M, 9.6GB)** 或 **Qwen2.5-7B-Instruct (Q4_K_M, 4.4GB)**，將診間對話轉換為英文 SOAP 病歷：
* **S (Subjective)**：主訴症狀（≤ 50 字，標準英文醫療術語）。
* **O (Objective)**：理學檢查與生命徵象數據。
* **A (Assessment)**：診斷名稱與 ICD-10 代碼（比對 `medical.db` 96,802 筆診斷碼）。
* **P (Plan)**：處方藥物、處置醫令（比對 12,042 筆藥品檔與 2,102 筆處置碼）與衛教重點。
* **CONVERSATION_SUMMARY**：繁體中文對話摘要（≤ 100 字），記錄患者個人習慣、過敏史與長期治療計畫，存入系統交班本。
* **合規防護 (ClinicalComplianceGuard)**：比對 `medical.db` 內 30 萬條臨床知識關聯，若偵測到忌吃食物或用藥禁忌（如高血壓開立 NSAIDs）自動發出 CRITICAL 警告。

### 3.3 雙軌混合檢索架構 (Hybrid Search: FTS5 + PageIndex)

```
                       [ 診所查詢 / 預審請求 ]
                                  │
         ┌────────────────────────┴────────────────────────┐
         ▼                                                 ▼
【結構化代碼精確搜尋】                             【非結構化規範語意檢索】
  SQLite FTS5 全文檢索                              PageIndex / SQLite-Vector
  - 9.6 萬 ICD-10 代碼                               - 《西醫基層審查注意事項》PDF/DOCX
  - 1.2 萬藥品檔 (ATC碼/支付價)                       - 藥品仿單與條文原文
  - 2,102 筆醫療服務醫令                              - 頁碼 (Page) & 章節 (Section) 定位
  - 毫秒級回應，零 CPU/GPU 計算開銷                   - 展現原文書頁，解決預審「薄弱」與「裸奔」
```

### 3.4 健保新規則與模型自動更新管線 (Auto-Update Pipeline)
健保署定期發布最新藥品給付價檔（如 `支付價大於0.csv`）、醫令清單與審查規定，系統在伺服器端建立不中斷服務的自動更新機制：
1. **背景 Task 探測 (每日 02:00)**：Python 背景任務自動下載健保署 Open Data 最新 CSV/PDF。
2. **DB 增量更新 (ETL & Version Diff)**：比對版本 Hash (`source_version`)，透過 `INSERT OR REPLACE INTO` 自動更新 `medical_kb.sqlite` 中的代碼與藥價。
3. **PageIndex 增量編譯**：僅對新修訂的條文章節進行 Incremental Re-indexing，避免全量重新編譯。
4. **LLM 模型背景熱切換 (Hot Swap & Fallback)**：讀取 `models/manifest.json`，當下載新版 GGUF 模型後，在離峰時段重啟 `llama-server`；若加載失敗則自動降級（Fallback）至舊版模型。

---

## 4. Elcinsurrence 健保電子抽審與申復自動化 (Audit & Appeal Pipeline)

### 4.1 抽樣事前預審工作流 (`POST /api/sampling/audit`)
* **性質**：**唯讀 (Read-only)**，不產生申復草稿、不寫入磁碟檔案（預審時尚無核減資料）。
* **邏輯**：接收 SOAP 病歷、ICD-10 與醫令碼，比對 Phase 2 SQLite 規則庫（13,942 條支付標準）。
* **5 階段判決結果**：
  * **✅ 充分**：病歷明確記載醫療必要性，符合給付規定。
  * **⚠ 薄弱**：缺少特定記載（如傷口尺寸、檢驗數據），回傳 `reinforcement_advice` 提示醫師補強。
  * **❌ 裸奔** (`support_level == "裸奔"`)：病歷完全未記載要件。
  * **⏳ 待判定** (`support_level == null` 且 `undetermined == true`)：LLM 服務逾時或系統異常（絕不偽裝成裸奔）。
  * **❓ 查無規則** (`support_level == null` 且 `rule_found == false`)：規則庫無該醫令條文（如新特藥）。

### 4.2 核減事後申復工作流 (`POST /api/appeal/generate`)
* **4 段式申復理由自動組裝**：依 D10 標準產出 ①案情摘要 ②醫療必要性（半年病史） ③規則依據（條文原文） ④病歷佐證（醫師採納補強）。
* **字數嚴格裁剪**：依健保局 Q15 規範，**p8 (理由一) 與 p9 (理由二) 各中文字數 ≤ 1000 字**（超限時自動優先裁剪段落 ④ 與 ②，保留 ① 與 ③ 骨架）。
* **特殊字元轉換**：半形角括號與引號 (`< > & ' "`) 自動轉換為全形 (`＜ ＞ ＆ ＇ ＂`)，避免 XML 解析失敗。

### 4.3 申復 XML 序列化與 PDF 佐證包打包導出
* **XML 序列化 (`scripts/build_appeal_xml.py`)**：將申復草稿序列化為符合健保局規範之 **tdata + ddata + pdata** Big5 編碼 XML 檔案。
* **紙本申復清單與佐證包 (Phase 11 / 13 / 14)**：
  * 使用 `python-docx` 建立 A4 版面，經由本機 LibreOffice Headless (`soffice --convert-to pdf`) 轉為 PDF。
  * 整合 Pillow + `pillow_heif` 處理超音波/X光/傷口照片，進行 EXIF 自動旋轉與 A4 縮放，產出結構完整的可列印申復佐證包 PDF。

---

## 5. HTML5 雙欄響應式審查介面 (Dual-Pane Interactive Viewer)

為提升審查醫師與診所內部核對效率，系統提供 HTML5 雙欄審查介面（`static/reviewer.html`）：

### 5.1 雙欄面板版面與 UI 架構
* **左側面板 (Left Pane)**：展示 XML 申報數據、SoapVoice S/O/A/P 病歷、核減原因與 p8/p9 四段式申覆理由。含有附件之醫令特別標註 `📷 附影像佐證 (p7=Y)`。
* **右側面板 (Right Pane)**：多媒體佐證檢視器（Evidence Viewer），展示超音波、X 光、傷口照片或 PDF 報告，支援縮放、旋轉與防洩漏浮水印。

### 5.2 XML-Image 雙向資料綁定 (Data Binding)
* **唯一鍵綁定**：在 SQLite 中，影像嚴格透過 `case_id`（案件 Hash 全域唯一鍵）與 `order_code`（醫令碼）進行關聯。
* **雙向互動 (Interactive Sync)**：
  * **點擊左側醫令或申覆理由** ➔ 右側影像區域自動平滑捲動（`ScrollIntoView`）並亮黃框聚焦（`highlight`）。
  * **點擊右側照片卡片** ➔ 左側 XML 內文中引用該照片的 SOAP 段落自動高亮顯示。

---

## 6. agent-desktop & WebBrain 雙軌 UI 自動化 (Desktop & Web Automation)

針對台灣診所異質化的 HIS 環境，系統提供雙軌自動化代理機制：

### 6.1 agent-desktop 桌面型 HIS UI 自動化 (展望、志氏、耀聖)
* **無障礙樹讀取**：`agent-desktop` 透過 Windows UI Automation API 獲取門診視窗之 Accessibility Tree JSON，完全不依賴螢幕截圖或像素比對。
* **Ref 標籤識別與填寫**：定位視窗中的 `CC:`（主訴）、`PE:`（理學檢查）、`Dx`（診斷）與 `Rx`（處方）欄位 `@ref` 標籤，發送 `click` 與 `type` 指令寫入 SOAP。
* **Headless 預設模式**：預設為背景 Headless 操作，不搶奪實體滑鼠游標與視窗焦點；需要實體動作時可加上 `--headed` 參數。

### 6.2 WebBrain 網頁型 HIS & 健保雲端 2.0 自動化
* **WebSocket Bridge 握手**：WebBrain Chrome/Edge 擴充功能連線至 Client 端 MCP Bridge (`ws://127.0.0.1:17374/extension`)，並透過 HMAC 密鑰認證。
* **藥歷預讀與自動填表**：發送 `webbrain_run` 任務，在實體分頁中檢視病患近三個月健保雲端藥歷，抓取重複用藥與過敏紀錄，自動回傳 Little B 面板或寫入網頁版 HIS。

### 6.3 MCP (Model Context Protocol) 整合架構
* **agent-desktop MCP**：呼叫 `agent-desktop mcp` 透過 stdio 暴露原子級桌面工具（`desktop_snapshot`、`desktop_click`、`desktop_type`）。
* **WebBrain MCP Server**：暴露 6 個高階任務級工具（`webbrain_run` 任務執行、`webbrain_extract` 結構化抽取、任務狀態與中斷），保護內部 Agent 權限檢查不被低階操作繞過。

---

## 7. 大容量歷史病歷 CSV 與健保申報檔 ETL 管線 (Data Processing & Ingestion)

### 7.1 STAR HIS 23MB+ 歷史病歷 CSV 批次 ETL
針對診所累積的大容量歷史病歷 CSV（如 `complete_medical_records_star_...csv`，約 23MB）：
1. **資料清洗與編碼自動偵測**：使用 Python `pandas` 處理 `utf-8-sig` / `big5` / `cp950` 編碼，去識別化並整理爛碼。
2. **批次注入與交易保證**：伺服器開啟 WAL 模式，以 Transaction 批次寫入 `clinic_cases.sqlite` 的 `soap_records` 表，作為歷史 RAG 與預審基準。

### 7.2 健保局 EDI / XML 申報明細檔匯入與解析
* **數位檔 (`/api/sampling/import`, `/api/appeal/import`)**：自動解析健保局標準 D-14d 18 欄明細檔及 CSV 抽審清單。
* **紙本與掃描檔 OCR 結構化**：優先調用 **PP-StructureV3** 進行表格結構化解析（`source: "paddle"`）；引擎不可用時自動降級至 **Tesseract OCR**（`source: "ocr"`），以醫令代碼為錨點提取內容。

---

## 8. 三層 SQLite 資料庫 Schema 與資安/合規 (Database Architecture & Compliance)

### 8.1 數據屬性分層架構 (Stratified Database Design)
系統採用多 SQLite 檔案設計，將靜態知識庫與動態業務資料進行隔離，降低併發鎖定概率：

```sql
-- 檔案 1: medical_kb.sqlite (唯讀 Read-Only 知識庫)
-- 包含 icd10_codes (96,802筆), drugs (12,042筆), medical_orders (2,102筆), payment_rules (13,942條)

-- 檔案 2: clinic_cases.sqlite (動態業務與預審庫)
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,               -- 全域唯一 Hash 鍵 (例如 SAMP-20261103-001)
    case_seq TEXT NOT NULL,                -- 門診流水號 (跨月會重複，不可做主鍵)
    record_no TEXT NOT NULL,               -- 病歷號碼
    patient_name TEXT,                     -- 病患姓名 (PHI)
    visit_date TEXT NOT NULL,              -- 就醫日期 (YYYY-MM-DD)
    state TEXT DEFAULT 'imported',         -- 狀態: imported -> reviewing -> reviewed -> appealed
    total_points INTEGER DEFAULT 0,        -- 申報總點數
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS soap_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL UNIQUE,          -- 外鍵關聯 cases(case_id)
    record_no TEXT NOT NULL,
    visit_date TEXT NOT NULL,
    subjective TEXT NOT NULL,              -- S: 主觀症狀 (英文)
    objective TEXT NOT NULL,               -- O: 客觀檢查 (英文)
    assessment TEXT NOT NULL,              -- A: 診斷與評估 (英文)
    plan TEXT NOT NULL,                    -- P: 治療計畫與處方 (英文)
    icd10_codes TEXT,                      -- JSON 陣列: ["L91.0"]
    medical_orders TEXT,                   -- JSON 陣列: ["14050B", "laser_01"]
    conversation_summary TEXT,             -- 繁體中文對話摘要
    raw_transcript TEXT,                   -- 原始語音逐字稿 (備查)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS preaudit_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    order_code TEXT NOT NULL,
    support_level TEXT,                    -- '充分', '薄弱', '裸奔', NULL
    rule_found BOOLEAN DEFAULT TRUE,
    undetermined BOOLEAN DEFAULT FALSE,
    verdict TEXT,                          -- 判定結論
    reinforcement_advice TEXT,             -- 補強建議
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
);

-- 檔案 3: attachments.sqlite (影像佐證索引庫)
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,                    -- 附件 UUID
    case_id TEXT NOT NULL,                 -- 嚴格以 case_id 作為關聯鍵
    order_code TEXT NOT NULL,              -- 醫令碼
    filename TEXT NOT NULL,                -- 安全後檔名 (safe_filename 護城河)
    file_size INTEGER NOT NULL,            -- 檔案大小 (bytes)
    mime_type TEXT NOT NULL,               -- image/jpeg, image/png, application/pdf
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 8.2 SQLite 局域網併發調校與安全設定
在多診間 Client 同時存取 Server 端 SQLite 時，為避免 `database is locked` 異常，Server 端初始化連線時強制執行：
```sql
PRAGMA journal_mode = WAL;          -- 開啟 Write-Ahead Logging 模式，允許讀寫並行
PRAGMA synchronous = NORMAL;         -- 兼顧資料寫入安全與 IO 效能
PRAGMA busy_timeout = 5000;          -- 設定 5 秒 Busy Timeout 佇列排隊緩衝
```

### 8.3 PHI 安全防護與合規規範
1. **主鍵一致性**：`case_seq`（流水號）跨月必定重複，全系統影像佐證、預審 API 與 XML 導出一律以 `case_id` 作為唯一關聯鍵。
2. **審計日誌（PHI-Zero Audit）**：`data/audit/access.log` 僅記錄 `caller_id`、時間戳與 API 路徑，**嚴禁將 SOAP 病歷、病患姓名或身分證號寫入系統 Log**。
3. **路徑穿越防護 (`safe_filename`)**：附件上傳強制進行 Magic Bytes Header 比對與白名單過濾，拒絕包含 `../` 等路徑穿越組件。

---

## 9. client.exe Windows 打包與 Inno Setup 部署 (Packaging & Deployment)

為滿足診所「雙擊即安裝、開機即連線」之需求，Client 端整合包將 Little B 懸浮 GUI、SoapVoice Recorder、`agent-desktop.exe` 與 WebBrain Node.js 組件打包為單一 `ClinicClientInstaller.exe`。

### 9.1 安裝後目錄結構 (`C:\Program Files\ClinicClient\`)

```
ClinicClient/
├── ClinicClient.exe               # Little B 主進程 GUI + SoapVoice Recorder Client
├── config.json                    # 客戶端連線、API Key 與 Server IP 配置
├── resources/
│   ├── bin/
│   │   ├── agent-desktop.exe      # 預編譯 Windows agent-desktop CLI 二進位檔
│   │   └── libagent_desktop_ffi.dll # C-ABI FFI 動態函式庫
│   ├── webbrain/
│   │   ├── node.exe               # 獨立打包 Node.js 執行環境 (無需用戶預裝 Node)
│   │   ├── mcp-server.js          # @webbrain/mcp-server 打包檔
│   │   └── extension.crx          # Chrome / Edge WebBrain 擴充功能套件
│   └── assets/
│       └── icons/                 # Little B 燈號與 UI 圖示
└── logs/
    └── client_runtime.log         # 用戶端執行日誌
```

### 9.2 Inno Setup 編譯腳本 (`installer.iss`)

```iss
[Setup]
AppName=Clinic AI Client
AppVersion=4.0.0
DefaultDirName={autopf}\ClinicClient
OutputBaseFilename=ClinicClientInstaller
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest

[Files]
Source: "build\ClinicClient.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "build\resources\*"; DestDir: "{app}\resources"; Flags: recursesubdirs
Source: "build\config.json"; DestDir: "{app}"; Flags: onlyifdoesntexist

[Icons]
Name: "{userstartup}\ClinicClient"; Filename: "{app}\ClinicClient.exe"; Parameters: "--autostart"
Name: "{autoprograms}\Clinic AI Client"; Filename: "{app}\ClinicClient.exe"

[Run]
Filename: "{app}\ClinicClient.exe"; Description: "啟動 Clinic AI Client"; Flags: nowait postinstall
```

---

## 10. 5 階段開發與診所現場導入時程藍圖 (Implementation Roadmap)

| 階段 | 階段名稱 | 核心開發與導入任務 | 驗收與交付標準 |
| :--- | :--- | :--- | :--- |
| **Phase 1** | **核心 API 網關與 SQLite 整合** | 1. 建立 SoapVoice 與 Elcinsurrence 統一 REST API 網關。<br>2. 建立 SOAP 自動轉接事前預審數據管道。<br>3. 整合 `medical_kb` (9.6萬 ICD-10) 與 `clinic_cases` WAL 模式。 | SOAP 產出可自動取得「充分/薄弱/裸奔」判決並持久化，查詢 Latency < 200ms。 |
| **Phase 2** | **雙軌自動化 Agent 橋接** | 1. 配置 agent-desktop 展望/志氏/耀聖 HIS 視窗 `@ref` 映射。<br>2. 建立 WebBrain WebSocket Bridge 握手與 MCP 任務對接。<br>3. 撰寫展望 HIS 與健保雲端 2.0 自動填入與藥歷預讀腳本。 | 點擊按鈕可成功將 SOAP 自動填入展望 HIS 主訴/檢查欄位，並完成雲端藥歷預讀。 |
| **Phase 3** | **局域網 ZeroConf 自動尋址** | 1. 實作 Server mDNS Zeroconf 廣播與 UDP Broadcast 探測。<br>2. 實作 API Key 雙向驗證與 Host 白名單。<br>3. 建立連線中斷本地離線緩衝區 (Offline Buffer)。 | Client 端啟動後 3 秒內自動發現 Server IP 並完成健康檢查與握手。 |
| **Phase 4** | **`client.exe` Windows 打包** | 1. 建置 Little B 懸浮 GUI 與 SoapVoice WASAPI 錄音端。<br>2. 內嵌 agent-desktop.exe 與 WebBrain Node.js 組件。<br>3. 使用 Inno Setup 編譯產出單一 `ClinicClientInstaller.exe`。 | 單一 `.exe` 安裝包能在乾淨 Windows 10/11 順利一鍵安裝執行，並常駐工作列。 |
| **Phase 5** | **診所現場場域測試** | 1. 於合作診所部署 LAN Server 與雙診間 Client。<br>2. 進行真人門診語音測試、自費/健保拆單收據與預審驗證。<br>3. 驗證申復 XML 導出格式與 HTML5 雙欄審查介面連動。 | 門診看診過程中 SOAP 生成與預審填入整體耗時 < 15 秒，申覆 XML 通過健保署格式檢核。 |

---

## 11. 結論

本計畫書（`plan-v4.md`）完成了台灣基層診所 AI 自動化與健保申報系統的全域架構設計。透過將 SoapVoice 語音病歷、Elcinsurrence 健保預審/申復引擎、agent-desktop 桌面自動化與 WebBrain 網頁代理完整打包為單一 `client.exe`，診所無需替換現有 HIS，即可在零個資外洩風險的局域網環境下，實現極簡化部署、大幅降低健保核減率，並順利拓展高毛利自費醫療市場。
