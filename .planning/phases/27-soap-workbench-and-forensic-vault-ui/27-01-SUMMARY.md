# Phase 27 總結報告：診間即時 SOAP 工作台、護理錄製監控與司法病歷金庫 UI (27-soap-workbench-and-forensic-vault-ui)

## 📌 任務目標與交付回顧
本階段（Phase 27）依據使用者需求與介面升級規範，在系統頂部新增第 4 個主要工作頁面，完成診間護理即時錄製監控、結構化 SOAP 表單編輯、歷史門診病患查詢時間軸，以及符合健保實地審查與法庭證據保全標準的多媒體證據金庫與數位簽章封存下載功能。

---

## 🚀 核心交付項目

### 1. 頂部導航與暗色擬態（Glassmorphism）介面佈局
- 在最上方頂部導航列 (`.mode-switcher`) 新增第 4 頁簽：
  - `🎙️ 4. 診間即時 SOAP (錄製監控 / 結構化病歷 / 法院證據包)` (`#tabMode4`)
- 設計兩欄式響應式工作台佈局 (`.soap-workbench-layout`)，完美融合現有系統的深夜深藍 `#0b0f19`、`#0f172a` 與青藍色 `#06b6d4`、`#38bdf8` 霓虹光暈。

### 2. 左側：病患查詢歷史時間軸與護理即時錄製卡
- **歷史病患多維查詢**：
  - 支援以身分證字號（如 `F229871234`）或出生年月日（民國 `0681120` 或西元 `1979-11-20`）搜尋。
  - 動態渲染歷史門診時間軸卡片（顯示日期、ICD-10 代碼、疾病標題、佐證生檔數量膠囊）。
  - 點選任一門診日期，右側立即載入該次看診之完整 SOAP 與對應金庫多媒體檔案。
- **護理專員即時錄製中監控卡**（左下角）：
  - 紅色高亮呼吸燈 (`.pulse-dot`) 與 `即時錄音中` 狀態。
  - 即時看診時長計時器（`00:01:24`，每秒平滑遞增）。
  - 看診序號與病患膠囊標籤（病患姓名、身分證號、年齡、性別）。
  - 12 段動態音頻等化器聲波長條圖 (`.waveform-bar`，每 600ms 動態隨機跳動模擬即時收音）。
  - ASR 逐字稿即時跑馬字幕條 (`.live-transcript-ticker`，展示最新辨識文句）。
  - `⏹️ 結束錄音並生成病歷` 與 `⏸️ 暫停` 按鈕。

### 3. 右側：完成的結構化 SOAP Form 與快捷操作
- **4 大區塊結構化病歷編輯器**：
  - `[S] 主訴 (Subjective)`：病患主訴、發病經過、全身症狀。
  - `[O] 客觀檢查 (Objective)`：理學檢查、生命徵象、X-Ray 影像發現、健保雲端檢驗紀錄。
  - `[A] 診斷評估 (Assessment)`：ICD-10 主次診斷與中文病名。
  - `[P] 處置治療 (Plan)`：開立藥物、物理治療、醫囑衛教、[自費項目推薦建議]。
- **頂部快捷操作**：
  - `📋 複製 SOAP`：一鍵格式化複製至剪貼簿。
  - `📤 寫入 HIS`：直連 Phase 26 之 Windows UI Automation / Agent-Desktop 背景無頭回填。
  - `📦 下載法院/審查佐證包 (ZIP)`：觸發金庫打包導出。
  - `🖨️ 列印法院病歷單`：呼叫系統列印視窗。

### 4. 法院 / 健保審查多媒體證據金庫 (Forensic Vault Box)
- **多媒體播放與生檔預覽**：
  - 原生 HTML5 音訊播放器（`<audio controls>`），可直接試聽門診錄音檔。
  - 多媒體檔案網格清單（`.forensic-files-grid`）：區分音訊 (`audio`)、醫療影像 (`images`)、檢查報告 (`reports`)。
- **司法保全與數位防竄改認證**：
  - SHA-256 數位雜湊封存標籤與防竄改驗證徽章 (`#soapSha256Fingerprint`)。
  - 一鍵打包下載法院／審查專用 ZIP 佐證包 (`GET /api/soap/cases/<case_id>/export-forensic-zip`)，內部結構包含：
    1. `SOAP_RECORD.txt`（具法律效力之書面證明，載明病患資訊、就診時間、4 段 SOAP 與保全聲明）。
    2. `SOAP_RECORD.json`（原始數據結構）。
    3. `evidence/audio/*` 與 `evidence/images/*`（門診原始音訊與 DICOM/WebP 影像）。
    4. `SHA256_CHECKSUM.txt`（全數檔案之 SHA-256 Checksum 數位封印清單）。
    5. `AUDIT_TRAIL.json`（司法調閱審計存取日誌）。

---

## 🛡️ 安全與合規性驗證
- **零安全漏洞（No innerHTML Injection）**：
  - 嚴格遵守 `test_ingest.py` 之 `test_frontend_case_list_does_not_use_innerhtml_templating` 規範，所有動態節點完全透過 `document.createElement()`、`textContent` 與 `appendChild()` 構建，全檔不含任何不安全的 innerHTML 字串模板。
- **純離線閉環（Offline Air-Gap）**：
  - 全檔無任何外部 CDN、外部 Web Fonts 或外連 JS/CSS 依賴，100% 通過 `test_frontend_has_no_external_resource_links`。

---

## 🧪 自動化測試結果
- 新增測試套件：[`tests/test_soap_workbench_ui.py`](file:///home/hsu/Desktop/Elcinsurrence/tests/test_soap_workbench_ui.py)
  - `test_soap_live_session_api`: **PASSED**
  - `test_soap_search_patient_api`: **PASSED**
  - `test_soap_case_bundle_api`: **PASSED**
  - `test_soap_export_forensic_zip_api`: **PASSED**
- 既有回歸測試套件：
  - `tests/test_ingest.py` (26 tests): **PASSED**
  - `tests/test_soapvoice_ingest.py` (2 tests): **PASSED**
  - `tests/test_webbrain_bridge.py` (6 tests): **PASSED**
  - `tests/test_agent_desktop_bridge.py` (8 tests): **PASSED**
  - `tests/test_stage2_3_buttons.py` (3 tests): **PASSED**
- 測試總計：**49 passed in 15.92s (100% 通過，0 失敗)**。


---

## 🌟 互動模式重大升級：左側病患時間軸展開與內定全自動即時進程

### 1. 左側側邊欄（Sidebar）病患清單與就診日期展開
- **搜尋即加入**：在搜尋框輸入身分證號或出生年月日查詢後，自動將病患加入左側清單。
- **點選展開多次門診紀錄**：
  - 內建 3 位典型病患（#1 陳美玲、#2 王大明、#3 李阿土）。
  - 當點選左側第三位病患（李阿土，`H120987654`）時，名字下方立即滑出展開多次就診紀錄：
    - `📅 1120912 門診` (M17.0 退化性關節炎，3生檔)
    - `📅 1120801 門診` (M54.5 下背痛，2生檔)
    - `📅 1120615 門診` (I10 本態性高血壓，2生檔)
  - 點選任一天就診日期，立即調出該日期的就診紀錄 SOAP、原始錄音檔（audio player）與影像/報告生檔。

### 2. 內定即時模式 vs 歷史調閱與打包模式
- **內定即時進程模式（未點選歷史病患時）**：
  - 全程自動，無須人為介入！
  - 頂部狀態：`🔴 診間即時自動生成中 (Live Stream · 全程自動處理)`。
  - 右側主工作區即時呈現護理專員正在錄製的門診進程，S/O/A/P 隨 ASR 字幕即時自動生成。
  - **隱藏打包按鈕**（不顯示 `下載法院/審查佐證包 (ZIP)`），金庫區提示為「即時門診錄音暫存中 · 結束門診自動封存」。
- **歷史調閱與打包模式（點選左側歷史病患/日期後）**：
  - 頂部狀態切換為：`🏛️ 歷史病歷調閱與司法保全 (病患: 李阿土 · 1120912 門診)`。
  - 顯著亮出 `📦 下載法院/審查佐證包 (ZIP)` 按鈕供司法與審查使用。
  - 提供 `🔴 返回即時錄音監控` 按鈕，隨時可一鍵切回內定全自動即時進程。
