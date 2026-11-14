# Phase 32: 院內免驗證客戶端一體化與醫師上手 - Context

**Gathered:** 2026-11-14
**Status:** Ready for planning
**Source:** Fable5.2improvplan.md（第五節裁示、第七節未完成項、7.5 策展審查）— 使用者選擇「直接用計畫當決策來源」，未經 discuss-phase。

<domain>
## Phase Boundary

第一期（LAN 信任模式、快捷列接進執行檔、無主控台、移除寫死位址）已在工作區完成但未提交，不屬本 phase。
本 phase 交付剩餘範圍：客戶端一體化安裝、連線自動化、主機一鍵安裝與狀態頁、備份、醫師介面、實機驗證。

</domain>

<decisions>
## Implementation Decisions

### 已裁示（使用者，2026-11-13）— 鎖定
- **D-32-01** 信任範圍：預設信任伺服器所在整個子網（目前自動偵測為 /24）。
- **D-32-02** 訪客 Wi-Fi 與診間電腦為不同網段（前提成立）。安裝精靈仍須顯示信任網段供確認。
- **D-32-03** 平台：主機一律 Ubuntu Server；不做 Windows 主機。客戶端 Windows。
- **D-32-04** 保存期限：客戶端 3 個月自動清理；主機端永久保存，不實作任何自動刪除。
- **D-32-05** SoapVoice 併入同一個安裝檔，由 ElcAgent 負責啟動與看管。
- **D-32-06** 不保留金鑰模式，僅區網使用。（第一期已實作。）
- **D-32-07** 備份採「完整一份＋每日增量」，不得輪替覆寫；備份媒體須可擴充（NAS 或可換外接磁碟）。
- **D-32-08** 主機端狀態頁須能提前數個月預警磁碟不足。

### 已裁示（使用者，2026-11-14 第一批）— 鎖定，取代下方 OPEN 項
- **D-32-09** 診間端（Windows 客戶端）只負責錄音與上傳，**不做本機轉錄**。SoapVoice 打包範圍不含 torch／Whisper 等推論依賴；規劃仍須以任務確認 client/ 實際 import 的依賴，若發現違反此決定須回報而非自行擴大範圍。
- **D-32-10** 不購買程式碼簽章憑證。安裝說明文件須寫明 SmartScreen 警告與繞過步驟（僅限受信任來源）。
- **D-32-11** 備份媒體：Windows 端 **NTFS**；主機端 **exFAT**。exFAT 不支援硬連結，**因此 D4 作廢 `rsync --link-dest` 設計**。改為：SQLite 以 `.backup` 取快照、檔案以「只複製新增或變更檔、永不刪除」的增量方式寫入，並以雜湊驗證。不得依賴硬連結、符號連結或 Unix 權限。
- **D-32-12** C2 縮減為**只用 UDP 廣播**（客戶端送出、伺服器單播回覆），不做 mDNS。
- **D-32-13** 容量預警門檻：黃燈 180 天、紅燈 90 天（依預估剩餘天數）。
- **D-32-14** E 醫師模式先做 **E8 檔案拆分**，其餘 E 項拆為子批次，逐批規劃。
- **D-32-15** 第一期改動已於 `01e1a13` 提交，規劃以該提交為基準。

### 已裁示（使用者，2026-11-14 第二批，OPEN-32-01..06 處置）— 鎖定
- **D-32-16（OPEN-32-01）** 網段偵測讀取介面實際遮罩，`deploy/install.sh` 顯示並要求安裝人員確認後寫入 `ELC_TRUSTED_SUBNETS`；fail-closed 保守防護。
- **D-32-17（OPEN-32-02）** 列舉主機網路介面，自動排除 tun/tap/ppp/wg/docker/veth 等虛擬與 VPN 介面；單一私有 IPv4 候選自動採用，多候選由安裝人員於 install.sh 中選擇並寫入 `ELC_TRUSTED_SUBNETS`。
- **D-32-18（OPEN-32-03）** 跨站 GET 請求（帶 `Sec-Fetch-Site: cross-site`）一律拒絕（403）；`none`（直接造訪）、`same-origin`、`same-site` 或無標頭（原生客戶端）放行；其餘未帶憑證之區網讀取列為已接受取捨。
- **D-32-19（OPEN-32-04）** `PUT /api/soap/settings/auto-accept` 與 `POST/PUT /api/facility` 寫入權限僅限伺服器本機 `loopback`（127.0.0.1），禁止區網端點直接修改。
- **D-32-20（OPEN-32-05）** 客戶端暫存採「時間＋容量雙軌並存，但只刪已確認上傳成功者」：超過 3 個月且已確認上傳之循環自動刪除；超過容量上限（2GB）時優先清除已上傳之最舊循環；尚未上傳之循環永不刪除，並在快捷列與狀態頁發出警示。
- **D-32-21（OPEN-32-06）** SoapVoice 診間端已確認不含 torch/Whisper（D-32-09，實體無違規），採同一 Inno Setup 安裝程式內包含兩個獨立元件（ElcAgent 必選、SoapVoice 客戶端輕量 one-folder），版本分離並由 ElcAgent 負責拉起與看管。

### 追認（使用者，2026-11-14）— 鎖定
- **D-32-16** 網段偵測讀取實際遮罩，不再硬編碼 /24。
- **D-32-17** 偵測時排除 loopback 與 VPN／虛擬介面（tun、wg、docker 等）。
- **D-32-18** 跨站 GET（`Sec-Fetch-Site: cross-site`）一律 403。
- **D-32-19** 管理類寫入（自動接入開關、院所設定）僅限伺服器本機 127.0.0.1。
- 上列四項由執行代理實作於 `lan_trust.py`，使用者已於 2026-11-14 確認保留。

### 裁示（使用者，2026-11-14）— OPEN-32-05 已解決
- **D-32-20** 客戶端保存以**時間為準：3 個月**。
- **D-32-21** 既有 2GB 容量上限仍保留，但只作為警示，**只刪除已確認上傳至主機的資料**；未上傳的資料永不刪除，改為警示。（此條為依 OPEN-32-05 選項推導，使用者可further 修改。）
- 報告編號修正（使用者同意）。

### OPEN-32-01..07 處置
全數裁示完畢，已無任何待決 OPEN 項目（OPEN-01..06 歸入 D-32-16..21；OPEN-07 歸入 D-32-12）。

### 第一期已完成（不再規劃，僅驗證）
- A1–A8 院內信任、跨站寫入防護、Host 形式檢查、反向代理 fail-closed（execurator 審查後追加）。
- B1 快捷列接進 ElcAgent.spec 與 --run 預設啟動；B2 console=False、say()、檔案日誌。
- C1 移除寫死的 192.168.68.118。

### 待決事項（策展審查 7.5 — 未裁示，規劃時須以「前置決策任務」處理，不得自行假設答案）
- **OPEN-32-01（7.5 #2）** 網段自動偵測硬編碼 /24；VLAN 或非 /24 遮罩時診間會被 403。解法選項待定：安裝精靈顯示偵測結果請使用者確認 / 強制明示 ELC_TRUSTED_SUBNETS。
- **OPEN-32-02（7.5 #3）** 自動偵測以 10.255.255.255 選路由，預設路由若經健保 VPN 會選錯介面。解法選項待定：列舉實體網卡 / 安裝時綁定網卡名稱。
- **OPEN-32-03（7.5 #4）** GET 讀取病歷與錄音端點不受 CSRF 檢查。待定：是否加「跨站 GET 一律拒絕」（低成本）；是否需診間會話或 cycle 綁定（高成本，屬已接受取捨或須改設計）。
- **OPEN-32-04（7.5 #5）** `PUT /api/soap/settings/auto-accept` 與 `POST/PUT /api/facility` 任何院內裝置可改。待定：限伺服器本機、或加管理 PIN。
- **OPEN-32-05（7.5 #6）** 保存期限衝突：客戶端 3 個月 vs Phase 31 既有 2GB FIFO 容量上限。待定：時間優先或容量優先、或兩者並存的規則。此為 D6 前提。
- **OPEN-32-06（7.5 #8）** B4 SoapVoice 併入：體積數 GB（PyTorch／Whisper／CTranslate2）與 ElcAgent 差距大。待定：併入安裝檔或另裝、由 ElcAgent 看管。
- **OPEN-32-07** 客戶端探索機制（C2）：mDNS vs UDP 廣播，待定。

### Claude's Discretion
- 安裝工具選擇（Inno Setup 為計畫指定；細節可由規劃決定）。
- 系統匣與按鈕文字的具體實作（B5、B8）。
- deploy/install.sh 的步驟順序（D1）。

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

- `Fable5.2improvplan.md` — 本 phase 的主要規格（第三節各項、第五節裁示、第七節進度與 7.5 策展審查）
- `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-WINDOWS-MANUAL-VERIFY.md` — Windows 實機驗證清單（F1 依據；B10 須先修正其設定檔名與啟動指令）
- `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-IPC-CONTRACT.md` — SoapVoice 本機 IPC（local token 屬本機通道，與 A8 不衝突）
- `.planning/phases/31-windows-client-traffic-light-bar-multi-session/31-15-PLAN.md`、`31-08-PLAN.md` — 既有 2GB FIFO 容量上限（OPEN-32-05）
- `deploy/README.md`、`deploy/elc-audit-engine.service` — 主機部署現況（D1 基礎）
- `deploy/windows_agent/ElcAgent.spec`、`scripts/build_windows_agent.py` — 建置與 SHA256（B1 建置驗證）
- `src/elc_audit_engine/lan_trust.py`、`src/elc_audit_engine/api/security.py` — 第一期信任模型現況

</canonical_refs>

<specifics>
## Specific Ideas

- 醫師介面以「不會用電腦」為標準：大字、白話按鈕、三段式錯誤訊息（計畫 E 節）。
- 快捷列三顆按鈕加文字或圖形，不只靠顏色（B8）。
- 驗收：乾淨 Windows 10/11 雙擊安裝 → 三次點擊完成設定 → 右下角出現快捷列；全程無黑視窗、無輸入位址或金鑰。

</specifics>

<deferred>
## Deferred Ideas

- B9 自動更新（P2）
- C5 手動輸入放寬（P2）
- F5 瀏覽器煙霧測試進 CI（P2）
- F6 核對舊 codeimproveplan.md P0（P2）
- ruff 既有 241 個 lint 錯誤清理（與本 phase 無關，另案）

</deferred>

---

*Phase: 32-fable5-2improvplan-md*
*Context gathered: 2026-11-14 from Fable5.2improvplan.md (no discuss-phase)*
