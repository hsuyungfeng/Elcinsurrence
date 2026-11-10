# Phase 30：Windows 執行檔、錄音→SOAP 審核與 HIS 首次校正 - 研究報告

**研究日期：** 2026-11-09
**領域：** Windows 可攜式 agent 打包、跨倉錄音資料契約、LAN 探索、HIS UI 自動化校正
**信心度：** 中（程式碼事實已逐一讀取；打包工具版本與 Windows/HIS 實機行為未驗證）

<user_constraints>
## User Constraints（來源：30-CONTEXT.md，逐字摘錄）

### Locked Decisions
- **D-30-01** 錄音功能實作在 `~/Desktop/SoapVoice` 倉，不在本倉重做。
- **D-30-02** 本倉（elc-audit-engine）只負責：接收 SoapVoice 產出的語音檔與 SOAP 草稿、提供審核 API 與審核視窗、以及 HIS 回寫。兩倉之間的資料契約必須在計畫中明列（欄位、檔名、認證方式）。
- **D-30-03** 預設為「每案先審查」：錄音完成後自動開啟 SOAP 審核視窗，醫師確認後才寫入 HIS。
- **D-30-04** 提供「自動接入」選項（設定開關），開啟後草稿通過既有品質檢核即直接排入 HIS_PUSH，不經審核視窗。開關切換必須寫入審計紀錄。
- **D-30-05** 沿用 Phase 29 既定規則：只寫入 S/O/A/P；診斷碼、醫令、藥令僅為建議。
- **D-30-06** 執行檔須包含 agent-desktop 功能（沿用 `AgentDesktopRunner`／`HISPushAutomator`）。
- **D-30-07** 建置方式（PyInstaller 或 Inno Setup）由 researcher 與 planner 決定，產物必須是「解壓即可執行、不需安裝」的 clean 包。
- **D-30-08** 啟動時依序嘗試：(a) 設定檔中上次成功位址、(b) 區網 UDP 廣播或 mDNS 探索、(c) 同網段探測 `GET /api/health`；全部失敗時顯示手動輸入位址畫面。不得依賴固定 IP。
- **D-30-09** 探索到的 server 必須以 API key 認證（沿用 `auth.py` 的 `caller:key` 機制），未認證時不得傳送任何病歷內容。
- **D-30-10** 首次使用進入校正精靈：讀取 HIS 檔案或視窗結構，列出 SOAP 所有校正項，逐項人工確認或修正。
- **D-30-11** 校正結果存為每台機器的 profile（沿用 vendor profile 概念）。未校正完成前拒絕真實回寫。
- **D-30-12** 診斷碼、醫令、藥令以唯讀清單顯示為建議，不參與自動寫入。

### Claude's Discretion
- 錄音→本倉傳輸方式（HTTP 上傳 vs. 佇列檔案），由 planner 依 `bridge_queue` 評估後決定。
- 校正精靈 UI 形式（獨立頁面 vs. 嵌入 HIS 歷史頁），由 researcher 提出建議（見第 4 節）。
- 「英文 SOAP 檔」確切格式（見 Open Items O1）。

### Deferred Ideas（本 phase 範圍外，勿規劃）
- Phase 29 合併到 `main`（需使用者確認）。
- HIS 廠商實機校準（Vision、Yaosheng、Minger、Chihshi）的實機執行，屬外部阻塞，不計入完成條件。
- 8 筆未通過品質檢查的範例代碼（`logs/pregen_unresolved_round4.txt`）。
</user_constraints>

## Summary

本 phase 有三條獨立的工程線，互相依賴不深，建議平行規劃：

1. **Windows 可攜式 agent**：`deploy/windows_agent/agent.py` 目前只是類別庫（無 `main()`、無設定檔載入、無探索、無 UI），需要包成入口程式。打包建議採 **PyInstaller one-folder（資料夾）＋ zip**，符合「解壓即用」；既有 `installer/build_clinic_installer.py` 只負責「產生 .iss 文字」，可保留作為選用安裝器，不應作為 agent 的主要產物。`agent-desktop` 是外部 Rust CLI（非 pywinauto），必須以資料檔形式隨包附帶。**Linux 上無法產出 Windows exe**，建置與實機驗證必須在 Windows 上執行。
2. **錄音→SOAP 審核→HIS**：SoapVoice 已有錄音（PyAudio → WAV 16 kHz mono PCM16）與 LLM SOAP 生成（`scripts/soapvoice_engine.py`，預設 `output_lang="en"`），也有 httpx 客戶端與離線重試佇列（`client/local_storage.py`、`client/retry_manager.py`）。但 SoapVoice 客戶端**目前沒有任何 API key 標頭**，且上傳目的地是 SoapVoice 自己的 `/api/v1/lan/process`，不是 elc-audit-engine。因此「跨倉契約」與「認證」是本 phase 最大的新增工作。
3. **HIS 首次校正**：Phase 29 已提供 `DEFAULT_HIS_PROFILES`（4 家廠商骨架，全部 `calibrated: False`）、`AgentDesktopRunner.snapshot()` 可取得 UIA 元素清單、`validate_startup_calibration()` 會拒絕啟動。缺的是：校正項資料模型、每機器的儲存格式、逐項確認的精靈 UI，以及「校正完成才允許寫入」的一致閘門。

**Primary recommendation:** 先做「agent 入口＋設定＋探索＋校正資料模型」（可全在 Linux 以 fake 測試），再接錄音契約與審核視窗；打包與實機校正排在最後，並明確標示為 Windows 實機任務。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 錄音與 WAV 產生 | SoapVoice 客戶端（Windows 本機） | — | D-30-01，PyAudio 在本機 |
| SOAP 草稿生成 | SoapVoice 引擎 / elc-audit-engine（待確認 O1） | — | 現有 `generate_extended_soap` |
| 草稿狀態機與審核 API | API / Backend（elc-audit-engine） | Database（CaseStore） | Phase 29 已實作 |
| 審核視窗 | Windows agent（桌面視窗） | — | 需與 UIA 同機，且醫師在診間操作 |
| HIS 寫入與讀回 | Windows agent（agent-desktop） | — | 只有本機能操作 HIS UI |
| LAN server 探索 | Windows agent | API（health 端點） | 客戶端主動找 server |
| HIS 校正項與 profile | Windows agent（本機檔案） | Backend（僅接收去識別化的稽核紀錄） | 校正依機器而異，不得含病歷內容 |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python 標準庫 `urllib`、`socket`、`concurrent.futures`、`tkinter` | 隨 Python 3.11+ | HTTP 客戶端、UDP 廣播、子網探測、校正精靈 UI | 已被 `deploy/windows_agent/agent.py` 採用；無新依賴，減少 Windows 打包風險 |
| agent-desktop（外部 Rust CLI／FFI） | 版本未知（repo 內無二進位） | UIA snapshot／set-value／get-value／paste-to | 既有 `AgentDesktopRunner` 以 subprocess 呼叫 |
| PyInstaller | [ASSUMED] 版本未於本次研究驗證 | 打包 one-folder 執行檔 | `SoapVoice-Offline.spec` 已有 one-folder 範例（`COLLECT` 模式） |
| pytest | 專案既有 | 測試 | `AGENTS.md` 規範 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Inno Setup 6（ISCC.exe） | [ASSUMED] | 選用安裝器 | 僅當診所要求安裝器時；只能在 Windows 執行 |
| httpx（SoapVoice 既有） | 專案既有 | 錄音端上傳 | 沿用 `client/http_client.py` 的 `post_multipart` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| UDP 廣播探索 | mDNS（zeroconf） | mDNS 需第三方套件與 multicast；多數診所路由器與 Windows 防火牆設定較不穩；本 phase 不建議 |
| PyInstaller one-folder | PyInstaller one-file | one-file 每次啟動需解壓到暫存目錄，啟動慢且較易被防毒誤判；one-folder 仍符合「解壓即用」 |
| 手寫 UIA | pywinauto | 專案已決定用 agent-desktop，不應另起 UIA 實作（Phase 29 §7.1） |

**Installation（Windows 建置端，依專案 uv 規範）：**
```bash
uv add --group dev pyinstaller   # 版本需於 Windows 端以 uv 解析確認
```

**Version verification:** 本次研究未驗證 PyInstaller 版本與 slopcheck 結果（見下節）。Windows 建置前須以 `uv` 解析實際版本並記錄。

## Package Legitimacy Audit

本次研究未執行 slopcheck，且未對 PyInstaller 做 registry 驗證。依規範全部標為 `[ASSUMED]`，planner 必須在安裝前加 `checkpoint:human-verify`。

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| pyinstaller | PyPI | — | — | — | 未執行 | [ASSUMED] — planner 須 human-verify |
| (Inno Setup 6) | 非套件 | — | — | jrsoftware.org | 不適用 | 選用，Windows 手動安裝 |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none（未執行）

## Question 1：SoapVoice 錄音、輸出與 HTTP 能力

**錄音位置（已讀取）：**
- `src/gui/desktop_app.py`：`start_recording()` 以 PyAudio 開啟串流（`format=pyaudio.paInt16, channels=1, rate=16000`），`stop_recording()` 寫入 `PROJECT_ROOT/data/recordings/temp.wav`（**固定檔名，會被覆寫**）。`process_recording()` 以 `requests.post(f"{API_BASE_URL}/api/v1/extended/transcribe")` 送出，再以 `/api/v1/extended/process` 取 SOAP。
- `src/asr/recording_session.py`：`RecordingSession` 建立 `data/recordings/{timestamp}_{session_id}/` 目錄，並以 `wave.open` 寫 WAV。
- `src/consultation/consultation_flow.py`：`consultation_flow.py:647` 以 `wave.open` 寫入 `recordings_dir`（預設 `get_user_data_dir()/recordings`）。
- `client/audio_recorder.py`：`AudioRecorder.start()` / `stop()` 回傳 `Optional[str]`（檔案路徑）。格式細節未逐行核對，**採用前須確認**。

**輸出格式：**
- 音檔：WAV（16 kHz、單聲道、16-bit PCM），來自 `desktop_app.py`；`lan_process_api.py` 會在伺服器端壓成 Opus 32 kbps。
- SOAP 草稿：`scripts/soapvoice_engine.py` 的 prompt 模板含 `## English SOAP Note:`，`generate_*` 預設 `output_lang="en"`。**因此 SOAP 草稿預設為英文**；逐字稿（ASR）則為繁體中文（`desktop_app.py` 註解「顯示繁體中文逐字稿」）。這與 Elcinsurrence 的 `validate_soap_quality`（英文為主）一致。SOAP 回傳為 `dict`，確切鍵名（`s/o/a/p` 或 `subjective/...`）**未於本次研究確認**（見 O2）。

**既有 HTTP client：**
- `client/http_client.py`：`AsyncHTTPClient`（httpx），提供 `get()` 與 `post_multipart()`，含 tenacity 式重試。
- `client/lan_client.py`：`LANClient.upload_consultation()` / `_do_upload()` 以 multipart 上傳「wav + 截圖 + 病患資訊」到 `LANConfig.lan_process_endpoint`（`api/v1/lan/process`）；失敗時寫入 `LocalStorageManager`（`queue.json`），連線恢復後由 `retry_pending_uploads()` 補傳。`check_health()` 呼叫 `api/v1/health`。
- **缺口：** 全域搜尋 `client/*.py` 未發現 `X-API-Key` 或 `Authorization` 標頭。SoapVoice 目前的上傳不帶認證，且目標是 SoapVoice 自己的 server，**不是** elc-audit-engine。

**結論（建議）：** 不新增佇列系統。錄音端沿用 `AsyncHTTPClient.post_multipart` 與 `LocalStorageManager` 作為離線暫存，新增一個 elc-audit-engine 端點（建議名稱 `POST /api/soap/recordings`，待 planner 定案），並在 header 帶 `X-API-Key`（SoapVoice 端新增設定項）。

**資料契約草案（須於計畫中明列，D-30-02）：**

| 欄位 | 型別 | 來源 | 說明 |
|------|------|------|------|
| `session_id` | str | SoapVoice | 冪等鍵，重送不重複建草稿 |
| `audio` | multipart file（`.wav`） | SoapVoice | 16 kHz mono PCM16；大小上限待定 |
| `soap` | JSON（`s`/`o`/`a`/`p`） | SoapVoice | 英文草稿；鍵名待 O2 確認 |
| `patient_ref` / `case_id` | str | SoapVoice 或 HIS | 病歷識別；須能對應 HIS 的 `case_id` |
| `visit_date` | ISO date | SoapVoice | 就醫日，供 §8.2 病患比對 |
| `caller` | 由 API key 解析 | 伺服器 | 不接受客戶端自填 |

認證：SoapVoice 使用 `ELC_API_KEYS` 的 `caller:key` 格式（`src/elc_audit_engine/auth.py`，`parse_api_keys`），**不得使用 Agent 金鑰**（Agent 金鑰僅允許心跳與 HIS_PUSH 端點，見 `api/security.py` 的 `AGENT_ALLOWED_ENDPOINTS` 檢查）。

## Question 2：Windows 執行檔打包

**現況（已讀取）：**
- `installer/build_clinic_installer.py`：`generate_inno_setup_script()` 產出 `.iss` 文字，`export_installer_bundle()` 寫入 `installer/`。**此腳本本身可在 Linux 執行**，但產出的 `ClinicClientInstaller.exe` 需在 Windows 以 ISCC 編譯。`[Setup]` 設為 `PrivilegesRequired=lowest`（每使用者安裝）；`[Files]` 期待 `bin\agent-desktop.exe`、`bin\libagent_desktop_ffi.dll`、`config\`、`data\`。
- 其中 `components` 的 `profiles: config/his_profiles.json` 在 repo 中**不存在**；vendor 設定目前實際存在於 `DEFAULT_HIS_PROFILES`（Python dict）。
- `build_clinic_installer.py` 的 launcher 註解提到「UDP 5001 自動探索機房」，但本次研究**未找到**對應的 UDP 監聽程式碼，視為未實作（見 O4）。
- `SoapVoice-Offline.spec`：one-folder 模式（`EXE(..., exclude_binaries=True)` + `COLLECT`），但會打包 llama.cpp、Whisper、chromadb 等數 GB 模型，**不適合**作為 agent 的範本，只能參考結構。
- `SoapVoice/WINDOWS_QUICK_START.md`：Windows 端流程為 `uv sync` → `uv add --group dev pyinstaller` → `pyinstaller --clean <spec>`；建置在 Windows 執行。

**建議：PyInstaller one-folder（`agent.exe` 放在資料夾內）＋ zip，不走 Inno Setup 作為主要產物。**
- 理由：符合「解壓即用、不需安裝」（CONTEXT D-30-07 的硬性條件）；Inno Setup 的 `PrivilegesRequired=lowest` 仍是「安裝」流程。
- Inno Setup 保留為選用安裝器，可直接重用 `build_clinic_installer.py` 的 `generate_inno_setup_script()`，但需修正 `components`（移除 LittleB、WebBrainBridge、RetryManager，因 agent 不需要）。

**必須隨包附帶的內容：**
- `agent-desktop.exe` 與 `libagent_desktop_ffi.dll`（外部二進位，來源與版本**未知**，見 O6）。
- `elc_audit_engine` 套件中 `agent_desktop_bridge.py`、`case_store/soap_draft_states.py` 的 Python 原始碼（`agent.py` 會 import 它們；PyInstaller 需以 `hiddenimports` 或 `pathex` 收集）。
- vendor 設定檔（建議改為 `config/his_profiles.json`，由 Python dict 匯出，並以 JSON Schema 驗證）。
- 校正檔存放於 `%LOCALAPPDATA%\ElcAgent\`（不隨包發佈，見第 4 節）。

**pywinauto 狀況：** repo 中 `pyproject.toml` 與 `requirements*.txt` 未列 `pywinauto`；UIA 完全由 agent-desktop 提供，**不需要** pywinauto。

**Linux 可否建置：** 不可。PyInstaller 不支援跨平台建置，產物必須在 Windows 執行。Linux 上只能做：(1) 產生 spec／清單；(2) 以 Linux Python 跑所有不依賴 Windows API 的單元測試；(3) 以 mock 驅動測試 `AgentDesktopRunner`。**需 Windows 的項目：** PyInstaller 建置、`agent-desktop.exe` 實際執行、`subprocess` 行為、防火牆、`%LOCALAPPDATA%` 路徑、Inno Setup（若採用）。

**Windows 專屬的已知陷阱（planner 應列入驗收）：**
- `subprocess.run` 在 `console=False`（視窗模式）下會閃出 console；建議 `creationflags=subprocess.CREATE_NO_WINDOW`。
- `text=True` 在 Windows 預設 cp950／cp1252 解碼，agent-desktop 輸出含中文欄位名時會亂碼；建議 `encoding="utf-8", errors="replace"`。
- `DEFAULT_HIS_PROFILES` 的 `name` 以子字串比對（`match_fields_to_refs` 的 `target_name in elem.name`）。Yaosheng／Minger 的 `name` 為單字 `"S"`、`"O"`、`"A"`、`"P"`，**會誤中任何含大寫 S/O/A/P 的元素名**（例如 "SOAP"、"Status"）。校正前必須以 `automation_id` 優先，並限制 `role`。

## Question 3：LAN 探索

**三種方式比較（以 Windows 診所區網為情境）：**

| 方式 | 優點 | 缺點 | 實作成本 |
|------|------|------|----------|
| (a) 設定檔記住上次位址 | 最快、無網路流量 | 首次或 server 換 IP 會失效 | 極低（必做） |
| (b) UDP 廣播（255.255.255.255 或子網廣播） | 快（~1 秒）、只用標準庫 | 需 server 端新增 UDP 監聽（目前 repo 無）；路由器不跨 VLAN；Windows 防火牆首次會跳出允許提示；需挑未被佔用的 port（installer 註解的 UDP 5001 已被 LittleB 語境使用，衝突風險） | 中 |
| (b') mDNS（zeroconf） | 名稱可讀（如 `elc.local`） | 需第三方套件；診所路由器／交換器常過濾 multicast；Windows 端行為不一 | 中高，不建議 |
| (c) 子網探測 `GET /api/health` | 不需改 server；標準 HTTP；防火牆只需開既有 port | 需推算本機網段（`socket` 技巧取得本機 IP）；/24 約 254 次請求，需並行與短逾時；可能找到多台 | 低中 |

**建議（沿用 D-30-08 的順序，並做兩點修正）：**
1. (a) 讀取 `%LOCALAPPDATA%\ElcAgent\config.json` 的 `last_server_url`，`GET /api/health` 驗證。
2. (b) UDP 廣播作為「加速」選項：送出固定查詢字串，server 回覆 `{"service":"elc-audit-engine","url":"http://IP:PORT"}`。**若 server 未實作監聽，則略過此步，不阻擋流程。**
3. (c) 子網探測：以 `ThreadPoolExecutor(max_workers=64)`、每台逾時 0.5 秒、`GET /api/health`，並以回應中的服務識別欄位（非僅 HTTP 200）確認身分，找到多台時列出讓使用者選擇。
4. 全部失敗：顯示手動輸入畫面（URL 格式驗證，只接受 `http://` 且須為私有 IP 段）。

**安全規則（對應 D-30-09）：** 探測階段只送 `GET /api/health`，**不送 API key、不送任何病歷內容**。取得可信位址後，才以 `X-API-Key` 發送心跳（`agent.py` 的 `DefaultHttpClient` 已用 `X-API-Key` 標頭）。`/api/health` 是否在認證豁免清單內，**未於本次研究確認**（O5）；若否，探測會得到 403，需改以「不含 PHI 的 401 回應 + 服務識別標頭」判定，或將 health 加入豁免。

**規模估計：** 同網段 /24、本機 LAN，並行探測通常在數秒內完成；實際耗時需於診所實機量測（屬 Windows 實機項目）。

## Question 4：HIS 首次使用校正

**Phase 29 已提供（已讀取）：**
- `DEFAULT_HIS_PROFILES`（`src/elc_audit_engine/agent_desktop_bridge.py`）：`vision`、`yaosheng`、`minger`、`chihshi` 四家；每家含 `exe_names`、`calibrated`、`calibrated_at`、`calibrated_by`，以及 `fields` 的 `soap_s/soap_o/soap_a/soap_p/icd10`（每個為 `automation_id`、`name`、`role`）。**全部 `calibrated: False`。**
- `AgentDesktopRunner.snapshot(app_name)`：呼叫 `agent-desktop snapshot --app <name> -i --json`，回傳 `UIElementRef` 列表（可作為校正精靈的「偵測到的內容」來源）。
- `HISPushAutomator.match_fields_to_refs()`、`push_case_to_his(write_soap_only=True)`：只寫 S/O/A/P，其他欄位只進 `fallback_copy_card`。
- `deploy/windows_agent/agent.py`：
  - `validate_startup_calibration()`：`config.calibrated` **或** `profiles[vendor].calibrated` 任一為真即放行（OR 邏輯）；`allow_uncalibrated=True` 可繞過。
  - `execute_job()`：只檢查 `self.config.calibrated`（AND 於 profile 之外）。**兩處邏輯不一致**，應統一為單一來源。
  - `execute_job()`：病患比對只在 `current_patient_getter is not None` 時執行；**預設為 None，等於病患比對被略過**，須改為 fail-closed。
  - 讀回驗證：以 `compute_soap_content_hash` 比對（`soap_draft_states.py`）。
- `installer/build_clinic_installer.py`：提到 `HIS 自動寫入設定精靈` 作為 `agent-desktop.exe` 的捷徑，**指向的是 agent-desktop 本身**，不是本 phase 要做的精靈。

**缺少的部分（需新增）：**

資料模型（每個校正項一筆，JSON 儲存）：

| 欄位 | 說明 |
|------|------|
| `item_key` | 唯一鍵，例如 `soap_s.input` |
| `section` | `S` / `O` / `A` / `P` / `ICD10` / `ORDER` / `MED` / `PATIENT_ID` / `SAVE_BUTTON` |
| `kind` | `writable`（可寫入）、`save_action`、`identity_check`、`advisory_only`（僅顯示，對應 D-30-12） |
| `detected` | 去識別化快照：`role`、`automation_id`、`name`、`control_type`、視窗標題（**不含元素 value**） |
| `suggested` | 系統建議的選擇器（由 `detected` 推導） |
| `confirmed` | 醫師／工程師確認後的選擇器；`null` 表示未確認 |
| `status` | `pending` / `confirmed` / `corrected` / `skipped` |
| `confirmed_by`、`confirmed_at` | 稽核欄位，只記錄人員代號與時間 |

Profile 層（每台機器每家廠商一份）：`vendor_key`、`machine_id`（本機產生的 UUID，不用 MAC）、`vendor_version`、`schema_version`、`items[]`、`readback_test_passed`（以測試病歷寫入並讀回一次）、`calibrated_at`、`calibrated_by`。

**「已校準」的唯一判定（建議）：** 所有 `kind in (writable, save_action, identity_check)` 的項目皆為 `confirmed` 或 `corrected`，**且** `readback_test_passed == true`。此判定取代目前的 `calibrated: bool` 旗標，`validate_startup_calibration()` 與 `execute_job()` 都改讀此判定。

**儲存位置：**
- 本機：`%LOCALAPPDATA%\ElcAgent\calibration\<vendor_key>-<machine_id>.json`，不隨安裝包發佈，不進 git。
- 伺服器：只接收「校正完成」事件（vendor、machine_id、時間、人員代號、項目數），**不含**元素名稱以外的細節、不含病歷內容（符合 29-DESIGN §10）。

**UI 形式建議：** 校正精靈必須在 Windows 本機執行（需要 UIA 快照），**不應**做成伺服器網頁。建議以 stdlib `tkinter` 做獨立視窗，與 agent 同一支 exe 內（PyInstaller 會收集）。每次一項，顯示「目前偵測到的內容／建議值／確認／修正／略過」，符合 CONTEXT specifics。診斷碼、醫令、藥令項目以唯讀區塊呈現，`kind=advisory_only`，不產生 `writable` 選擇器。

## Question 5：風險、阻塞與 Linux 可測項目

### 風險與阻塞
| # | 風險 | 影響 | 緩解 |
|---|------|------|------|
| R1 | 無 Windows＋HIS 實機 | 打包、UIA、校正無法在本環境驗證 | 本 phase 完成條件只含 Linux 可驗證項＋Windows 建置腳本；實機列為外部阻塞（CONTEXT Deferred） |
| R2 | 四家 vendor profile 皆未校準 | 真實寫入不可用 | 校正精靈＋閘門；未校準時拒絕寫入（既有行為保留） |
| R3 | Phase 29 尚未合併；目前工作區為未提交變更（29-IMPLEMENTATION 註明「不要 commit」） | Phase 30 依賴的程式碼可能不穩定 | 規劃前先由使用者決定 Phase 29 合併方式（deferred 項目） |
| R4 | `agent-desktop` 二進位不在 repo 內，版本與來源未知 | 打包後可能無法執行 | 列為 O6，需使用者提供 |
| R5 | `agent.py` 病患比對預設略過 | 可能寫入錯誤病歷（PHI 與醫療安全） | 改為 fail-closed：`current_patient_getter` 為 None 時拒絕寫入 |
| R6 | 子字串比對誤命中（`"S"`） | 寫入錯誤欄位 | 校正後以 `automation_id` 為主；加測試（見下） |
| R7 | 校準旗標 OR／AND 不一致 | 繞過閘門 | 統一為單一判定（第 4 節） |
| R8 | 錄音端無 API key、目標不同 server | 上傳被拒或資料落錯地方 | 契約明列（第 1 節）；新增端點與 key 設定 |
| R9 | `temp.wav` 固定檔名 | 連續錄音互相覆寫 | 改用 `session_id` 命名（SoapVoice 端） |

### Open Items（需使用者確認，不得自行假定）
- **O1** 英文 SOAP 檔的確切格式：目前證據指向「LLM 生成英文草稿」（`soapvoice_engine.py` 預設 `output_lang="en"`），但 CONTEXT 仍標為未確認。請確認是「LLM 草稿」還是「外部既有檔案」。
- **O2** SoapVoice 回傳的 SOAP `dict` 鍵名（`s/o/a/p` 或其他）與是否含 `icd10`／醫令／藥令。
- **O3** 錄音→本倉的傳輸：HTTP 上傳（建議）或檔案佇列；API key 如何配發給 SoapVoice 客戶端（建議 `ELC_API_KEYS` 新增一個 caller）。
- **O4** LAN 探索的 UDP port 與服務識別字串；installer 註解中的 UDP 5001 是否保留給 LittleB。
- **O5** elc-audit-engine 的 `/api/health` 是否在認證豁免清單；elc-audit-engine 實際監聽的 port。
- **O6** `agent-desktop.exe` 與 `libagent_desktop_ffi.dll` 的來源、版本、授權。
- **O7** 本次讀取的 Phase 29 程式碼是否為最終版（目前未合併、未提交）。
- **O8** 診所實際使用的 HIS 廠商（決定先校正哪一家）。
- **O9** 校正精靈是否接受 tkinter 獨立視窗（建議）或需要其他 UI 框架（會增加打包體積）。
- **O10** 「自動接入」開關的預設狀態與權限（誰能切換；D-30-04 要求寫審計，格式待定）。

### Validation Architecture（Linux 可跑、以 fake 替代 Windows／HIS）

> `.planning/config.json` 未於本次讀取；依規範視為啟用。測試框架為 pytest（`AGENTS.md`）。

| 需求 | 測試類型 | 指令（Linux） | 備註 |
|------|----------|----------------|------|
| 探索：設定檔位址優先 | unit | `uv run pytest tests/test_agent_discovery.py::test_last_known_url_first -x` | 注入假 health 函式 |
| 探索：子網探測找到服務 | integration | 同上檔案 `::test_subnet_probe_finds_stub` | 以 `http.server` 綁 127.0.0.1 模擬，host 清單注入 |
| 探索：不送 key、不送病歷 | unit | `::test_probe_sends_no_api_key` | 攔截請求標頭與 body |
| 契約：缺 `session_id` 或 `soap` 拒絕 | unit | `uv run pytest tests/test_soap_recording_contract.py -x` | 用 SoapVoice 真實回傳的 fixture（待 O2） |
| 認證：Agent 金鑰無法呼叫錄音端點 | unit | `uv run pytest tests/test_soap_review_api.py -k agent -x` | 延伸既有 Phase 29 測試 |
| D-30-04 開關寫審計 | unit | `uv run pytest tests/test_auto_accept_toggle.py -x` | 驗證審計列且不含 SOAP 內文 |
| 校正：未完成不得寫入 | unit | `uv run pytest tests/test_windows_agent.py -k calibration -x` | 擴充既有測試 |
| 校正：advisory 項目不產生 writable 選擇器 | unit | `uv run pytest tests/test_calibration_model.py -x` | |
| 校正：JSON 儲存往返與部分確認狀態 | unit | `uv run pytest tests/test_calibration_store.py -x` | 使用 `tmp_path` |
| 病患比對 fail-closed | unit | `uv run pytest tests/test_windows_agent.py -k patient -x` | 新增 getter 為 None 的案例 |
| 子字串誤中（`"S"` 比 `"SOAP"`） | unit | `uv run pytest tests/test_his_matcher.py -x` | 對 `match_fields_to_refs` 的已知缺陷寫紅燈測試 |
| 中文輸出解碼與 `CREATE_NO_WINDOW` | unit（mock subprocess） | `uv run pytest tests/test_agent_runner_windows.py -x` | 僅驗證參數，不需 Windows |
| PyInstaller 打包與 `agent-desktop.exe` 執行 | manual（Windows） | Windows：`uv run pyinstaller --clean agent.spec` 後 `dist\ElcAgent\ElcAgent.exe --selftest` | Linux 無法執行，列為實機驗收 |

### Wave 0 Gaps
- [ ] `tests/test_agent_discovery.py`：探索模組與 fake HTTP 伺服器
- [ ] `tests/test_calibration_model.py`、`tests/test_calibration_store.py`：校正資料模型與儲存
- [ ] `tests/test_soap_recording_contract.py`：跨倉契約與 SoapVoice fixture（需 O2）
- [ ] `tests/test_his_matcher.py`：子字串誤中的紅燈測試
- [ ] `tests/test_auto_accept_toggle.py`：D-30-04 審計

## Sources

### Primary（HIGH，已於本 repo 讀取）
- `.planning/phases/30-windows-exe-soap-review-calibration/30-CONTEXT.md`
- `.planning/ROADMAP.md`（Phase 30 段）
- `.planning/phases/29-soap-review-his-writeback/29-DESIGN.md`、`29-IMPLEMENTATION.md`
- `.planning/phases/26-agent-desktop-his-push-and-installer/26-01-SUMMARY.md`
- `installer/build_clinic_installer.py`
- `src/elc_audit_engine/agent_desktop_bridge.py`
- `deploy/windows_agent/agent.py`
- `src/elc_audit_engine/auth.py`（`ELC_API_KEYS`、`ELC_AGENT_KEYS`）、`src/elc_audit_engine/api/security.py`（`AGENT_ALLOWED_ENDPOINTS` 檢查）
- `src/elc_audit_engine/api/routes/agent_bridge.py`、`misc.py`（`/api/health`）
- `~/Desktop/SoapVoice/SoapVoice-Offline.spec`、`WINDOWS_QUICK_START.md`、`AGENTS.md`
- `~/Desktop/SoapVoice/src/gui/desktop_app.py`、`client/lan_client.py`、`client/lan_config.py`、`client/http_client.py`、`client/local_storage.py`
- `~/Desktop/SoapVoice/src/api/lan_process_api.py`、`scripts/soapvoice_engine.py`（grep 片段）

### Secondary / Not verified
- PyInstaller 版本與 slopcheck：未驗證（[ASSUMED]）。
- agent-desktop：外部二進位，無法於本 repo 驗證。
- Windows 防火牆與 UDP 廣播在診所網路的實際行為：未驗證（需實機）。

## Metadata

**Confidence breakdown:**
- Standard stack: 中；PyInstaller 版本未驗證。
- Architecture: 高；以讀取的程式碼為準。
- Pitfalls: 高（R5、R6、R7 直接來自程式碼）；Windows 專屬（subprocess、編碼）中，需實機確認。
- Discovery 效能與可靠性：低，需實機量測。

**Research date:** 2026-11-09
**Valid until:** 7 天（Phase 29 尚未合併，程式碼可能變動）
