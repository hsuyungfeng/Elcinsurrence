# Elcinsurrence 健保三軌自動化審核與申復工作台 (v5.1)

`Elcinsurrence` 是一套專為健保門診申報總檔、抽樣預審與核減申復設計的自動化審核與申復輔助引擎（`elc-audit-engine`），提供完整的三軌處理架構（當月預審 ＋ 抽樣預審 ＋ 核減申復）、原生 HIS 系統無頭回填對接（`agent-desktop`）、以及健保 VPN 雲端藥歷 2.0 自動化預讀橋接（`webbrain`）。

---

## 🌟 核心架構與三軌工作流 (Three-Track Automation Architecture)

本系統支援三大獨立運作介面與流程：

### 1. 📊 當月申報檔預審工作流 (Stage 1: Monthly Pre-Audit)
- **目的**：在每月 1~5 號正式申報送出前，針對全院門診 `TOTFA.zip` 總檔進行高單價醫令、特殊藥品與給付規定全量掃描。
- **流程**：導入 `TOTFA.zip` ➔ 串流解析門診清冊 ➔ 健保 C 類與藥品規定即時核對 ➔ 產出視覺化審核卡片與紅黃綠燈統計。
- **入口**：`POST /api/monthly/upload`、[`totfa.py`](src/elc_audit_engine/parsers/totfa.py)。

### 2. 📋 抽樣事前預審工作流 (Stage 2: Sampling Pre-Audit & Packager)
- **目的**：於抽審清單送出健保署前，審核門診病歷並評估「醫令支持度」（✅ **充分** / ⚠️ **薄弱** / ❌ **裸奔**），並掛載歷史錄音影像佐證。
- **流程**：導入抽樣 CSV 清單 ➔ 病歷 SOAP 解析 ➔ 六個月時間軸匹配 ➔ EvidenceVault 佐證庫自動掛載 ➔ 導出標準 `NHI_EIIAPI` 電子抽審封包。
- **入口**：[`run_presubmission_check`](src/elc_audit_engine/pipeline.py)、`GET /api/sampling/export-batch-xml`。

### 3. ⚖️ 核減事後申復工作流 (Stage 3: Post-Deduction Appeal)
- **目的**：針對健保署核減不予核銷之刪減醫令，啟動多源證據自動彙整並生成四段式申復理由書。
- **流程**：導入核減明細 ➔ 連動 Stage 1/2 原始 SOAP 與 Evidence Vault 佐證檔案 ➔ 4 段式申復理由自動組裝 ➔ 導出 Big5 申復 XML (p1~p9) / ODT / 爭議審議 PDF 佐證包。
- **入口**：[`run_case_pipeline`](src/elc_audit_engine/pipeline.py)、[`generators/appeal.py`](src/elc_audit_engine/generators/appeal.py)。

---

## 🚀 Phase 24–26 跨系統整合與自動化引擎

### 1. SoapVoice × Elcinsurrence 診間即時語音注入 (Phase 24)
- **端點**：`POST /api/his/soapvoice-ingest`
- **特性**：直接接收 SoapVoice 語音轉錄結構化 SOAP，自動歸檔語音（`.opus` / `.flac`）與病歷截圖至 `data/vault/{id_card}-{fee_ym}/` 佐證庫，即時執行自費品項（PRP / 玻尿酸）智慧推薦與 C 類支付規定初審。

### 2. WebBrain 健保 VPN 雲端藥歷 2.0 預讀與三軌自動化 (Phase 25)
- **模組**：[`src/elc_audit_engine/webbrain_bridge.py`](src/elc_audit_engine/webbrain_bridge.py)
- **端點**：`POST /api/his/webbrain/nhi-extract`、`POST /api/his/webbrain/action`
- **特性**：利用 `@webbrain/mcp-server` (`ws://127.0.0.1:17374/extension`) 於醫師真實瀏覽器以 `mode="ask"` 唯讀預讀雲端藥歷。自動將近 6 個月檢驗值（HbA1c、LDL-C、eGFR）帶入 SOAP Objective（`[健保雲端檢驗]`），並對比跨院處方進行即時重複用藥警示；支援 24 顆二階與三階工作台按鈕語意化自動化執行。

### 3. Agent-Desktop Windows UIA 原生 HIS 回填與安裝包 (Phase 26)
- **模組**：[`src/elc_audit_engine/agent_desktop_bridge.py`](src/elc_audit_engine/agent_desktop_bridge.py)
- **安裝包生成**：[`installer/build_clinic_installer.py`](installer/build_clinic_installer.py)
- **特性**：
  - **Observe–Act–Verify** 閉環：透過 Accessibility Tree 辨識控制項，預設採用 UIA `ValuePattern`（Tier 1）背景寫入，不搶奪醫師滑鼠焦點。
  - **3-Tier Fallback**：Tier 1 ValuePattern ➔ Tier 2 剪貼簿貼上還原 ➔ Tier 3 懸浮卡片點擊複製。
  - **STALE_REF 世代重繪保護**：控制項重繪時自動刷新快照並重試。
  - **各大 HIS 設定檔支援**：內建展望（Vision）、耀聖（Yaosheng）、佲格（Minger）、志氏（Chihshi）。
  - **BridgeQueue 派工 CAS 鎖**：支援 `HIS_PUSH` 任務狀態機原子更新（`PENDING` ➔ `SENDING` ➔ `SUCCESS`）。
  - **一體化安裝包**：自動生成 Inno Setup 腳本（`clinic_installer.iss`）與啟動器（`start_clinic_client.bat`），一鍵打包小B、`agent-desktop` 與 `WebBrain`。

### 4. 診間即時 SOAP 工作台、護理錄製監控與司法病歷金庫 UI (Phase 27)
- **前端介面**：[`static/index.html`](static/index.html) (`#tabMode4` / `#workflow4View`)
- **後端端點**：
  - `GET /api/soap/live-session`：護理專員即時錄音呼吸燈、錄音動態計時、病患膠囊標籤、12 段即時聲波等化器、ASR 即時逐字稿跑馬字幕。
  - `POST /api/soap/search-patient`：以身分證字號或出生年月日查詢歷史門診紀錄時間軸。
  - `GET /api/soap/cases/<case_id>/bundle`：門診完整 S/O/A/P 結構與金庫多媒體檔案清單。
  - `GET /api/soap/cases/<case_id>/export-forensic-zip`：一鍵導出符合法庭與健保審查規範之 ZIP 佐證包（含 `SOAP_RECORD.txt`、`SOAP_RECORD.json`、原始音訊與影像、`SHA256_CHECKSUM.txt` 數位防竄改雜湊、`AUDIT_TRAIL.json` 司法審計時間戳）。
- **安全保障**：全介面純 DOM 構建，100% 杜絕 unsafe innerHTML 注入；全離線運作，無任何外部 CDN 網路依賴。

### 5. 當月申報 TOTFA 與每日語音 SOAP 自動比對入庫暨 11 碼標準檔名 EMR 批次打包引擎 (Phase 28)
- **架構與比對**：[`src/elc_audit_engine/reconciliation/soap_reconciler.py`](src/elc_audit_engine/reconciliation/soap_reconciler.py)
  - 解決 `TOTFA.zip` 僅有費用、醫令與診斷碼而無病歷本文的問題。
  - 當月申報檔匯入時，以多源三層策略（Layer 1: CaseStore HIS ➔ Layer 2: 診所本機 PATIENT_DB ➔ Layer 3: EvidenceVault）進行關聯比對，自動提取對應門診語音 SOAP、`soap_text`、`vault_key` 與佐證檔案寫入案件 payload，供第 2 階（抽樣預審）與第 3 階（事後申復）備存。
- **11 碼標準檔名與 500MB ZIP 分包**：[`src/elc_audit_engine/packagers/emr_batch_packager.py`](src/elc_audit_engine/packagers/emr_batch_packager.py)
  - **11 碼標準檔名**：`[第1階 2碼 11:西醫基層門診] + [第2階 1碼 A/B/C/D] + [案件分類 2碼 09] + [流水號 6碼] + [-N 擴充]`，嚴格半形英數字校驗（禁止全形或中文字元）。
  - **四大資料屬性分類 (A/B/C/D)**：
    - `A`：病歷本文類（門診 SOAP 紀錄單、病歷首頁、處方箋）。
    - `B`：影像類（X 光、超音波、臨床處置照片、DICOM）。
    - `C`：非影像檢驗報告（CBC、HbA1c、生化報告）。
    - `D`：同意書與事前審查核准函。
  - **A 類 HTML 病歷文件**（2026-11-17 起）：由 `StructuredSoapHtmlBuilder` 產製單一自包含 HTML，含 `病歷首頁`、`門診處方箋`、`門診 SOAP 紀錄單` 三段錨點目錄與醫師簽章欄；所有欄位轉義，缺漏顯示「（未提供）」。原 PDF 產製因輸出空白頁已停用。
  - **500MB 動態分包**：封包命名格式 `{機構代碼 10碼}_{民國日期 7碼}_{序號 3碼}.zip`，達 450MB 動態臨界點自動裁切分包，封包內建 `MANIFEST.txt` 與 `SHA256_CHECKSUM.txt` 數位防竄改檢驗單。
  - **源頭端品質驗證 (Validation-at-Source)**：副檔名白名單與阻斷檢查、DICOMDIR 引導目錄完整性檢核。
- **工作台介面升級**：
  - 第 2 階與第 3 階頂部操作列整合為緊湊 1 列（操作按鈕 ＋ 報告交付 ＋ 佐證庫上傳）。
  - 結構化 4 格獨立色彩 SOAP 編輯表單（S 藍、O 綠、A 紫、P 橘黃）。
  - 缺口分析警示「紅字建立清單」與智慧補強建議「綠色字體確認件」。
  - 「同意修訂並寫回 HIS 與資料庫」雙向同步與變更即時偵測警示。
- **RESTful API 端點**：
  - `POST /api/emr/batch-package`：執行批次標準 11 碼重命名與 500MB ZIP 封包產製。
  - `GET /api/emr/packages`：列出已產製之 EMR 封包清單。
  - `GET /api/emr/download/<filename>`：安全下載 500MB ZIP 封包。

### 6. 本機 Gemma 4 E4B（128K）推論・離線雙後端語音辨識・臨床 SOAP 與報告精簡化 (Phase 33–34)
- **常駐本機 LLM 服務（`elc-llama-server.service`）**：
  - 預設模型：`unsloth/gemma-4-E4B-it-GGUF:Q4_K_M`（附掛 `mmproj-BF16.gguf`，`--ctx-size 131072 --kv-unified --offline -ngl 99`，綁定 `127.0.0.1:8080`；高配機房可選用 `config/llama_config.q8.example.json`）。
  - 30 組健保金標準（`scripts/replay_gold_standard.py`）實測達 **100%（30/30）**、零引文幻覺；完整評測見 [`compare.md`](compare.md)。
- **本機離線雙後端 ASR（[`src/elc_audit_engine/asr/`](src/elc_audit_engine/asr/)）**：
  - **`sherpa` 後端（Phase 34，預設快速 ASR 後端）**：`sherpa-onnx` SenseVoice int8 ＋ OpenCC `s2twp` 台灣繁化 ＋ [`config/asr_hotwords.json`](config/asr_hotwords.json) 專科熱詞校正 ＋ 可選離線雙人說者分離（`diarize=True, num_clusters=2`）。純 CPU 實測達 **42.8× 即時速度**（RTF `0.023`）、**0% 重複迴圈**；選配依賴 `uv sync --extra asr-sherpa`。
  - **`whisper` 後端（Phase 33，重雜訊／台語口音備援）**：`faster-whisper large-v3-turbo`（`int8`、Silero VAD、`condition_on_previous_text=False`、PyAV 19 相容解碼）；選配依賴 `uv sync --extra asr`。
  - 預設走 `sherpa`，可透過 `ELC_ASR_BACKEND=sherpa|whisper` 或 `transcribe_audio(..., backend=...)` 切換，全程 100% 離線不外送音檔，日誌零 PHI。
- **錄音 API 上限與品質分流**：
  - `POST /api/soap/recordings` 支援 `.wav` 與 `.opus`（上限 25 MB，Flask `MAX_CONTENT_LENGTH` 已對齊為 **26 MB**；非錄音端點維持各自 10 MB 防線）。
  - `validate_soap_quality(soap, profile="template"|"clinical")` 區分短版預生成範例（200–500 字）與真實門診錄音 SOAP（200–2000 字），並整合 [`icd10_validator.py`](src/elc_audit_engine/comparator/icd10_validator.py) 偵測高風險 ICD-10 語意誤碼（僅出警告，絕不擅自改碼）。
- **給付規定完整展開（Phase 38 使用者確認版）**：
  - 當月預審與二／三階報告的 `📜 給付規定（payment_text）` 直接完整展開原文，不做摘要截斷；已移除先前的精簡摘要模組（`rule_summary.py`）。
  - 下方折疊的 `📜 檢視完整給付規定條文` 僅含官方條文全文（`article_full_text`，附 `article_location` 出處），不重複 `payment_text`。

### 7. 規則庫安全更新、唯讀品質稽核、零 LLM 官方條文全文建置與維運速查卡 (Phase 35–38)
- **規則庫安全原子同步與四重防誤觸（[`sync_latest_rules.py`](src/elc_audit_engine/rule_repository/scripts/sync_latest_rules.py)、[`rules.py`](src/elc_audit_engine/api/routes/rules.py)）**：
  - 新增 `GET /api/rules/status` 檢視規則庫列數（含 `rule_mapping_rows`）與最新來源 CSV；`POST /api/rules/upload` 單路由放寬上限至 **65 MB**（其餘路由維持 26 MB）。
  - 同步流程導入 `O_EXCL` 獨占鎖檔（`data/db/rules.sqlite3.lock`）、SQLite 側車檢查（`-wal`/`-shm`/`-journal` 存在時回 `409` 且絕不自動刪除）、雙表 staging 原子替換，並自動連動重建官方完整條文 `rule_mapping`（缺官方目錄時保留既有列不洗空）及依檔名時間戳輪替備份（上限 5 份）。
  - **四重 `replace=True` 防誤觸**：函式層（最前端檢查）、API 層（缺／錯確認碼優先回 `422`）、CLI（`--replace --confirm REPLACE_RULES`）與前端（`static/index.html` 整表更新按鈕加上 `advanced-only` 於醫師模式隱藏，並以 `prompt()` 強制輸入 `REPLACE_RULES`）；日常建議優先採用「🔄 增量同步（保留舊碼）」。
  - **零 LLM 官方完整條文建置器（[`build_fulltext_mapping.py`](src/elc_audit_engine/rule_repository/mapping/build_fulltext_mapping.py)）**：以純 Python 標準庫確定性擷取 `officialdocument/審查注意事項/完整給付規定1140221.odt`（解開藥品 CSV 303 字截斷，命中 5,453 筆）、21 份官方 `.docx`（各科審查注意事項跨段落條文與手術節支付標準表）與 `261119` 官方 `備註`（合計 2,849 筆診療項目），總計 **8,302 筆**官方原文完整呈現於一／二／三階報告的「📜 檢視完整給付規定條文」展開區（附出處位置、100% 不截斷）。
  - 本倉庫直接收錄零 PHI 之公開健保規則庫 **`data/db/rules.sqlite3`**（5,752 筆給付項目＋11,472 筆藥品＋8,302 筆官方條文全文，字面占位 0；含個資之 `data/db/cases.sqlite3` 維持 `.gitignore` 嚴格排除）。
- **唯讀規則 CSV 品質稽核與 8 類舊碼差異分析（[`audit_csv.py`](src/elc_audit_engine/rule_repository/audit_csv.py)）**：
  - 提供唯讀品質掃描（占位字串、AI 預填標記、中文緊鄰非標準尾碼／缺碼引用）與 `--stale-vs-db` 8 類舊碼分類分析；嚴守絕不自動刪除原則（`stale_count > 0` 一律建議 `upsert`）。
  - `_csv_table.py` 統一將 `null`／`none`／`未找到給付規定` 寫入 SQLite `NULL`；`OrderJudgment.llm_failed` 精準區分官方 `NULL` 條文（業務待人工 `reviewed`）與 LLM 故障（`failed`）。
- **臨床 SOAP 品質與一鍵部署收尾**：
  - `soap_advice.py` 支援單次定向重試去除佔位詞、空繁中摘要自動補齊，以及臨床 `pending` 兩步防繞過檢核（放行明確檢驗追蹤語境，攔截診斷／計畫待定佔位）；`deploy/install.sh` 整合 `elc-llama-server.service` 與 `--check-asr-models`／`--check-llama-cache` 檢查。
  - 新增一頁式非工程師《診所主機維運速查卡》：[`docs/CLINIC_SERVER_OPS_QUICKCARD.md`](docs/CLINIC_SERVER_OPS_QUICKCARD.md)。

### 8. Windows Client 分段錄音、VAD 自動錄音與即時管線串接 (Phase 39)
- **診間語音活動自動觸發（Voice Activity Detection, VAD）**：
  - 為解決醫師繁忙忘記按下錄音鍵的痛點，Windows Client（SoapVoice）透過輕量神經網路 Silero VAD 常駐監聽診間對話。
  - **3.0 秒環形記憶體緩衝區（Pre-roll Ring Buffer）**：偵測到語音起點時，將前綴 3 秒音訊作為 `seq: 0` 分段送出，確保問診第一句「陳先生你好」完整無吃字。
  - **30 秒靜音自動完結（Auto-finalize）**：看診結束後若連續 30 秒無人聲對話，自動呼叫 `POST /api/cycles/<cycle_id>/finalize` 完結並觸發後端 pipeline。
- **音訊分段上傳、去重與安全性邊界**（[`src/elc_audit_engine/cycles/chunks.py`](src/elc_audit_engine/cycles/chunks.py)）：
  - 格式限定：16 kHz, 16-bit mono PCM WAV，單段上限 4 MiB（約 2 分鐘音訊）。
  - **等冪性重送**：以 `(cycle_id, seq)` 為鍵，弱網重送相同 SHA-256 視為成功回傳 `{"duplicate": true}`；雜湊不符拋 `ChunkConflictError (409)`。
  - **嚴格 WAV 標頭與格式檢驗**：校驗 RIFF 宣告長度與實際傳入位元組完全一致，並強制 16-bit 偶數位元組對齊，拒絕截斷或損毀檔案（`422 invalid_wav_format`）。
  - **循環容量上限保護**：單一循環最多 `MAX_CHUNKS_PER_CYCLE = 120` 段（約 2 小時）且總 PCM 限制 `MAX_CYCLE_PCM_BYTES = 250 MiB`，防範儲存空間耗盡攻擊（`413 cycle_limit_exceeded`）。
  - **無損 PCM 串接**：`finalize` 到齊後依序提取純 PCM frames 組裝乾淨單一 `full.wav`，絕無各段 RIFF 標頭串接導致的交界破音。
- **循環與心跳 API 擴充**：
  - `POST /api/cycles`：支援 `trigger_mode`（`manual` | `vad_auto`）與 `preroll_sec`，並由 `recording_cycles` 持久化儲存。
  - `POST /api/clients/heartbeat`：支援 `vad_listening: bool` 狀態回報，且執行嚴格型別校驗（非 bool 輸入拋 `422`）。
- **文件與測試交付**：
  - Windows 端落地與實體驗測指引：[`docs/plans/windows_client_vad_test_plan.md`](docs/plans/windows_client_vad_test_plan.md)（含 V-01~V-09 實體檢核表）。
  - 完整端到端整合測試套件：[`tests/test_windows_client_chunk_e2e.py`](tests/test_windows_client_chunk_e2e.py)（8 項測試通過，1 項 ASR 離線模型保護跳過，經 Herdr 獨立 Tester 簽核）。

---

## 👥 Herdr 多 Agent 協同分工體系 (Herdr Agent Team)

在 Herdr 終端多 Agent 環境 (`HERDR_ENV=1`) 下，由三個終端窗格（Pane）協同分工（2026-11-16 起）：

**標準流程**：Claude 規劃 → agy 執行 → Hermes 測試 → Claude 最終核對 → 使用者確認後提交。

| 終端窗格 (Pane) | 角色指派 | 執行模型 / 核心職責 |
| :--- | :--- | :--- |
| **`w7:pC`** (原 `w7:p6`) | **Antigravity (agy)** | **Executor：依計畫檔實作程式與文件**<br>• 只按計畫檔修改，不自行擴大範圍<br>• 不得自行提交；完成後回報改動清單與待決疑問 |
| **`w7:pE`** (原 `w7:p3`) | **Hermes** | **Tester：測試與驗收，不修改程式**<br>• 全套件測試、`ruff check .`、瀏覽器 console 檢查<br>• 回報原始輸出與數字，不以「應該通過」代替實測 |
| **`w7:pD`** (原 `w7:p1`) | **Claude Code** | **Coordinator／Final check：規劃、派工、最終核對**<br>• 撰寫計畫檔、派工、收取測試結果、獨立重跑測試與 ruff<br>• 提交與推送須經使用者確認 |

> 兩條路徑共用 Phase 5 `compare_case`，故判定語意一致；分開的原因是**產出與副作用不同**（預審誤用整案管線會意外寫出申復草稿），對應目標架構圖 Cloud HIS 的 Review Service ／ Appeal Service 分離。

### ⚠️ 三種「非結論」狀態（呼叫端必須分辨）

系統故障不得偽裝成業務結論。`support_level` 為 `null` 時有兩種完全不同的成因：

| 狀態 | 判斷方式 | 意義 |
|---|---|---|
| ❌ **裸奔** | `support_level == "裸奔"` | 病歷**確實**未記載 — 這是業務結論 |
| ⏳ **待判定** | `support_level == null` 且 `undetermined == true` | 判定服務異常（LLM 逾時/解析失敗），**系統未能判定** |
| ❓ **查無規則** | `support_level == null` 且 `rule_found == false` | 規則庫無此醫令條文 |

**絕不可把「待判定」顯示為「裸奔」** — 那會讓醫師針對一個從未成功執行的判定，去補強根本不存在的缺漏。規則庫本身故障（DB 損毀/表遺失）則回 **HTTP 503**，同樣不偽裝成「查無規則」。

---

## 🔌 HIS 系統整合與 API 對接指南 (HIS Integration & API Protocol)

`elc-audit-engine` 提供標準 RESTful API 與 Python Package 雙重整合介面，方便嵌入 `doctor-toolbox`、Emr / HIS 門診系統或院內 VPN 上傳服務。

### 1. 系統對接架構與串接流程 (Architecture & Integration Steps)

```text
+----------------------------+      HTTP REST API (LAN trust)       +-----------------------------------+
|  院方 HIS / EMR 門診系統   |  =================================>  |    Elcinsurrence Core Engine      |
|  (doctor-toolbox / 門診端)  |                                      |       (Flask / CaseStore)         |
+----------------------------+                                      +-----------------------------------+
                                                                                      |
                                       +----------------------------------------------+
                                       |                                              |
                        [事前預審 Review Service]                       [事後申復 Appeal Service]
                        run_presubmission_check()                        run_case_pipeline()
                        事前預審 · 唯讀 · 不寫檔                     事後申復 · 產出報告與草稿
                                       |                                              |
                                       +----------------------+-----------------------+
                                                              |
                                                   [Phase 5 三方比對器]
                                                              |
                              +-------------------------------+-------------------------------+
                              |                               |                               |
                  [Phase 2 規則庫 SQLite]        [Phase 3 解析器 XML/核減/SOAP]     [Phase 4 病歷彙整器]
                  [docx 樹狀索引 + ChromaDB]                                        [半年病史 Provider]
```

#### 💡 完整 HIS 串接四步驟 (End-to-End Workflow)

1. **環境設定與健康檢查 (Step 1: Auth & Healthcheck)**
   - HIS 發送探測請求：`GET /api/health`（不含病歷資料）。
   - 本系統不使用 API key。HIS 須位於院內信任網段內（見「認證」小節），無需設定認證標頭。

2. **案件匯入與初始化 (Step 2: Ingest & Case Initialization)**
   - **抽審預審**：HIS 呼叫 `POST /api/sampling/import` 上傳 CSV/PDF。系統解析後寫入 `CaseStore` 持久化，狀態標記為 `imported`。
   - **核減申復**：HIS 呼叫 `POST /api/appeal/import` 上傳 D-14d 明細。系統建案並持久化 (狀態 `imported`)。
   - **案件查詢**：HIS 發送 `GET /api/sampling/cases` 或 `GET /api/appeal/cases` 取得目前儲存庫中的全數案件與最新狀態。

3. **預審比對與狀態推進 (Step 3: Audit & Workflow State Machine)**
   - **事前預審**：HIS 帶入 `case_id` 呼叫 `POST /api/sampling/audit`。系統進行 SOAP 分段與 LLM 三方比對，完成後案件狀態自動由 `imported` 推進至 `parsed` ➔ `reviewing` ➔ `reviewed`。
   - **事後申復**：HIS 帶入 `case_id` 呼叫 `POST /api/appeal/generate`。系統依 D10 四段式結構產出草稿，案件狀態自動推進至 `appealed`。

4. **申復 XML 匯出 (Step 4: XML Export / Package Builder)**
   - 呼叫 CLI 工具 `scripts/build_appeal_xml.py` 讀取 `appeal_{流水號}.json`，生成 Big5 編碼、特殊字元全形轉義之健保署標準申復 XML 檔 (tdata + ddata + pdata)。

### 1.1 ⚠️ 案件識別欄位對接注意事項（`case_id` vs `case_seq`）

HIS 串接時常見的誤用來源：`CaseStore` 中 `case_id` 與 `case_seq` 是**兩個獨立、各自可為 `null` 的欄位**，並非同一值的別名。

| 欄位 | 意義 | 誰產生 | 是否必填 |
|---|---|---|---|
| `case_id` | CaseStore 全域唯一主鍵（`SAMP-`／`APP-` + 記錄內容雜湊；同一份檔案重複匯入得到相同 id，回報於 `case_store_conflicts`） | 匯入時系統賦值 | 是（永不為空） |
| `case_seq` | 健保申報流水號（院所端業務編號） | 匯入時由來源資料的 `case_seq` 欄位帶入（可能未提供） | 否（可為 `null`） |

**HIS 對接時務必注意**：`case_seq` 只在單一費用年月／案件分類內唯一，跨月必定重複，**不可當成案件主鍵**。所有 Phase 12 影像佐證端點（`/api/appeal/attachments/*`）、佐證包列印與申復草稿的 p7 附件旗標，一律以 **`case_id`** 作為附件儲存／查詢鍵。

- 附件端點仍接受 `case_seq` 作為相容用識別：伺服器會以它反查申復案件，**僅在唯一對應一筆時採用**；對應多筆回 `409`（請改用 `case_id`），查無回 `404`。
- 附件回應同時帶 `case_id` 與 `case_seq`。

> **歷史記錄**：v1.1 以 `case_seq` 為附件鍵（commit `3f7f097` 曾修正生成端與上傳端不一致）。2026-09 全專案 code review（`doc/REVIEW-A-api-store-generators.md` CR-03）發現流水號跨月重複會把他人影像併入本案佐證包、誤設 p7=Y，改為 `case_id` 為鍵。升級前以流水號存放的舊附件**不會自動併入**佐證包，列印時會在 `warnings` 提示，請確認病患後以 `case_id` 重新上傳。

### 2. 核心 REST API 規格

> **案例清單端點**（`GET /api/sampling/cases`、`GET /api/appeal/cases`）：未匯入資料時回傳**示範資料**（每個案例帶 `"demo": true`），供 UI 展示工作流；**匯入後優先回傳導入資料**（`source: "csv" / "paddle" / "ocr"`）。醫令名稱一律以規則庫為準（例：`64140C`＝甲床與手指重建術，曾誤標為「手腕韌帶縫合術」，2026-08-04 修正）。匯入資料的每筆項目另附 `state`（案件狀態）與 `failure_reason`；支援 `?limit=`（1～1000，預設 1000）與 `?offset=` 分頁，回應標頭 `X-Total-Count` 為總筆數，超過 limit 時不再靜默截斷。

#### 🔐 認證（2026-11-13 起：院內網路信任，已移除 API key）

本系統不再使用 `X-API-Key`。來源判定改為位址與請求標頭（實作：`src/elc_audit_engine/lan_trust.py`、`api/security.py`；依使用者裁示 D-32-06、D-32-27）：

| 檢查 | 規則 | 不符合時 |
|---|---|---|
| 來源位址 | 須為 loopback，或位於信任網段（`ELC_TRUSTED_SUBNETS`；未設定則自動偵測伺服器所在網段，排除 VPN／虛擬介面） | `403`：僅限院內網路使用 |
| Host 標頭 | 須為合法主機形式（防 DNS rebinding） | `400`：不允許的 Host |
| 跨站請求 | `Sec-Fetch-Site: cross-site` 的請求一律拒絕（含 GET，防跨站讀取） | `403`：拒絕跨站請求 |
| 管理設定寫入 | 院內信任網段內可直接修改（D-32-27；取代先前「僅限本機」限制） | — |

- **剩餘風險（D-32-24，已接受）**：同一網段內的任何裝置皆可讀取病歷資料，系統不做逐裝置身分驗證。詳見 `docs/CLINIC_DEPLOYMENT_GUIDE.md` 第一節。
- **稽核**：存取審計日誌的 `caller_id` 為來源位址（不含病歷內容）。
- **部署前提**：本系統為院內專用，須置於防火牆之後，只允許院內網段連入服務埠。

#### 📝 存取審計日誌（Phase 9-01：零 PHI；2026-08-08 修復豁免清單誤用）

每次呼叫非 `_AUDIT_EXEMPT_ENDPOINTS`（`/`／`/api/health`／靜態檔）的端點，都會在審計日誌留下一列 JSON（JSON Lines 格式）：

- **路徑**：`AUDIT_LOG_PATH`（環境變數可覆寫；預設 `data/audit/access.log`，已 `.gitignore`）。
- **欄位（六個，固定）**：`ts`（UTC ISO 時間戳）、`caller_id`（呼叫方識別，或 `anonymous` 表示未帶／帶錯 key）、`method`、`path`、`status`。
- **明文聲明：不記錄 PHI。** 禁止欄位（`soap`／`soap_text`／`record_no`／`patient_name`／`id_number`／`birth_date`）與超長字串（>100 字）一律拒絕寫入（`AuditFieldError`），不會被靜默剔除——審計的目的是「誰在何時存取了什麼端點」，而非複製病歷內容。
- 審計寫檔失敗不會讓業務回應變成 500，但會記錄於 application log（不靜默無痕）。
- **⚠️ 2026-08-08 回歸修復**：`fcde2c8` 把六個業務端點加進認證豁免清單後，`_record_access_audit` 一度沿用同一份清單判斷是否寫審計，導致這六個接觸病歷資料的端點**完全停止寫審計日誌**——違反「認證可選、審計必留」的設計。已拆成 `_AUDIT_EXEMPT_ENDPOINTS`（僅 3 項）與 `_AUTH_EXEMPT_ENDPOINTS`（9 項）兩份獨立清單修復；`test_auth.py` 全數更新驗證。

#### 🔹 [POST] `/api/sampling/audit` — 抽樣事前預審支持度評估

呼叫真實引擎（`run_presubmission_check`）：查規則庫 ➔ Phase 3 `parse_soap_text` 分段 ➔ LLM 逐檢核項判定 ➔ 三級分類 ➔ 缺口候選補強。**需 llama.cpp server 可用**。

- **請求內容 (JSON)**：
  ```json
  {
    "order_code": "14050B",
    "order_name": "糖化血色素檢驗 HbA1c",
    "soap_text": "S: DM O: BP 120/80 A: DM P: HbA1c",
    "record_no": "M1001",
    "case_id": "SAMP-0001"
  }
  ```
  * `case_id`（選填）：提供時於判定完成後推進案件狀態（單一交易）：正常判定 → `reviewed`；LLM 判定服務異常（`undetermined=true`）→ `failed`（附原因，可重試）。非抽樣案件回 `409`。回應 `state_transition` 揭露結果：`ok`／`failed`／`skipped`（已在 reviewed 或之後）／`not_found`／`conflict`；未帶 `case_id` 時為 `null`。
  * `/api/appeal/generate` 同樣回傳 `state_transition`；草稿 `validation_errors` 非空時不推進 `appealed`（`skipped`）。
  * `visit_date`（選填，ISO／西元 8 碼／民國 7 碼／`115/07/10`）：半年病史窗的迄日；未帶時取 CaseStore 案件 payload 的就醫日。回應 `records_window_anchor` 為 `visit_date` 或 `today`（兩者皆無時退回今天）。就醫日也用於檢查規則是否在當日生效，不在生效期間的規則改待人工，不送 LLM 判定。

- **回傳內容 (JSON)**:
  ```json
  {
    "status": "success",
    "order_code": "14050B",
    "support_level": "薄弱",
    "rule_found": true,
    "undetermined": false,
    "verdict": "部分支持",
    "quote": "糖尿病追蹤",
    "rule_location": "西醫基層-內科 > 一",
    "reinforcement_advice": "- 建議於 P 欄補充前次檢驗日期與數值",
    "candidates": [
      {"text": "建議於 P 欄補充前次檢驗日期與數值", "rule_location": "西醫基層-內科 > 一", "prompt_only": false}
    ],
    "records_degraded": true
  }
  ```
  > 上例為說明用的欄位形狀。實際 `support_level` 取決於規則庫是否收錄該醫令：
  > 目前 `rule_mapping` 13,942 碼中有 6,934 碼為「誠實無匹配」（語料本無對應條文，
  > 多為藥品碼），這些碼會回 `rule_found: false`。
- **狀態碼**：`400` 入參不合法／缺必填；`503` 規則庫故障（`RuleRepositoryError`）；`500` 其他（訊息已脫敏，不回傳 traceback）。
- ⚠️ `support_level` 可為 `null` — 請依上方「三種非結論狀態」表以 `undetermined` / `rule_found` 分辨，不可逕自視為「裸奔」。

#### 🔹 [POST] `/api/appeal/generate` — 核減多源證據申復草稿生成
呼叫真實產生器（`build_appeal_draft`）組裝 D10 四段。**「③ 規則依據」的條文全文一律取自規則庫 `get_rule`**；查無時回 `rule_found: false` 並誠實標示，不得自行拼造法規依據。

- **請求參數 (JSON)**：`case_seq`、`order_code` 為必填；`evidence` 為**字串陣列**（醫師採用的補強敘述，來自 Phase 6 審核軌跡）。
  ```json
  {
    "case_seq": "201",
    "order_code": "64140C",
    "deduct_amount": 3200,
    "claimed_points": 3200,
    "deduction_reason": "病歷未載明甲床損傷範圍與術前影像評估",
    "is_appealing": true,
    "has_attachment": false,
    "evidence": [
      "影像 Finger X-ray：Distal phalanx fracture with nail bed defect",
      "檢驗 CBC/WBC：11,500 /uL"
    ]
  }
  ```
- **回傳內容 (JSON)**：`appeal_sections` 為**依 D10 四段順序排列的陣列**。
  ```json
  {
    "status": "success",
    "case_seq": "201",
    "order_code": "64140C",
    "appeal_sections": [
      {"key": "case_summary", "title": "①案情摘要", "text": "..."},
      {"key": "necessity", "title": "②醫療必要性（半年病史）", "text": "..."},
      {"key": "rule_basis", "title": "③規則依據（條文原文）", "text": "..."},
      {"key": "evidence", "title": "④病歷佐證（醫師採用補強敘述）", "text": "..."}
    ],
    "reason1": "（p8 欄位文字）",
    "reason2": "（p9 欄位文字）",
    "p6_points": 3200,
    "total_char_count": 420,
    "rule_found": true,
    "xml_p8_p9_valid": true,
    "over_limit": false,
    "validation_errors": []
  }
  ```
- **字數規則**：依官方問答集 **Q15 — p8/p9 各 ≤1000 中文字**（非「合計 2000」）；超限時 `xml_p8_p9_valid: false`。裁剪優先序 ④→②，①③ 骨架不動。
- **硬檢查**：`is_appealing: false` 時 P6 強制填 0（Q13）；`claimed_points` 不得超過 `deduct_amount`（D-15）— 違反時列於 `validation_errors`。
- **狀態碼**：`400` 入參不合法；`503` 規則庫故障；`500` 其他（已脫敏）。

#### 🔹 [POST] `/api/sampling/import` 與 `/api/appeal/import` — 批次匯入清單（digital + paper）

接受 **CSV（digital）、PDF、JPEG/PNG 掃描影像（paper→OCR）**，multipart 欄位名 `file`，單檔上限 10MB。**一律本機處理**（PDF 文字層 pdftotext；掃描文件 PP-StructureV3 表格結構化，降級 tesseract；D2：個資不出本機），不呼叫雲端 API。

- **抽樣清單（`/api/sampling/import`）**：
  - CSV：自訂欄位契約（2026-08-04 裁示）— `流水號(case_seq)／病歷號(record_no)／病患姓名(patient_name)／醫令代碼(order_code, 必填)／醫令名稱(order_name)／就醫日期(visit_date)／科別(clinic)／SOAP(soap_text)`，表頭別名中英皆可、自動偵測，編碼 utf-8-sig→big5→cp950。
  - PDF／影像（紙本）：**優先 PP-StructureV3 表格結構化**（`source: "paddle"`，欄位級：表頭對齊 8 欄契約、日期正規化）；引擎不可用／無表格時**自動降級** tesseract 行解析（`source: "ocr"`，以醫令代碼為錨點結構化「代碼＋名稱」）。每筆保留原始辨識行供人工核對。
  - ⚠️ 表格結構化需 `uv sync --extra ocr`（paddlepaddle==3.2.2 釘版，見 deepflash4improve §8.2）；未裝則全程降級，功能不中斷。
- **核減清單（`/api/appeal/import`）**：CSV 走 D-14d 18 欄 parser（編碼/分隔符/表頭自動偵測）；**PDF／影像誠實降級- CaseStore 整合 (Phase 9-03)**：匯入解析成功後逐筆持久化至 `CaseStore` (state=`imported`)。若出現同名 `case_id` 重複匯入，不會靜默覆寫，而是明確於 `case_store_conflicts` 回報。
- **回傳**：`{status, media_type, source, imported, rejected, rejected_rows:[{row,reason,raw}], case_store_persisted, case_store_conflicts}`；案件只存於 CaseStore（2026-09 起不再另存 `data/uploads/*.json` PHI 快照），伺服器啟動時仍會一次性、冪等地將舊快照遷移至 CaseStore。請求大小上限 11MB（超過回 `413`）。
- **狀態碼**：`400` 缺檔／不支援類型／超過 10MB／未匯入任何案件（含原因）；`500` 其他（已脫敏）。

#### 🔹 [CLI 工具] `scripts/build_appeal_xml.py` — Package Builder (申復 XML 序列化，Phase 9-04)

將 Phase 7 產出的 `appeal_{流水號}.json`（含 p1-p9 醫令段欄位）序列化為符合健保署申復格式之 XML 檔案。

- **用法**：
  ```bash
  python scripts/build_appeal_xml.py <appeal_json路徑> [輸出XML路徑]
  # 範例:
  python scripts/build_appeal_xml.py data/output/appeal_18.json data/output/appeal_18.xml
  ```
- **範圍聲明**：本次僅支援 **tdata + ddata + pdata**（單筆醫令申復），**不含** `edata`（統扣明細段）。若案件分類為統扣類（`0`），需待後續擴充。
- **tdata 加總欄位聲明**：單一案件情境下 `t6-t37` 加總欄位依官方規則無資料不輸出標籤。
- **編碼與特殊字元處理**：檔案固定以 `Big5` 編碼寫出；若遭遇 Big5 無法編碼之字元會 fail-fast 報錯。p8/p9 申復理由內之半形特殊字元 (`< > & ' "`) 會自動轉換為全形字元 (`＜ ＞ ＆ ＇ ＂`)。

#### 🔹 [Python 代碼直接對接]
HIS 後端若為 Python 架構，可直接呼叫 [`pipeline.py`](src/elc_audit_engine/pipeline.py) 的兩個入口：

```python
# ① 事前預審（唯讀，不寫檔）
from elc_audit_engine.pipeline import run_presubmission_check

result = run_presubmission_check(
    case=submission_case,
    soap_doc=soap_document,
    timeline=patient_timeline,   # None＝病歷缺席降級（C5）
)
for oj in result.comparison.order_judgments:
    print(oj.order_code, oj.support_level)   # None 代表待判定／查無規則
print("系統未能判定的醫令：", result.undetermined_orders)
```

```python
# ② 事後申復（比對→補強報告→逐筆申復草稿，會寫檔）
from elc_audit_engine.pipeline import run_case_pipeline

result = run_case_pipeline(
    case=submission_case,
    soap_doc=soap_document,
    timeline=patient_timeline,
    deduction_records=deductions,
    output_dir="/path/to/output",
)
print("病歷補強報告：", result.report_path)
print("申復 XML / JSON 草稿：", result.appeal_paths)
```

兩者皆可注入 `rule_lookup` / `judge_fn` / `narrative_fn` 替身（D-08），測試零 LLM 依賴。
規則庫故障會拋 `RuleRepositoryError`（D-06/P0-2 **穿透不吞** — infra 故障不得偽裝成「查無規則」），呼叫端須自行處理。

---

## 🛠️ 開發與運作指南

### 1. 啟動 Web UI 三軌控制台

```bash
# 安裝依賴（含 flask；紙本表格結構化加 --extra ocr）
uv sync
uv sync --extra ocr   # 選用：PP-StructureV3 表格結構化（paddlepaddle==3.2.2 釘版）

# 啟動 API 與 三軌控制台 Web Server
uv run python server.py
```
啟動後打開瀏覽器造訪 `http://127.0.0.1:5000` 即可操作預審與申復介面。

**安全預設**：本服務會接觸病歷資料，故預設 **綁定 `127.0.0.1`、`debug=False`**，並以院內網路信任判定來源（見下方「認證」小節）。需對外提供時**務必置於反向代理／VPN 之後**，再以環境變數覆寫：

| 環境變數 | 預設 | 說明 |
|---|---|---|
| `ELC_SERVER_HOST` | `127.0.0.1` | 監聽位址 |
| `ELC_SERVER_PORT` | `5000` | 連接埠 |
| `ELC_SERVER_DEBUG` | 關閉 | 設為 `1`/`true` 開啟；**正式環境切勿開啟**（會回顯堆疊） |
| `ELC_TRUSTED_SUBNETS` | 自動偵測（`deploy/install.sh` 安裝時寫入） | 院內信任網段（逗號分隔 CIDR）；多個不同網段或無法偵測時僅信任本機 |
| `AUDIT_LOG_PATH` | `data/audit/access.log` | 存取審計日誌（JSON Lines，零 PHI）寫入路徑 |

> 預審端點的 LLM 判定需 llama.cpp server（`localhost:8080`）可用；未啟動時判定會降級為「待判定」（`support_level: null` + `undetermined: true`），而非「裸奔」。

### 2. 建置規則庫 (Phase 2 管線)

**須依序執行**（後一步依賴前一步的產物）：

```bash
# 1) 來源 CSV -> SQLite（payment_rules / drug_rules）
uv run python -m elc_audit_engine.rule_repository.scripts.build_sqlite

# 2) 審查注意事項 .doc/.docx -> 樹狀索引（需 LibreOffice headless 轉檔）
uv run python -m elc_audit_engine.rule_repository.scripts.build_docx_trees

# 3) docx 樹 -> ChromaDB 向量索引（輔助層，非阻斷）
uv run python -m elc_audit_engine.rule_repository.scripts.build_chroma_index

# 4) LLM rule_mapping 快取編譯（需啟動 llama.cpp server；支援增量與續跑）
uv run python -m elc_audit_engine.rule_repository.mapping.build_mapping
```

> 規則庫建置產物預設寫入 `data/`：其中公開健保規則庫 **`data/db/rules.sqlite3`**（零 PHI，5,752 筆給付＋11,472 筆藥品）已納入版控方便開箱即用；`data/db/cases.sqlite3`（含病患資料）、`data/db/rules.sqlite3.bak.*`、`data/rag/` 與 `data/output/` 維持 `.gitignore` 嚴格排除。
> 步驟 4 具版本追蹤（`source_version`）與增量建置，中斷後可續跑，不需全部重來。

### 3. 執行單元與端到端測試套件

```bash
uv run pytest -q
```

目前基線：**1,766 passed / 3 skipped / 1 deselected / 0 failed**（Phase 38 驗收，2026-11-23）。測試零 LLM 依賴（判定與生成皆以替身注入）且全域隔離正式 `data/db/cases.sqlite3` 與 `data/audit/access.log`，不需啟動 llama.cpp 即可全數執行；OCR 表格結構化測試以替身覆蓋，不需 GPU。

---

## ✅ Phase 9 追認：已完成範圍

下列工作已於 Phase 9 之前 commit，但未納入 GSD phase 管理；本節依 Phase 9 Success Criteria 第 1 項要求追認記錄：

| 範圍 | Commit | 內容 | 狀態 |
|---|---|---|---|
| Flask API 接真實引擎 | `b80cd08` | `/api/sampling/audit` → `run_presubmission_check`；`/api/appeal/generate` → `build_appeal_draft`；安全預設（綁 127.0.0.1／debug=False／錯誤脫敏／入參校驗） | 已完成，於 Phase 9 追認納管 |
| 批次匯入 | `56d9902` | `ingest/` 模組（media/sampling/ocr_rows）＋ `/api/sampling/import`、`/api/appeal/import`；落盤 `data/uploads/*.json` | 已完成，於 Phase 9 追認納管 |
| 紙本表格結構化 | `8c38a19` | `ingest/table_ocr.py` PP-StructureV3（可選依賴＋自動降級回 tesseract） | 已完成，於 Phase 9 追認納管 |
| 安全清尾 | `f6ac775` | P1-5 前端 XSS＋CSP／P1-2 prompt 定界／P1-3 路徑穿越 | 已完成，於 Phase 9 追認納管 |

---

## 🖨️ 紙本申復清單列印（Phase 11）

未串接 HIS 或選擇紙本作業的院所，可由 `appeal_{流水號}.json` 產出官方三聯式「門診醫療費用點數申復清單」可列印 PDF——與 Markdown／JSON／申復 XML **並行的輸出通道，不互相取代**。版式依官方 30396_1 模板（105.04.01 修訂版），輸出經 `config/facility.json` 院所層設定與（可選）case payload join 患者層欄位。

### 前置條件

- **本機 LibreOffice（soffice，D-01）**：CLI 以 headless 模式呼叫 `soffice --convert-to pdf` 將 filled ODT 轉成 PDF；soffice 缺席時轉檔階段會明確失敗（不靜默）。
- **`config/facility.json` 已填院所欄位**：`code`（代號字碼）／`name`（醫療院所名稱）為必填，另有 `address`（地址）、`physician_name`（負責醫師）。缺檔或缺必填欄位時 CLI fail-fast（`FileNotFoundError`／`ValueError`），不會以空值默默產出看似正常的 PDF；路徑可經環境變數 **`FACILITY_CONFIG_PATH`** 覆寫。

### 指令範例

```bash
# 基本：單一 appeal JSON → data/output/申復清單_{case_seq}_{order_seq}.pdf
python scripts/build_appeal_print.py data/output/appeal_001.json

# 帶 case payload join 患者層欄位（身份證字號/姓名/傷病名稱/審查科別/數量/金額）
python scripts/build_appeal_print.py data/output/appeal_001.json data/cases_payload.json

# 指定輸出 PDF 路徑（第三參數）
python scripts/build_appeal_print.py data/output/appeal_001.json data/cases_payload.json data/output/appeal_001.pdf
```

### 行為說明

- **三聯一次列印**：每聯 1 頁；醫令 >15 行時自動分頁為 3×N 頁（D-06）。
- **患者層欄位**：身份證字號照印遮罩值（`submission.id_number`）；join 不到的欄位（身份證字號／姓名／傷病名稱／審查科別／數量／金額）留空且**不捏造**，CLI 會於成功訊息後以「警告：」逐條列出缺欄欄位名（只印欄位名，不印值全文，T-11-03）。
- **第二聯「中央健康保險署填列」**：核定／複核／初核／審查委員欄留空，供健保署填寫（系統不產出健保署複核結果）。

### PHI 注意（P0-3）

PDF 輸出於 `data/output/*`（已 `.gitignore`，含 PHI 絕不進版控）。

---

## 📎 影像佐證上傳（Phase 12）

診所可透過 API 上傳超音波、X 光、處置照片等影像佐證，系統依案件流水號與醫令做命名關聯儲存，並由「實體檔案是否存在」真實驅動申復 XML 中的 `p7`（`has_attachment`）欄位。

### 安全設計
- **Magic Bytes 驗證**：PNG/JPEG/HEIC/PDF 各有 Header Bytes 硬性比對，副檔名偽造無效。
- **索引存於 SQLite**（`ATTACHMENTS_DIR/attachments.sqlite3`，交易保證一致性；檔案路徑由目錄＋檔名組出，搬移目錄仍有效）。升級前的每案 `meta.json` 於首次存取該案時自動匯入並改名為 `meta.json.migrated`；`meta.json` 損毀時回報錯誤，不當成「沒有附件」。
- **`safe_filename()` 路徑穿越防護**：白名單校驗（ASCII 英數＋`_-`＋CJK），包含 `../` 等穿越組件直接拒絕。
- **PHI-zero 審計**：附件操作記錄於存取日誌，**只記錄操作不留檔名內容**（T-12-03）。

#### 🔹 [POST] `/api/appeal/attachments/upload` — 上傳影像佐證

- **請求**：`multipart/form-data`，欄位 `file`（PNG/JPEG/HEIC/PDF，≤10MB）＋ `case_id`（建議；或可唯一對應的 `case_seq`）、`order_seq`、`order_code`。
- **回傳**：
  ```json
  {
    "status": "success",
    "attachment": {
      "id": "uuid",
      "case_id": "APP-3f2a9c01d4e5b6a7",
      "case_seq": "201",
      "order_seq": "1",
      "order_code": "64140C",
      "filename": "安全後檔名.jpg",
      "file_size": 12345,
      "mime_type": "image/jpeg",
      "created_at": "..."
    }
  }
  ```
- **狀態碼**：`400` 格式不支援、Magic Bytes 不符或識別碼不合法；`404` 查無案件；`409` `case_seq` 對應多筆案件；`500` 其他。

#### 🔹 [GET] `/api/appeal/attachments/<case_id>` — 列出佐證附件

回傳指定案件所有已上傳附件的元資料清單（不回傳二進位內容）。路徑參數亦接受可唯一對應的 `case_seq`（規則同上傳）。

#### 🔹 [DELETE] `/api/appeal/attachments/<case_id>/<attachment_id>` — 刪除附件

刪除指定附件檔案，並從 `has_attachment` 計算中排除。

---

## 🗒️ 核減明細原格式列印（Phase 13）

匯入並解析健保核減資料後，可輸出與官方「門診醫療給付抽查核減明細表」紙本一致格式的 PDF，供診所留底或紙本對帳（RCPI2012R01 式樣）。

### 技術設計
- **ODT ElementTree 動態列複製**：以 `xml.etree.ElementTree` 操作 ODT ZIP 結構，動態複製 `<table:table-row>` 並注入各筆核減記錄，避免 XML/String Injection（T-13-01）。
- **soffice headless 轉 PDF**：在 `TemporaryDirectory` 沙盒中執行轉換，用後即刪（T-13-04）。

#### 🔹 [POST] `/api/deduction/print` — 核減明細 PDF 列印

- **請求 (JSON)**：
  ```json
  {
    "records": [
      {
        "case_seq": "201",
        "order_code": "64140C",
        "order_name": "甲床與手指重建術",
        "deduct_amount": 300,
        "deduction_code": "D01",
        "deduction_reason": "病歷未記載甲床損傷範圍",
        "visit_date": "2026-06-20",
        "fee_year_month": "11506"
      }
    ]
  }
  ```
- **回傳**：
  ```json
  {
    "status": "success",
    "pdf_url": "/api/output/核減明細_xxxxxxxx.pdf",
    "warnings": ["Row 1: 缺病患姓名"]
  }
  ```
- **CLI 替代方案**：`python scripts/build_deduction_print.py data/deduction.csv`
- **狀態碼**：`400` 缺必填欄位；`500` soffice 轉檔失敗（含錯誤說明）。

---

## 📦 審核軌跡＋申復佐證包列印（Phase 14）

將審核軌跡 JSON、病歷補強 Markdown 報告、申復理由草稿，以及上傳之影像佐證照片，合成為結構完整的「可列印佐證包 PDF」，供診所列印後隨同紙本申復清單合訂寄出。

### 技術設計
- **管線**：`python-docx`（A4 版面架構） → `soffice headless`（DOCX→PDF） → `pypdf`（合訂多段 PDF）。
- **影像處理**：`Pillow` + `pillow_heif`（HEIC 支援）＋ EXIF 自動旋轉＋A4 自動縮放；損毀圖片自動跳過並標紅色警示框（不中止整包生成）。
- **結構**：摘要封面→審核軌跡→病歷摘要→申復理由全文→影像佐證附錄（附錄每張圖自占一頁）。

#### 🔹 [POST] `/api/appeal/evidence-packet/print` — 佐證包 PDF 生成

- **請求 (JSON)**：
  ```json
  {
    "case_id": "APP-0001"
  }
  ```
  申復理由段取自該案最近一次**通過驗證**的 `/api/appeal/generate` 草稿（保存於 CaseStore `case_artifacts`）；審核軌跡取自 CaseStore 狀態轉換歷史。病史段目前不在此端點查詢，會標示「病史未查詢」。
- **回傳**：
  ```json
  {
    "status": "success",
    "pdf_url": "/api/output/申復佐證包_APP-3f2a9c01d4e5b6a7.pdf",
    "warnings": []
  }
  ```
- **CLI 替代方案**：`python scripts/build_evidence_packet.py --case-id APP-0001`
- **狀態碼**：`400` 缺案件資料；`404` 查無案件；`409` 尚未生成（或未通過驗證的）申復草稿；`500` 合成失敗（含錯誤說明）。
- **附件查詢鍵**：以 `case_id` 查詢 Phase 12 附件，輸出檔名亦以 `case_id` 命名——見上方「案件識別欄位對接注意事項」。

#### 🔹 [GET] `/api/output/<檔名>.pdf` — 下載列印產出

下載 `/api/deduction/print`、`/api/appeal/evidence-packet/print` 回傳的 `pdf_url`。內容含 PHI，僅限院內信任網段存取，並寫入存取審計日誌；僅開放 `.pdf`。

---

## 🌐 完整 REST API 端點一覽（v1.3）

| Method | 端點 | 功能 | 認證 |
|--------|------|------|------|
| `GET` | `/api/health` | 健康檢查 | 免認證 |
| `GET` | `/` | 控制台首頁（Web UI） | 免認證 |
| `POST` | `/api/monthly/upload` | 上傳 TOTFA.zip 當月申報總檔並自動預審 | 選填 |
| `GET` | `/api/monthly/batch/<batch_id>/report` | 當月申報預審批次報告（HTML/JSON） | 選填 |
| `POST` | `/api/monthly/batch/<batch_id>/clear` | 清空指定申報批次案件與暫存 | 選填 |
| `GET` | `/api/sampling/batch-report` | 抽樣預審批次報告（比照當月申報預審格式） | **必填** |
| `POST` | `/api/sampling/batch-audit` | 全自動批次審查（全部抽樣案件閉環評估） | 選填 |
| `GET` | `/api/sampling/export-batch-xml` | 全批次導出抽審 XML（Big5） | **必填** |
| `POST` | `/api/appeal/sample-from-stage2` | 第 2 階隨機抽選連動至第 3 階申復庫 | 選填 |
| `GET` | `/api/appeal/batch-report` | 核減事後申復批次報告（比照當月申報預審格式） | **必填** |
| `POST` | `/api/appeal/cases/clear` | 清空所有第 3 階申復案件 | 選填 |
| `GET` | `/api/appeal/export-batch-xml` | 全批次導出申復 XML（Big5 TOTFA.zip） | **必填** |
| `GET` | `/api/sampling/cases` | 抽審名冊案件列表 | **必填** |
| `POST` | `/api/his/soapvoice-ingest` | 接收診間 SoapVoice 錄音與截圖並自動歸檔至 EvidenceVault (Phase 24) | 選填 |
| `POST` | `/api/his/webbrain/nhi-extract` | 預讀健保雲端藥歷與檢驗報告並自動注入 SOAP O 段 (Phase 25) | 選填 |
| `POST` | `/api/his/webbrain/action` | 解析工作台二階／三階語意化操作計劃 (Phase 25) | 選填 |
| `POST` | `/api/sampling/audit` | 事前預審支持度評估 | 選填 |
| `POST` | `/api/sampling/import` | 匯入抽審名冊（CSV/PDF/影像） | 選填 |
| `GET` | `/api/appeal/cases` | 申復草稿案件列表 | **必填** |
| `POST` | `/api/appeal/generate` | 核減申復草稿生成 | 選填 |
| `POST` | `/api/appeal/import` | 匯入核減清單 | 選填 |
| `POST` | `/api/appeal/attachments/upload` | 上傳影像佐證（Phase 12） | 選填 |
| `GET` | `/api/appeal/attachments/<case_id>` | 列出佐證附件（Phase 12） | **必填** |
| `DELETE` | `/api/appeal/attachments/<case_id>/<id>` | 刪除佐證附件（Phase 12） | **必填** |
| `POST` | `/api/deduction/print` | 核減明細原格式 PDF（Phase 13） | 選填 |
| `POST` | `/api/appeal/evidence-packet/print` | 佐證包 PDF 合成（Phase 14） | 選填 |
| `GET` | `/api/output/<檔名>.pdf` | 下載列印產出 PDF | **必填** |
| `POST` | `/api/soap/search-patient` | 門診歷史病患與看診紀錄時間軸查詢 (Phase 27) | 選填 |
| `GET` | `/api/soap/live-session` | 護理專員即時錄音監控與 ASR 逐字稿 (Phase 27) | 選填 |
| `GET` | `/api/soap/cases/<case_id>/export-forensic-zip` | 一鍵導出法庭與健保審查 ZIP 佐證包 (Phase 27) | 選填 |
| `POST` | `/api/emr/batch-package` | 批次標準 11 碼重命名與 500MB ZIP 分包產製 (Phase 28) | 選填 |
| `GET` | `/api/emr/packages` | 查詢已產製之 EMR 審查封包清單 (Phase 28) | 選填 |
| `GET` | `/api/emr/download/<filename>` | 安全下載 500MB EMR 審查 ZIP 封包 (Phase 28) | 選填 |
| `GET` | `/api/rules/status` | 查詢規則庫列數、佔位檢查與最新來源 CSV (Phase 36) | 院內信任 |
| `POST` | `/api/rules/upload` | 上傳官方給付／藥品規則 CSV（單路由上限 65 MB，Phase 36） | 院內信任 |
| `POST` | `/api/rules/sync` | 原子同步規則庫（預設 `upsert`；`replace: true` 須帶 `confirm: "REPLACE_RULES"`，Phase 36–37） | 院內信任 |

> **認證說明**：已移除 `X-API-Key`；所有端點皆以來源位址信任判定（詳見「認證」小節），審計日誌的 `caller_id` 為來源位址。

---

## 🧱 API 程式結構

`server.py` 只是 WSGI／開發伺服器入口（`app = create_app()`）；API 本體位於 `src/elc_audit_engine/api/`：

| 模組 | 職責 |
|---|---|
| `app.py` | `create_app(config, *, case_store, migrate_legacy)`：設定、注入 CaseStore、註冊 hooks／錯誤處理／blueprints。匯入套件本身無副作用。 |
| `security.py` | Host 白名單、API key 認證（豁免清單）、安全標頭、存取審計 |
| `errors.py` | `ApiError` 與統一錯誤處理（脫敏、4xx 語意） |
| `cases.py`／`records.py`／`uploads.py`／`validation.py` | 案件轉換與持久化、病史時間窗、上傳暫存、欄位驗證 |
| `routes/` | `misc`（首頁、健康檢查、PDF 下載）、`sampling`、`appeal`、`attachments`、`printing` 五個 blueprint |

測試以 `create_app(..., case_store=CaseStore(tmp), migrate_legacy=False)` 建立隔離實例（見 `tests/conftest.py` 的 `make_api_app`），不再 monkeypatch 模組全域變數。

## 🪟 Windows 端 MockHIS 校正探針（Phase 30-09）

位於 `deploy/windows_agent/mock_his/`，用來在 Windows 測試機上驗證「寫入 → 讀回 → 比對」流程，全程只使用假資料（`TEST-*`）。

- **`mock_his.py`**：替身視窗（標題含「MockHIS」）。客戶區使用 Win32 原生 EDIT／STATIC 控制項，**不可改回 Tkinter**（Tkinter 不會被 UI 自動化讀取）。
- **`probe_readback_check.py`**：探針，依 agent-desktop 2.6 的快照格式（`data.tree`、`ref_id`、角色 `textfield`）定位「主訴 (S)」欄位，以 `set-value` 寫入、`get <REF> --property value` 讀回並比對 SHA-256。找不到 MockHIS 視窗即中止（fail-closed）。標題匹配會排除系統殼層視窗（檔案總管、PowerShell、命令提示字元、Terminal），避免資料夾名稱含 `MockHIS` 造成誤判（2026-11-17）。
- **`handoff/`**：交接給他人的壓縮包與操作說明（含 SHA-256 校驗碼）。不含任何病患資料庫。
- **測試**：`uv run pytest tests/test_phase30_probe_detection.py tests/test_phase30_probe_mock.py`

> `--test-vendor <關鍵字>` 會允許對真實廠商視窗寫入，**僅限示範資料的測試機**，不得放入交接包。

---

## 📂 專案架構文件參考
- **診所主機維運速查卡（一頁式非工程師 SOP）**：[`docs/CLINIC_SERVER_OPS_QUICKCARD.md`](docs/CLINIC_SERVER_OPS_QUICKCARD.md)
- **全景架構升級計畫**：[`plan-v5.md`](docs/plans/plan-v5.md)（深度整合 SoapVoice、Agent-Desktop 與 WebBrain）
- **開發進度與里程碑**：[`progress.md`](progress.md)
- **改進意見與架構分析**：[`deepflash4improve.md`](deepflash4improve.md)
