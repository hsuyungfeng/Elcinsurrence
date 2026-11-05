# Phase 27 Context: 診間即時 SOAP 工作台、護理錄製監控與司法病歷金庫 UI

## 使用者需求核心規格

使用者明確要求：
> 1. 在畫面抬頭，最上面抬頭的位置增加一個 SOAP 的按鈕頁面。
> 2. 左下角顯示出目前護理專員在錄制的病人。
> 3. 右側則是顯示出完成的 SOAP 的 form。
> 4. 增加一個可以尋找之前病人使用身分證字號或者是出生年月日。
> 5. 可以選擇哪一個日期所做的 SOAP 跟生檔，讓它可以下載，如果需要審查或者是法院使用。

---

## 視覺與工程架構設計原則

1. **極致美感與風格一致性（Beautiful UI & Glassmorphism Design System）**：
   - 延續 Elcinsurrence 現有的 Deep Slate 質感暗色調背景（`#0b0f19`、`#0f172a`）、半透明毛玻璃微光（`backdrop-filter: blur(16px)`）、科技青色（`#06b6d4`）、冷調深藍（`#2563eb`）與警示琥珀（`#f59e0b`）。
   - 與 Phase 23 的 `140px` 側欄收折、`F11` 全螢幕沉浸模式與平滑微動畫完全相容。

2. **頂部導覽四軌分頁整合（Header Navigation Extension）**：
   - 頂部 `.mode-switcher` 擴充第 4 顆頁籤：
     `🎙️ 4. 診間即時 SOAP 與法庭病歷金庫 (即時語音 / 結構化病歷 / 司法調閱包)`。
   - 點擊可在「1. 當月申報預審」、「2. 抽樣事前預審」、「3. 核減事後申復」與「4. 診間即時 SOAP」無縫秒級切換。

3. **左側工作區佈局（雙層分割架構）**：
   - **上半部：歷史病患查詢與日期時間軸**：
     - 提供「身分證字號 (ID Number)」與「出生年月日 (ROC/AD Birth Date)」快速檢索框。
     - 搜尋後列出病患的歷次就診日期卡片（例如：`112/08/15 門診 (感冒發燒)`、`112/07/20 門診 (膝關節痛)`），點選即可切換右側顯示該日期對應之 SOAP 與生檔。
   - **下半部：護理專員即時錄製監控台 (Active Nurse Recording Console)**：
     - 即時卡片：顯示當前診間／護理專員正在錄製之病患（姓名、身分證號、看診序號、主訴快照）。
     - 狀態指示燈：🔴 錄製中（Recording with Pulsing Indicator）/ ⏸️ 暫停 / ⏹️ 停止並自動生成 SOAP。
     - 聲波視覺化動態條（Audio Waveform Visualizer Animation）與即時通話秒數計時器。
     - 即時字幕條（Live Transcript Subtitle Ticker）：動態滾動展示 Whisper / Qwen3-ASR 即時辨識字詞。

4. **右側主工作區佈局（結構化 SOAP Form ＋ 司法金庫生檔）**：
   - **頂部工具列**：
     - 顯示目前選定日期之病患主檔資訊、看診醫師、就醫號次。
     - 快捷動作按鈕：`📋 複製 SOAP`、`📤 寫入 HIS (agent-desktop)`、`📦 下載法院/審查佐證包 (ZIP)`、`🖨️ 列印法院病歷驗證單 (PDF)`。
   - **主欄位（結構化 SOAP Form）**：
     - `S` (Subjective 主訴)：多行高對比編輯區。
     - `O` (Objective 客觀檢查)：支援門診理學檢查、檢驗數值與 WebBrain 雲端藥歷預讀資料。
     - `A` (Assessment 診斷評估)：ICD-10 疾病代碼與中英文病名。
     - `P` (Plan 處置與醫囑)：處置治療計畫、健保處方藥品、自費項目（PRP / 玻尿酸推薦）。
   - **下層：生檔檔案庫與司法調閱專區 (Forensic Evidence Vault)**：
     - 生檔清單：
       - 🎙️ 原始錄音檔（`.opus` / `.wav`）：內建 HTML5 音訊播放器，支援播放、暫停、進度條拖曳與下載。
       - 🖼️ 醫療影像／病歷截圖（`.webp` / `.png` / `.jpg`）：縮圖網格，點擊開啟高清燈箱。
       - 📑 檢驗檢查 PDF / 抽血單。
     - **司法/法院調閱打包引擎（Forensic Export Engine）**：
       - 一鍵打包為完整法院證據 ZIP 檔，內含：
         1. 原始錄音生檔與影像生檔。
         2. 結構化病歷書面報告（含就醫日、看診醫師、完整 SOAP 與處置）。
         3. `SHA256_CHECKSUM.txt` 數位防竄改雜湊指紋清單。
         4. `AUDIT_TRAIL.json` 存取與生成時間戳記（符合台灣醫療爭議調解、刑事自訴與民事損害賠償訴訟證據保全規範）。

---

## 關鍵技術依賴與 API 契約

1. **後端 API 端點新增**：
   - `GET /api/soap/live-session`：取得目前護理專員正在錄製之病患資訊與最新即時文字串流。
   - `POST /api/soap/search-patient`：傳入 `id_card` 或 `birth_date` 查詢病患歷次門診清單。
   - `GET /api/soap/patient/<id_card>/encounters/<visit_date>`：取得特定日期之 SOAP 與 Vault 金庫生檔。
   - `GET /api/soap/export-forensic-vault/<vault_key>`：打包下載符合法庭規範之 ZIP 佐證包（含 SHA-256 雜湊）。
2. **前端靜態檔案**：
   - 全量實作於 [`static/index.html`](file:///home/hsu/Desktop/Elcinsurrence/static/index.html)。
   - 遵守無外部 CDN 依賴（離線資安防護規範）、DOM-Safe XSS 防護規範。
