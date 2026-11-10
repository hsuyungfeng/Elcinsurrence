# Phase 30: Windows 執行檔、錄音→SOAP 審核與 HIS 首次校正 - Context

**Gathered:** 2026-11-09
**Status:** Ready for planning
**Source:** 使用者於 `/gsd-plan-phase` 的需求描述＋三題確認（phase 位置、錄音程式位置、審查預設）

<domain>
## Phase Boundary

本 phase 交付三件事，且全部依賴 Phase 29（SOAP 審核＋HIS 回寫，尚未合併到 `main`）：

1. **Windows 執行檔（解壓即用）**：agent-desktop 的功能必須編進 Windows 執行檔。執行檔為乾淨（clean）的可攜式建置，解壓後自動尋找區網內的 local server（elc-audit-engine）。
2. **錄音→SOAP 審核→HIS 寫入**：SoapVoice 錄音完成後，自動跳出 SOAP 審核視窗，醫師修改後直接寫入 HIS 的 SOAP 欄位。可選「自動接入」或「每案先審查」，**預設每案先審查**。目的為匯入語音檔與 SOAP 英文檔。
3. **HIS 歷史介面首次使用校正**：第一次使用時，讀取 HIS 的檔案／畫面結構，把 SOAP 校正項逐項列出，由人工校正。診斷碼、醫令、藥令只顯示為建議，不自動寫入。

</domain>

<decisions>
## Implementation Decisions

### 錄音位置（已確認）
- **D-30-01** 錄音功能實作在 `~/Desktop/SoapVoice` 倉，不在本倉重做。
- **D-30-02** 本倉（elc-audit-engine）只負責：接收 SoapVoice 產出的語音檔與 SOAP 草稿、提供審核 API 與審核視窗、以及 HIS 回寫。兩倉之間的資料契約必須在計畫中明列（欄位、檔名、認證方式）。

### 審查模式（已確認）
- **D-30-03** 預設為「每案先審查」：錄音完成後自動開啟 SOAP 審核視窗，醫師確認後才寫入 HIS。
- **D-30-04** 提供「自動接入」選項（設定開關），開啟後草稿通過既有品質檢核即直接排入 HIS_PUSH，不經審核視窗。開關切換必須寫入審計紀錄。
- **D-30-05** 沿用 Phase 29 既定規則：只寫入 S/O/A/P；診斷碼、醫令、藥令僅為建議。

### Windows 執行檔
- **D-30-06** 執行檔須包含 agent-desktop 功能（沿用 `src/elc_audit_engine/agent_desktop_bridge.py` 的 `AgentDesktopRunner`／`HISPushAutomator`）。
- **D-30-07** 建置方式（PyInstaller 單檔或資料夾 vs. 既有 Inno Setup 流程）由 researcher 與 planner 決定，但產物必須是「解壓即可執行、不需安裝」的 clean 包。既有 `installer/build_clinic_installer.py`（Phase 26）為可重用基礎。
- **D-30-08** 啟動時自動尋找區網 local server：依序嘗試 (a) 設定檔中上次成功位址、(b) 區網 UDP 廣播或 mDNS 探索、(c) 同網段探測 `GET /api/health`。全部失敗時顯示可手動輸入位址的畫面。不得依賴固定 IP（Phase 29 R3 已確認主機 IP 不固定）。
- **D-30-09** 探索到的 server 必須以 API key 認證（沿用 Phase 9 `auth.py` 的 `caller:key` 機制），未認證時不得傳送任何病歷內容。

### HIS 首次校正
- **D-30-10** 首次使用（無校正設定檔時）進入校正精靈：讀取 HIS 的檔案結構或視窗結構，列出 SOAP 所有校正項（如 S/O/A/P 的欄位位置、輸入方式、儲存按鈕），**逐項**由人工確認或修正。
- **D-30-11** 校正結果存為每台機器的 profile（沿用 Phase 29 的 vendor profile 概念）。未校正完成前拒絕真實回寫（Phase 29 blocker 條件延續）。
- **D-30-12** 診斷碼、醫令、藥令以唯讀清單顯示為建議，不參與自動寫入。

### Claude's Discretion
- 錄音→本倉的傳輸方式（HTTP 上傳 vs. 佇列檔案），由 planner 依既有 `bridge_queue` 評估後決定。
- 校正精靈的 UI 形式（獨立頁面 vs. 嵌入 HIS 歷史頁），由 researcher 提出建議。
- 「英文 SOAP 檔」的確切格式（LLM 草稿英文 vs. 外部檔案）尚未確認，researcher 應從 SoapVoice 與既有 `soap_templates` 推斷，並於 RESEARCH.md 列為待確認項。

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 29（直接前置）
- `.planning/phases/29-soap-review-his-writeback/29-DESIGN.md` — 草稿狀態機、審核 API、HIS_PUSH 寫入規則
- `.planning/phases/29-soap-review-his-writeback/29-IMPLEMENTATION.md` — 已完成的實作內容
- `.planning/phases/29-soap-review-his-writeback/29-TEST-NOTES.md` — A1–A8 測試與已知風險
- `deploy/windows_agent/agent.py` — 既有 Windows agent（pull 模式、心跳）

### Agent Desktop 與安裝包（Phase 26）
- `.planning/phases/26-agent-desktop-his-push-and-installer/26-01-SUMMARY.md` — 既有 ClinicClientInstaller 封裝
- `installer/build_clinic_installer.py` — Inno Setup 腳本與清單產生器
- `src/elc_audit_engine/agent_desktop_bridge.py` — `AgentDesktopRunner`、`HISPushAutomator`、`process_his_push_job`

### 錄音（外部倉）
- `~/Desktop/SoapVoice/SoapVoice-Offline.spec` — 既有 PyInstaller 規格，可作為 Windows 打包參考
- `~/Desktop/SoapVoice/WINDOWS_QUICK_START.md` — 錄音端 Windows 啟動說明

### 認證與佇列
- `src/elc_audit_engine/auth.py` — `caller:key` 與 constant-time 比對
- `src/elc_audit_engine/bridge_queue.py` — CAS 任務佇列（沿用於 HIS_PUSH）

</canonical_refs>

<specifics>
## Specific Ideas

- 解壓後雙擊即可執行，無需安裝步驟；首次執行自動探索 server 並顯示連線狀態。
- 錄音完成後的審核視窗應直接顯示 SOAP 四欄（S/O/A/P），診斷碼、醫令、藥令以側欄建議呈現。
- 校正精靈以「一次一項」呈現，每項顯示：目前偵測到的內容、建議值、確認／修正按鈕。

</specifics>

<deferred>
## Deferred Ideas

- Phase 29 尚未合併到 `main`，需使用者確認後才能合併（HANDOFF 中的阻塞項）。本 phase 不處理合併。
- HIS 廠商實機校準（Vision、Yaosheng、Minger、Chihshi）需要 Windows＋HIS 實機，列為外部阻塞，不計入本 phase 的完成條件；本 phase 只交付校正精靈與流程。
- 8 筆未通過品質檢查的範例代碼（`logs/pregen_unresolved_round4.txt`）不在本 phase 範圍。

</deferred>

---

*Phase: 30-windows-exe-soap-review-calibration*
*Context gathered: 2026-11-09 via user requirements and three confirmation questions*

## 使用者決定紀錄（2026-11-10）
- **O3 已接受**：私有 IP（10/8、172.16/12、192.168/16、127.0.0.1）的錄音接收端點免 API key；其他來源與 Agent 金鑰仍受限。
- **O10 已接受**：自動接入的權限預設允許任何非 agent 的 key（不設 `ELC_SOAP_ADMIN_CALLERS` 限制）。
- **需高度自動化**：醫師會在申報與被抽審時自行檢查 SOAP、診斷碼、醫令與藥令，因此整體流程以自動化為優先。
- **O8 待釐清**：HIS 廠商仍未指定；使用者表示不一定每次重新校正。原文「回傳雲端少於10」含義不明，需再確認。
- **O8 已釐清**：HIS 廠商不超過 10 家，多為舊式 Windows GUI。每遇到一家新廠商就必須校正一次；校正結果回傳雲端，供之後的預先校正使用。同一廠商不需重複預校。（注意：「回傳雲端、預先校正」目前不在 30-01～30-10 計畫內，列為待排入的新需求。）
- **預設審查模式**：維持「每案先審查」為預設，「自動接入」為開關（選項 2a）。
- **預先校正仍逐項人工確認（D-30-10 維持）**：使用者於 2026-11-10 確認。
- **HIS 欄位結構（使用者提供）**：SOAP 的分項大多是「一個文字框」；診斷碼、醫令、藥令共用「固定一個輸入／檢索位置」。校正項因此以「每個欄位一項」建模，診斷碼／醫令／藥令各為單一檢索欄位項，不拆成多項。
- **相依性**：30-09（Windows 與 HIS 實機）依賴 30-11（雲端回傳與預先校正），已在 30-09 frontmatter 加入 `30-11`。

## 網頁版 HIS 結構觀察（2026-11-10，唯讀，已去除病患識別資料）
來源：https://doctor-toolbox.com/DoctorConsultation（診療室，醫師已登入的瀏覽器工作階段；僅檢視，未輸入或送出任何資料）
- 病歷頭：病歷編號、建立／更新時間、案件分類下拉（00 自費、01 西醫一般、02 急診…E1），病歷模板的載入／儲存（個人、診所）。
- 錄音區：重新錄音、播放、「回報問題（取得診斷碼）」，另有手機掃 QR 錄音的替代方式。
- SOAP 分項：S Subjective、O Objective、A Assessment、P Plan、Past Medical History 為**各一個文字框**；另有 AI 對話摘要與原始逐字稿展開區。A、P 無獨立「編輯」按鈕，S、O、PMH 有。
- **關鍵發現：「複製SOAP到HIS 到剪貼簿」按鈕**——網頁版目前以剪貼簿交給 HIS，不是直接寫入。此為 HIS 回寫路徑之一，影響 30-09 的實機驗證設計（需確認診所實際使用的是網頁版剪貼簿，還是桌面 HIS 的 UIA 寫入）。
- 診斷碼、醫令、藥令：各為**固定一個搜尋輸入框**（「搜尋 ICD 代碼或名稱」、「搜尋醫療服務代碼或名稱」、「搜尋藥品名稱或代碼」），下方是已選項目清單。與使用者確認的「固定一個輸入檢索位置」一致。
- 操作按鈕：清空 SOAP、更多功能、儲存病歷、完成看診。

## 延後事項：雲端備份（2026-11-10 使用者決定）
- **狀態**：暫不實作，待 Phase 30 完成後再規劃。
- **設計方向（使用者提出）**：由各診所 local server 於夜間事後上傳備份，確保 local server 故障時不影響看診流程。
- **待決定**：本設計若上傳病歷（含病患資料），與鎖定決策 D2（病患資料不離開本機）與 D12（兩層隱私）衝突，必須在規劃前明確修訂決策，並補上加密與授權。僅上傳無病患識別的設定與校正結構則不需修訂 D2（對應 30-11）。
- **HIS 寫入路徑（更正）**：網頁版「複製到剪貼簿」是給桌面版 HIS 用的，不是寫入路徑；30-09 驗證的是桌面版 HIS（agent-desktop UIA）。

- **已修訂決策（2026-11-10）**：D2、D12 已加上修訂註記，新增 D14（雲端備份政策：客戶端加密、本機金鑰、可撤銷授權、審計、夜間事後上傳）。雲端備份功能本身仍未實作，待 Phase 30 完成後規劃。

- **D14 補充（2026-11-10）**：下載權限與解密金鑰分離（金鑰只在本機）；加入離線金鑰匯出與不依賴 local server 的還原流程。預設本機模式；雲端僅接收加密備份與校正結構；網頁版為選用，待法律確認。
