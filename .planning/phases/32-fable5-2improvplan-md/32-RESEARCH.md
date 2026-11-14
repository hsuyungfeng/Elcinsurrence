# Phase 32: 院內免驗證客戶端一體化與醫師上手 - Research

**Researched:** 2026-11-14
**Domain:** Windows 客戶端打包／安裝（PyInstaller + Inno Setup）、區網探索、Ubuntu Server 一鍵部署、備份與容量預警
**Confidence:** MEDIUM（程式現況為 HIGH；Windows 安裝與防火牆行為本環境無法實測，為 MEDIUM／LOW）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- D-32-01 信任範圍：預設信任伺服器所在整個子網（目前自動偵測為 /24）。
- D-32-02 訪客 Wi-Fi 與診間電腦為不同網段（前提成立）。安裝精靈仍須顯示信任網段供確認。
- D-32-03 平台：主機一律 Ubuntu Server；不做 Windows 主機。客戶端 Windows。
- D-32-04 保存期限：客戶端 3 個月自動清理；主機端永久保存，不實作任何自動刪除。
- D-32-05 SoapVoice 併入同一個安裝檔，由 ElcAgent 負責啟動與看管。
- D-32-06 不保留金鑰模式，僅區網使用。（第一期已實作。）
- D-32-07 備份採「完整一份＋每日增量」，不得輪替覆寫；備份媒體須可擴充（NAS 或可換外接磁碟）。
- D-32-08 主機端狀態頁須能提前數個月預警磁碟不足。
- 第一期（A1–A8、B1、B2、C1）已完成，僅驗證。

### Claude's Discretion
- 安裝工具選擇（Inno Setup 為計畫指定；細節可由規劃決定）。
- 系統匣與按鈕文字的具體實作（B5、B8）。
- deploy/install.sh 的步驟順序（D1）。

### Deferred Ideas (OUT OF SCOPE)
- B9 自動更新（P2）、C5 手動輸入放寬（P2）、F5 瀏覽器煙霧測試進 CI（P2）、F6 核對舊 codeimproveplan.md P0（P2）、ruff 既有 241 個 lint 錯誤清理。

### 待決（OPEN-32-01..07）：未裁示。本文件第「OPEN 項目建議」節僅為建議，規劃須以「前置決策任務」處理，不得當作已鎖定。
</user_constraints>

<phase_requirements>
## Phase Requirements

`.planning/REQUIREMENTS.md` 不存在（已驗證）；ROADMAP 的 Phase 32 需求欄為 TBD。規劃者應以 Fable5.2improvplan.md 的項目代號作為需求 ID：

| ID | 描述 | 研究支援 |
|----|------|----------|
| B3 | Inno Setup 單一安裝檔，免管理員、自動啟動 | 安裝工具節 |
| B4 | SoapVoice 併入並由 ElcAgent 看管 | OPEN-32-06、SoapVoice 現況節 |
| B5/B6/B7/B8 | 系統匣、三步精靈、免 JSON 校正、按鈕文字 | Architecture Patterns（Tk 主執行緒＋pystray） |
| B10 | 修正驗收清單設定檔名 | Pitfall 6 |
| C2/C3/C4/C6 | 探索、位址復原、health 帶院所資訊 | 探索節 |
| D1–D6 | install.sh、初次設定、狀態頁、備份、LLM 看管、保存期限 | Ubuntu 節、備份節 |
| E1–E9 | 醫師模式 | 本研究未深入（僅 UI 重構，E8 先做） |
| F1/F2/F3 | 實機驗證、一頁說明、重寫 STATE | 驗證架構節 |
</phase_requirements>

## Summary

第一期的程式層（LAN 信任、無金鑰、快捷列接進 spec）已在工作區完成但尚未提交。本 phase 的剩餘工作分成四條可平行的線：(1) Windows 客戶端安裝與看管（B3–B8、B10）；(2) 區網探索（C2–C4、C6）；(3) Ubuntu 主機一鍵安裝／狀態頁／備份（D1–D5）；(4) 保存期限與醫師介面（D6、E）。Linux 開發環境無法建置或執行 Windows 程式，所有 Windows 實機項目為外部阻塞，須與可自動化部分明確切開。

關鍵發現：(a) SoapVoice 依賴 torch、faster-whisper、ctranslate2、chromadb、sentence-transformers、llama-cpp-python 等（pyproject.toml 已確認），數 GB 等級，且其 `soapvoice.spec` 為 `console=True`、`datas` 引用 `models/`、`.env`（`SoapVoice/models` 目錄在此工作區不存在，現有 spec 無法在本機重現建置）；既有 `soapvoice.iss` 是 `PrivilegesRequired=admin`、`{pf}`，與「免管理員」衝突。(b) 現有 `installer/build_clinic_installer.py` 是 Phase 26 遺留產生器，引用不存在的 `bin/LittleB.exe`、`@webbrain/mcp-server` 與 Node，與 ElcAgent 現況不符，建議不沿用，另寫新的 `.iss`。(c) 探索建議以 stdlib UDP 廣播「請求／單播回覆」為主，不引入 zeroconf。(d) Ubuntu 主機現行 systemd 單元是 **user 單元**（`%h/.config/...`、`WantedBy=default.target`），本機已 `Linger=yes`，install.sh 應延續 user＋linger 模式。

**Primary recommendation:** 客戶端用 Inno Setup 6（`PrivilegesRequired=lowest`、`{userstartup}` 捷徑）打包 PyInstaller one-folder 的 ElcAgent；SoapVoice 以「另裝、由 ElcAgent 看管」（獨立 one-folder 子目錄、可選元件），探索用 stdlib UDP 廣播＋既有 /24 掃描退路；主機以 user systemd＋linger 的冪等 install.sh。所有 OPEN 項目先做決策任務。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 來源位址信任／CSRF | API/Backend（Flask） | — | 已在 `lan_trust.py`／`security.py` |
| 伺服器探索回應（UDP 應答） | API/Backend（獨立 daemon 執行緒） | — | 與 gunicorn 單 worker 並存，須避免多 worker 重複綁埠 |
| 探索發送／位址復原 | Windows 客戶端 | — | `discovery.py` 已有掛勾 |
| 安裝／開機自動啟動 | Windows 客戶端安裝檔 | — | Inno Setup |
| SoapVoice 看管（拉起、重啟） | ElcAgent（客戶端） | — | D-32-05 |
| 客戶端 3 個月清理 | 客戶端（ElcAgent／SoapVoice temp_cleanup） | — | D-32-04；主機端不得刪除 |
| 狀態頁／容量預警 | API/Backend | Database/Storage | 讀 `data/` 用量與歷史取樣 |
| 備份 | 主機 OS 層（systemd timer＋腳本） | NAS/外接磁碟 | 不經由 Flask |
| 醫師介面 | Browser/Client（靜態 HTML） | — | E8 拆檔先行 |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Inno Setup | 6.x（執行時需確認最新穩定版） | 產生 `ElcAgentSetup.exe` | 計畫指定；支援 `PrivilegesRequired=lowest`、`{userstartup}` [CITED: jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm]；Linux 上無原生 `iscc`，須在 Windows 或 wine 內編譯（本機有 `/usr/bin/wine`，未驗證可用） |
| PyInstaller（one-folder） | 專案既有（`scripts/build_windows_agent.py` 以 `uv run pyinstaller` 呼叫） | ElcAgent 打包 | 既有；one-folder 啟動快、免每次解壓暫存，且防毒誤報少於 one-file [ASSUMED] |
| Python stdlib `socket` | — | UDP 廣播探索 | 零新依賴、與 `discovery.py` 風格一致 |
| uv | 0.9.16（本機已裝） | 主機端依賴管理 | 使用者全域指示要求；鎖檔須加 `--no-config`（見 MEMORY：避免全域 pydantic 限制靜默降級） |
| systemd user unit＋linger | — | 主機服務 | 現行部署即此模式，本機 `Linger=yes` 已驗證 |
| `sqlite3` `.backup`／`rsync --link-dest` | OS 內建 | 備份 | D-32-07 完整＋增量、不覆寫 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pystray ＋ Pillow | 未驗證版本 | B5 系統匣 | SoapVoice pyproject 已含 pystray；ElcAgent 側是否已有須確認。Tk 佔主執行緒，pystray 用 `run_detached()` [ASSUMED] |
| zeroconf | — | mDNS | **不建議**（見探索節） |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Inno Setup | WiX／MSI | MSI 較偏機器級安裝與 GPO；本案需免管理員、單檔、腳本簡單，Inno 勝 |
| Inno Setup | NSIS | 可行，但計畫已指定 Inno，且專案內已有 `.iss` 先例 |
| Inno Setup | MSIX | 需簽章與側載設定，診所場景不適合 |
| 工作排程器自啟 | Startup 資料夾捷徑 | 免管理員下 Startup 捷徑最單純；排程器需額外權限設定 |

**Installation（開發端）:**
```bash
uv sync --no-config    # 主機/開發端；鎖檔操作一律加 --no-config
```

**Version verification:** 本 phase 新增外部套件極少（建議零新增：UDP 用 stdlib；pystray/Pillow 若尚未在 ElcAgent 依賴中才新增）。研究時未執行 slopcheck，因此 pystray／Pillow 若新增，標 `[ASSUMED]`，規劃須加 `checkpoint:human-verify`。

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| pystray | PyPI | 未查 | 未查 | 未查 | 未執行 | [ASSUMED] 規劃須 checkpoint:human-verify（SoapVoice 已使用，風險低） |
| Pillow | PyPI | 未查 | 未查 | 未查 | 未執行 | [ASSUMED] 同上（SoapVoice 已使用） |
| zeroconf | PyPI | — | — | — | 未執行 | 不建議使用，不需審核 |

**Packages removed due to slopcheck [SLOP]:** none（未執行 slopcheck，全部標 [ASSUMED]）
**Packages flagged as suspicious [SUS]:** 無資料
**備註：** 本 phase 建議不新增套件；若執行時新增，一律先過 slopcheck。

## Architecture Patterns

### System Architecture Diagram

```
[Windows 診間 PC]                              [Ubuntu Server 主機]
 ElcAgentSetup.exe (Inno, lowest)               deploy/install.sh (冪等)
   └─> %LOCALAPPDATA%\Programs\ElcAgent\           ├─ uv sync --no-config
        ElcAgent.exe (Tk 主執行緒: 快捷列)          ├─ ~/.config/elc-audit-engine/env
         ├─ HIS 輪詢 daemon thread                  ├─ systemd --user: engine / healthcheck.timer / backup.timer
         ├─ pystray 系統匣 (detached)               └─ loginctl enable-linger
         ├─ Supervisor thread ──spawn/restart──> SoapVoice\SoapVoice.exe (本機 127.0.0.1:18765, IPC token)
         └─ Discovery:
              1) last_url -> GET /api/health 比對 facility_code
              2) UDP 廣播 "ELC-DISCOVER" :5001 ──────────> UDP responder thread (主機 Flask 行程內)
                                          <──單播 JSON(url, facility_code, name, ver)──┘
              3) /24 掃描 (退路)  4) 手動輸入(最後)
         └─ HTTP (無金鑰, 來源位址信任) ─────────────> gunicorn :5000 (lan_trust 403 檢查)
                                                        └─ /api/health(深度)・狀態頁・data/
   清理: 客戶端 3 個月 + 容量上限 (OPEN-32-05)        備份: sqlite .backup + rsync --link-dest -> 外接/NAS
```

### Recommended Project Structure
```
installer/
├── elc_agent.iss            # 新：Inno 腳本（取代 build_clinic_installer.py 遺留內容）
└── build_installer.py       # 新：呼叫 PyInstaller → iscc，輸出 SHA256
deploy/
├── install.sh               # D1 冪等
├── backup.sh + elc-backup.{service,timer}
└── windows_agent/
    ├── discovery.py         # 補 udp_probe 實作
    ├── supervisor.py        # SoapVoice 看管
    └── tray.py              # B5
src/elc_audit_engine/
├── discovery_responder.py   # UDP 應答 daemon thread
└── api/routes/status.py     # D3 狀態頁／容量預測
```

### Pattern 1: UDP 廣播「請求／單播回覆」探索
**What:** 客戶端（發送方）對 `255.255.255.255` 與各介面的子網定向廣播送出固定魔術字串，伺服器 UDP 應答執行緒（綁 `0.0.0.0:5001`）單播回覆 JSON（`url`、`facility_code`、`facility_name`、`version`，不含病歷）。客戶端驗證 JSON 後再以 `/api/health` 比對 `facility_code`。
**When to use:** C2、C3。
**Why 勝過客戶端監聽廣播：** 客戶端不需綁定監聽埠，Windows 防火牆對「程式主動送出後收到回覆」的 UDP 通常放行，不會跳出「允許存取」提示（該提示在非管理員下無法按允許）[ASSUMED：Windows 防火牆有狀態 UDP 行為，須實機驗證，屬 F1 項目]。
**Example:**
```python
# 發送端（stdlib）
import socket, json
def udp_probe(port=5001, timeout=1.0, magic=b"ELC-DISCOVER/1"):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(timeout)
    for dst in ("255.255.255.255",):          # 另加各介面的子網定向廣播
        s.sendto(magic, (dst, port))
    found = []
    try:
        while True:
            data, addr = s.recvfrom(2048)
            try: found.append((addr[0], json.loads(data)))
            except ValueError: pass
    except socket.timeout:
        pass
    return found
```
`discovery.discover_server(..., udp_probe=...)` 已有掛勾，回傳 URL 清單即可（`discovery.py` L147、L172 已確認）。回覆來源位址須再通過 `validate_manual_server_url` 的私有網段檢查，且回覆內容只作「候選」，不傳任何資料。

### Pattern 2: Tk 主執行緒＋看管執行緒
快捷列佔主執行緒（`main.py` 已將 HIS 輪詢移至 daemon thread）。SoapVoice 看管以另一 daemon thread 用 `subprocess.Popen`（Windows 加 `creationflags=CREATE_NO_WINDOW`）啟動，輪詢 `proc.poll()` 與 IPC 控制埠健康（`SoapVoiceControlClient`，埠 18765 已在 `config.py`），退出後指數退避重啟（上限次數後轉為快捷列顯示「語音程式未啟動」而非無限重啟）。Windows 上客戶端結束時需終止子行程（job object 或 `taskkill /T`）[ASSUMED]。

### Anti-Patterns to Avoid
- **沿用 `installer/build_clinic_installer.py`：** 引用不存在的 `bin/LittleB.exe`、Node 套件，與現況不符。
- **mDNS 為唯一探索機制：** Ubuntu Server 預設不裝 avahi（見探索節）。
- **在 install.sh 內寫入使用者家目錄絕對路徑：** 現有 `.service` 寫死 `/home/hsu/Desktop/Elcinsurrence`，install.sh 必須以樣板產生單元檔。
- **備份用 `rsync --delete` 或輪替：** 違反 D-32-07。
- **主機端任何自動刪除：** 違反 D-32-04，容量管理只可預警。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Windows 安裝／解除安裝／開機捷徑 | 自寫安裝腳本或登錄檔操作 | Inno Setup `[Icons]` `{userstartup}`、`[UninstallDelete]` | 解除安裝與升級覆蓋由 Inno 處理 |
| SQLite 一致備份 | 直接 `cp` 資料庫檔 | `sqlite3 db ".backup 'dst'"` 或 Python `sqlite3.Connection.backup` | WAL 模式下 cp 會得到損毀快照 |
| 增量備份 | 自寫差異演算法 | `rsync -a --link-dest=<上一份>`（硬連結快照） | 每日一份完整外觀、只佔增量空間、不覆寫 |
| 磁碟預測 | 複雜時序模型 | 每日記錄 `data/` 大小到簡單表／JSON，線性回歸成長率 | 預警數個月只需線性估計 |
| 服務自動重啟 | 自寫守護行程 | systemd `Restart=always`（已有）＋既有 healthcheck.timer | 已運作 |
| CIDR 判斷 | 手寫位元運算 | `ipaddress`（已使用） | — |

**Key insight:** 本 phase 多數風險不在演算法，而在「環境差異」（Windows 防火牆、防毒、遮罩、VPN 路由），應以可設定＋可觀測（日誌、狀態頁）取代聰明的自動猜測。

## Runtime State Inventory

> 非 rename／migration phase，但有兩處既有狀態需列明（避免被安裝流程忽略）。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | 客戶端 `%LOCALAPPDATA%\ElcAgent\config.json`、校正檔、SoapVoice cycles／暫存；主機 `data/`、`config/facility.json`（有未提交的執行期修改，不提交） | 安裝／解除安裝不得刪除使用者設定與暫存（`[UninstallDelete]` 只刪程式檔） |
| Live service config | 主機 `elc-audit-engine.service` 為 user 單元，內含寫死路徑 `/home/hsu/Desktop/Elcinsurrence` | install.sh 以樣板重生單元檔 |
| OS-registered state | 客戶端開機捷徑（Startup 資料夾）；舊版 zip 部署者可能已有手動捷徑 | 安裝檔升級時需偵測並取代舊捷徑 |
| Secrets/env vars | 已無金鑰；`~/.config/elc-audit-engine/env` 內舊的 `ELC_API_KEYS` 殘留需忽略 | install.sh 不寫金鑰；舊值無害但文件應註明 |
| Build artifacts | `ElcAgent-win64.zip`、SHA256（B1 後需重建）；`SoapVoice/dist/SoapVoice.exe` 為舊建置 | 重新建置（Windows 外部阻塞） |

## Common Pitfalls

### Pitfall 1: SoapVoice 體積與打包可重現性
**What goes wrong:** 把 SoapVoice 併入同一安裝檔，安裝檔暴增到 GB 級，且 ElcAgent 每次小改版都要重發整包。
**Why:** `SoapVoice/pyproject.toml` 依賴 torch、torchaudio、faster-whisper、ctranslate2、chromadb、sentence-transformers、llama-cpp-python、scipy、funasr 等（已確認）。現有 `soapvoice.spec` 以 EXCLUDES 手動排除部分（matplotlib、scipy、torchvision…），但 `hiddenimports` 又列了 sentence_transformers、chromadb，且 `datas` 需要 `models/`（此工作區該目錄不存在，無法重現）；`console=True`、`upx=True`（upx 可能破壞 torch DLL）[ASSUMED]。`dist/SoapVoice.exe` 僅 8KB 目錄佔位，實體建置產物不在 repo。
**How to avoid:** 見 OPEN-32-06 建議：獨立元件、獨立版本、ElcAgent 看管；SoapVoice 實際在診間 PC 需要本機語音辨識或僅錄音上傳，須先釐清（若僅錄音＋上傳至主機轉錄，則客戶端不需要 torch——此為最大體積節省，**需使用者確認 SoapVoice 客戶端 `client/` 實際依賴**；`client/` 目錄只有錄音、分段、上傳、控制埠等模組，未見模型推論，建議以 `client/` 為單位另建輕量 spec）。
**Warning signs:** 安裝檔 > 500MB；建置機需要 `models/`。

### Pitfall 2: Inno `{userstartup}` 與升級時重複實例
**What goes wrong:** 升級安裝時舊版 ElcAgent 仍在執行，檔案被鎖、或開機出現兩個快捷列。
**How to avoid:** Inno `[Setup]` 設 `CloseApplications=yes`／`RestartApplications`，且 ElcAgent 啟動時以命名 Mutex 做單一實例。`PrivilegesRequired=lowest` 時 `{userstartup}` 指向安裝使用者的啟動資料夾（官方文件對此細節描述有限，本次僅從搜尋摘要得到，標 [ASSUMED]，須在 Windows 實機驗證）。
**Warning signs:** 重開機後兩個圖示；安裝提示「檔案正被使用」。

### Pitfall 3: Windows 防火牆／SmartScreen／防毒
**What goes wrong:** 未簽章 exe 觸發 SmartScreen；PyInstaller exe 常被防毒誤報；客戶端若「監聽」UDP 會跳防火牆提示，非管理員無法放行。
**How to avoid:** 客戶端只主動送出（Pattern 1）；one-folder；提供 SHA256；程式碼簽章屬採購決策（開放問題）。無法在本環境驗證。

### Pitfall 4: 網段偵測錯誤導致整間被 403（OPEN-32-01／02）
`lan_trust.detect_local_subnets` 以連向 `10.255.255.255` 取本機位址再硬編碼 /24（已確認 L28）。非 /24 或預設路由走 VPN 時，信任網段錯誤。為 fail-closed，錯誤的後果是「診間被拒」而非「外人進來」，故安全風險低、可用性風險高。

### Pitfall 5: UDP 廣播不跨網段、不跨 VLAN
定向廣播與 255.255.255.255 預設不被路由器轉發；診所若分 VLAN 則廣播探索失敗，須退回 /24 掃描（同樣不跨網段）或手動輸入。同時 D-32-01 信任範圍本來就是「伺服器所在子網」，非 /24 時兩者一致失敗——應在安裝精靈明示並提供手動輸入。

### Pitfall 5b: gunicorn 多執行緒下的 UDP 應答
gunicorn 設定為 `workers = 1`、`gthread`（已確認），UDP 應答執行緒可放在應用啟動鉤子（`post_fork` 或 app factory）。若日後增加 worker，會重複綁埠（`SO_REUSEADDR` 在 Linux UDP 下不會報錯但行為不確定）；需寫測試或註解固定 worker 數。

### Pitfall 6: B10 驗收清單檔名錯誤
`31-WINDOWS-MANUAL-VERIFY.md` 引用 `agent_settings.json`，實際為 `%LOCALAPPDATA%\ElcAgent\config.json`（`config.py` L46 已確認）。須先修正才進行 F1。

### Pitfall 7: 時間優先 vs 容量優先清理的資料遺失
見 OPEN-32-05：兩規則並存時，容量上限（2GB FIFO）可能在 3 個月內就刪掉未上傳的錄音。清理**只能刪已確認上傳到主機的資料**，否則等同遺失永久保存的病歷素材。此為建議前提，需使用者裁示。

### Pitfall 8: 備份的「不覆寫」與媒體耗盡
`rsync --link-dest` 硬連結需要目的端檔案系統支援（ext4／xfs 可；NTFS／exFAT／部分 NAS SMB 不可）。外接磁碟若為 exFAT 則無硬連結，需改用「一份完整＋每日差異資料夾」。須在 install.sh 偵測目的端檔案系統並警告。

## Code Examples

### Inno Setup 骨架（免管理員、開機自啟）
```iss
; Source: jrsoftware.org Inno Setup help（PrivilegesRequired／Icons），細節須於 Windows 實機驗證
[Setup]
AppName=ElcAgent
AppVersion={#AppVersion}
DefaultDirName={autopf}\ElcAgent
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
DisableProgramGroupPage=yes
CloseApplications=yes
OutputBaseFilename=ElcAgentSetup
Compression=lzma2

[Files]
Source: "dist\ElcAgent\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{userstartup}\ElcAgent"; Filename: "{app}\ElcAgent.exe"
Name: "{userdesktop}\醫療審核快捷列"; Filename: "{app}\ElcAgent.exe"

[Run]
Filename: "{app}\ElcAgent.exe"; Flags: nowait postinstall skipifsilent
```
注意：`{autopf}` 在 `PrivilegesRequired=lowest` 時解析為使用者層級的 `%LOCALAPPDATA%\Programs`（Inno 6 行為）[ASSUMED，須驗證]。

### 狀態頁容量預測（線性）
```python
# 每日取樣 (date, bytes_used)；以最近 N 天最小平方估成長率
def days_until_full(samples, free_bytes):
    n = len(samples)
    if n < 7: return None                       # 資料不足，不亮紅燈
    xs = list(range(n)); ys = [b for _, b in samples]
    mx, my = sum(xs)/n, sum(ys)/n
    slope = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / sum((x-mx)**2 for x in xs)
    return None if slope <= 0 else free_bytes / slope
```
門檻建議：<180 天黃、<90 天紅（D-32-08「數個月」，門檻數值屬建議，需裁示）。

### 增量備份
```bash
# 完整一份＋每日硬連結增量，絕不 --delete
TS=$(date +%F); DST="$BACKUP_ROOT/daily/$TS"
LAST=$(ls -1d "$BACKUP_ROOT"/daily/* 2>/dev/null | tail -1)
sqlite3 data/case_store.db ".backup '$STAGE/case_store.db'"   # 一致快照（檔名須以實際 DB 為準）
rsync -a ${LAST:+--link-dest="$LAST"} "$STAGE/" "$DATA_OTHERS/" "$DST/"
```

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| 金鑰＋豁免清單 | 來源位址信任＋Origin 檢查（第一期完成） | 已落地 |
| Phase 26 `build_clinic_installer.py`（LittleB／WebBrain） | 新 `.iss` 專注 ElcAgent（＋可選 SoapVoice） | 舊腳本過期，建議保留但標註棄用或移除 |
| `soapvoice.iss` admin＋`{pf}` | per-user lowest | 與免管理員需求衝突，不可沿用 |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Windows 防火牆放行「程式主動送出後收到的 UDP 單播回覆」，不跳提示 | Pattern 1 | 探索在診間失敗；退路為 /24 掃描與手動輸入 |
| A2 | `PrivilegesRequired=lowest` 下 `{userstartup}`、`{autopf}` 指向使用者層級 | 安裝節 | 開機不自啟或裝到錯誤路徑 |
| A3 | PyInstaller one-folder 比 one-file 較少防毒誤報、啟動較快 | Standard Stack | 影響發版形式，需實測 |
| A4 | SoapVoice 診間客戶端不需 torch（僅 `client/` 模組：錄音、分段、上傳） | Pitfall 1 | 若實際需要本機轉錄，體積結論改變、OPEN-32-06 建議須重審 |
| A5 | Ubuntu Server 預設不安裝／不啟用 avahi mDNS | 探索節 | mDNS 方案可行性判斷 |
| A6 | pystray 以 `run_detached()` 可與 Tk 主迴圈共存 | Pattern 2 | B5 實作須改用其他方式 |
| A7 | 備份目的端檔案系統支援硬連結（ext4/xfs） | Pitfall 8 | 改用差異資料夾 |
| A8 | 容量預警門檻 180/90 天 | 範例 | 屬使用者需裁示的數值 |
| A9 | pystray／Pillow 套件合法性（未跑 slopcheck） | Package Audit | 供應鏈風險 |

## OPEN 項目建議（僅為建議，未經使用者裁示，不得鎖定）

| ID | 建議 | 證據／理由 | 信心 |
|----|------|------------|------|
| OPEN-32-01 | **安裝／install.sh 時偵測實際遮罩（讀介面 netmask，不硬編碼 /24）並顯示給安裝人員確認；非 /24 時要求明示 `ELC_TRUSTED_SUBNETS`**。fail-closed 設計下錯誤僅導致 403，所以成本主要在現場排錯 | `lan_trust.py` 已硬編碼 /24；`ELC_TRUSTED_SUBNETS` 覆寫機制已存在；D-32-02 已要求精靈顯示信任網段 | HIGH（程式事實）/ MEDIUM（取捨） |
| OPEN-32-02 | **列舉介面（`ip -j addr`／`psutil` 或 `/proc/net`）取得有私有 IPv4 的介面，排除 tun/tap/ppp 等 VPN；單一候選自動採用，多候選由安裝人員選並寫入 `ELC_TRUSTED_SUBNETS`**（等於綁定結果，不綁網卡名稱，因網卡名稱會變動） | 現行「連 10.255.255.255 取路由」在 VPN 為預設路由時會選到 VPN 介面（7.5 #3） | MEDIUM |
| OPEN-32-03 | **採低成本：跨站 GET（`Sec-Fetch-Site: cross-site`）一律拒絕；不做診間會話／cycle 綁定**（高成本、並可與 D-32-06 精神衝突），並將剩餘風險記為已接受取捨 | `lan_trust.is_cross_site_request` 目前只套用於 `UNSAFE_METHODS`；擴充到 GET 是小改動。注意 `Sec-Fetch-Site: none`（使用者直接輸入網址）須放行，原生客戶端無此標頭須放行 | MEDIUM |
| OPEN-32-04 | **`PUT /api/soap/settings/auto-accept` 與 `/api/facility` 寫入限 loopback（伺服器本機）**，院內其他裝置改由「初次設定頁」流程（D2）在伺服器本機瀏覽器操作；不引入管理 PIN（PIN 又回到「輸入東西」，且儲存／重設流程增加複雜度） | 7.5 #5；D2 設定頁本來就是一次性；loopback 判斷已存在於 `lan_trust`。代價：遠端無法調整，需要時用 SSH 轉發或本機操作。若醫師需要在診間改 auto-accept，則須改用 PIN——此為產品決策 | MEDIUM |
| OPEN-32-05 | **「時間＋容量並存，但只刪『已確認上傳成功』的資料」**：超過 3 個月且已上傳→刪；超過容量上限時先刪已上傳最舊者；**尚未上傳者永不刪，改在快捷列／狀態頁亮警示**。若超限且全未上傳，暫停新錄音前先警告 | D-32-04 主機永久保存意味客戶端只是暫存；刪未上傳資料等同遺失；2GB 預設值來自 31-08（`temp_cache_max_mb` 預設 2048，已確認）；容量上限可改設定值而非兩套互斥規則 | MEDIUM |
| OPEN-32-06 | **「另裝、由 ElcAgent 看管」**：安裝檔提供兩個獨立 Inno 元件（ElcAgent 必選；SoapVoice 客戶端為獨立 one-folder、可選或預設勾選），共用安裝程式但版本分離；ElcAgent 負責啟動、重啟、顯示狀態，醫師仍只看到一個程式。先確認 A4（`client/` 是否可獨立成輕量 spec） | 見 Pitfall 1；依賴清單已確認；若硬併入單一 exe 會使每次 ElcAgent 發版皆重傳 GB 級 | MEDIUM（取決於 A4） |
| OPEN-32-07 | **UDP 廣播（請求／單播回覆）為主，/24 掃描為退路；不引入 mDNS**。 | 見探索節比較 | MEDIUM |

## 探索機制比較（OPEN-32-07 依據）

| 面向 | UDP 廣播（stdlib） | mDNS（zeroconf） |
|------|-------------------|------------------|
| 新依賴 | 無 | zeroconf（第三方；PyInstaller 打包需處理 hiddenimports，[ASSUMED]） |
| 主機端 | 應用內 daemon thread，install.sh 無額外套件 | Ubuntu Server 通常需另裝並啟用 avahi-daemon，或應用內再用 zeroconf 註冊 [ASSUMED] |
| Windows 客戶端 | 主動送出，單播回覆 | Windows 10+ 內建 mDNS 解析 `.local`，但 Python 端用 zeroconf 需綁 UDP 5353 與加入多播群組，可能觸發防火牆提示、多網卡（VPN／Hyper-V 虛擬網卡）時介面選擇易錯 [ASSUMED] |
| 跨 VLAN／AP 隔離 | 失敗（需退路） | 同樣失敗（多播多半不跨網段；部分 AP 擋多播） |
| 位址復原（C3） | 好：回覆直接帶 URL＋facility_code | 需解析主機名再 GET health |
| 失敗模式 | 防火牆擋入站、廣播被 AP 過濾；皆有 /24 掃描與手動輸入退路 | 同上，並加 avahi 未裝、`.local` 解析遇 VPN 的 DNS 後綴路由問題 |

結論：UDP 單一機制已足夠；mDNS 的額外收益（醫師可用 `elc-server.local` 開網頁）可留作選配，不應阻塞 phase。注意計畫 C2 原文寫「mDNS＋UDP」，如採本建議需使用者同意修改 C2 範圍。

## Ubuntu Server install.sh 限制（D1）

- 現況：`deploy/elc-audit-engine.service` 為 **user 單元**（`EnvironmentFile=%h/.config/elc-audit-engine/env`、`WantedBy=default.target`）；本機 `loginctl show-user` 已 `Linger=yes`。install.sh 應 `loginctl enable-linger "$USER"`（需 sudo 或 polkit，冪等）。
- 單元檔內寫死 `/home/hsu/Desktop/Elcinsurrence` 與 `.venv`，須以 `sed`／樣板用 `$ROOT` 產生到 `~/.config/systemd/user/`，再 `systemctl --user daemon-reload && enable --now`。
- Ubuntu Server 無桌面：`XDG_RUNTIME_DIR` 在 SSH 中可能未設，`systemctl --user` 失敗；腳本須檢查並提示 `export XDG_RUNTIME_DIR=/run/user/$(id -u)`。
- 綁定埠 5000 >1024，不需 root。`ELC_SERVER_HOST=0.0.0.0` 才對區網開放（`gunicorn.conf.py` 預設 127.0.0.1，已確認）——install.sh 預設應寫入 0.0.0.0，並同時列印信任網段（呼應 D-32-02）。
- uv：本機 0.9.16 存在；腳本若找不到 `uv`，提示官方安裝方式而非自動 `curl | sh`（安全）。鎖檔／同步一律 `--no-config`（使用者記憶：全域 pydantic 限制會靜默降級）。
- 防火牆：Ubuntu 預設 ufw 停用；若啟用，需開 5000/tcp 與探索用 5001/udp，並限制來源為信任網段。
- 冪等：重複執行不得覆蓋使用者 env；僅補缺項。
- 備份計時器同為 user timer，linger 下可運作。
- 無法在 Linux 開發機驗證「全新 Ubuntu Server」流程，只能以 `bash -n`、shellcheck、與容器／VM（若可用）驗證——標為外部驗證項目。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | install.sh、測試 | ✓ | 0.9.16 | — |
| python3 | 測試 | ✓ | （uv 管理） | — |
| wine | 嘗試在 Linux 編譯 Inno／PyInstaller | ✓ | 已安裝（版本未查；能否跑 iscc／PyInstaller 未驗證） | Windows 建置機 |
| Inno Setup (iscc) | B3 | ✗（Linux 上無原生） | — | Windows 建置機或 wine（未驗證） |
| Windows 10/11 實機 | F1、B3–B8 驗證 | ✗ | — | **無；外部阻塞** |
| zeroconf | 不需要 | ✗ | — | — |
| shellcheck | install.sh 靜態檢查 | 未查 | — | `bash -n` |
| systemd user／linger | 主機 | ✓ | `Linger=yes` | — |

**Missing with no fallback:** Windows 10/11 實機（建置、安裝、UIA＋Tk 共存、防火牆、開機自啟、SmartScreen 全部無法在本環境驗證）。
**Missing with fallback:** Inno 編譯器（Windows 建置機）。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest（既有；`tests/` 1536 passed、`doc/tests` 138 passed 為第一期基準） |
| Config file | 既有 pytest 設定（`tests/conftest.py`）；本研究未再確認 pyproject 設定細節 |
| Quick run command | `uv run --no-config pytest tests/test_agent_discovery.py tests/test_lan_trust.py -q`（需確認 `--no-config` 是否適用於 `uv run`） |
| Full suite command | `uv run --no-config pytest tests doc/tests -q`（勿用 `-x`，會誤報；見 7.2） |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| C2 | UDP 應答執行緒收到魔術字串回 JSON；錯誤字串忽略；回覆不含病歷 | unit/integration（本機 loopback socket） | `pytest tests/test_discovery_responder.py -q` | ❌ Wave 0 |
| C2 | `udp_probe` 結果接入 `discover_server`、私有位址過濾 | unit | `pytest tests/test_agent_discovery.py -q` | ✅（需擴充） |
| C3 | 記住位址失效→重探索→`facility_code` 相符才更新 | unit（假 probe） | 同上 | ❌ Wave 0 |
| C4 | `/api/health` 含院所名稱／版本、不含病歷、院外 403 | API | `pytest tests/test_lan_trust_api.py -q` | ✅（擴充） |
| OPEN-01/02 | 子網偵測：多介面、VPN 介面排除、非 /24 遮罩（以假介面清單注入） | unit | `pytest tests/test_lan_trust.py -q` | ✅（擴充） |
| OPEN-03/04 | 跨站 GET 拒絕、設定寫入限 loopback（若採建議） | API | `pytest tests/test_lan_trust_api.py -q` | ✅（擴充） |
| D1 | install.sh 語法／冪等（dry-run 模式、樣板渲染單元檔路徑） | shell | `bash -n deploy/install.sh`；`pytest tests/test_install_script.py`（渲染函式） | ❌ Wave 0 |
| D3 | 容量預測函式（資料不足、成長為零、正常） | unit | `pytest tests/test_capacity_forecast.py -q` | ❌ Wave 0 |
| D4 | 備份腳本在暫存目錄：產生完整＋第二日增量、舊份不被改動、SQLite 備份可開啟 | shell／pytest tmpdir | `pytest tests/test_backup_script.py -q` | ❌ Wave 0 |
| D5 | LLM 停止→狀態為「AI 暫停」、其餘端點正常 | API（mock LLM 探測） | `pytest tests/test_status_api.py -q` | ❌ Wave 0 |
| D6 | 客戶端清理：>3 個月且已上傳→刪；未上傳不刪；超容量只刪已上傳最舊；主機端無任何刪除路徑（grep 型測試） | unit | `pytest SoapVoice/tests/...`（SoapVoice 為獨立 repo 測試，位置需確認） | ❌ Wave 0 |
| B4 | Supervisor：子行程退出→退避重啟；超過上限停止；結束時終止子行程（以假 `Popen` 注入） | unit | `pytest tests/test_agent_supervisor.py -q` | ❌ Wave 0 |
| B5/B8 | 系統匣選單項目、按鈕文字／禁用狀態（無需顯示的邏輯層） | unit | `pytest tests/test_agent_bar_launch.py -q` | ✅（擴充） |
| B3 | `.iss` 靜態檢查：含 `PrivilegesRequired=lowest`、`{userstartup}`、無 `{commonstartup}` | unit（文字） | `pytest tests/test_installer_script.py -q` | ❌ Wave 0 |
| B10 | 驗收清單不含 `agent_settings.json` | unit（grep） | 同上 | ❌ Wave 0 |
| E 全部 | 純靜態 HTML／JS 修改 | 靜態檢查＋人工（F5 煙霧測試已延後） | — | 部分人工 |

### 外部阻塞（需 Windows 實機，無法在 CI／本環境自動化）
1. PyInstaller one-folder 實際建置、SHA256、`ElcAgentSetup.exe` 編譯與乾淨 Win10/11 安裝。
2. 免管理員安裝、開機自啟（`{userstartup}`）、重開機後快捷列出現、升級時單一實例。
3. UIA＋Tk 共存（7.4 風險）、HIS 校正（B7 擷取控制項）。
4. UDP 廣播於 Windows 防火牆實際行為（A1）、SmartScreen／防毒誤報。
5. Phase 31 的 8 項人工驗證＋30-09 探針（F1，B10 修正後才有意義）。
6. 乾淨 Ubuntu Server 全新安裝 install.sh（無此環境，需 VM）。
7. 訪客 Wi-Fi 實際隔離（現場網路）。

### Sampling Rate
- **Per task commit:** 受影響測試檔（quick run）
- **Per wave merge:** `uv run --no-config pytest tests doc/tests -q`（基準 1536＋138 passed，不得回退；ruff 錯誤數不得超過 241）
- **Phase gate:** 全綠＋外部阻塞清單逐項標為「已實機確認／待確認」，再 `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_discovery_responder.py`、`tests/test_agent_supervisor.py`、`tests/test_capacity_forecast.py`、`tests/test_backup_script.py`、`tests/test_install_script.py`、`tests/test_installer_script.py`、`tests/test_status_api.py`
- [ ] 介面列舉的可注入抽象（讓 OPEN-01/02 可單元測試，不依賴真實網卡）
- [ ] 第一期未提交改動需先 commit（目前工作區 `M`/`??` 眾多，phase 32 測試基準依賴它）

## Security Domain

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no（D-32-06 無金鑰） | 來源位址信任（既有） |
| V3 Session Management | no | — |
| V4 Access Control | yes | `lan_trust`（子網／loopback）；OPEN-32-04 設定寫入限 loopback |
| V5 Input Validation | yes | UDP 探索回覆視為不可信：長度上限、JSON 解析容錯、位址須私有網段；`ELC_TRUSTED_SUBNETS` 解析失敗 fail-fast（既有） |
| V6 Cryptography | no（內網 HTTP，已知取捨）；備份若加密需用成熟工具（如 age／gpg），不自寫 |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 偽造探索回覆（同網段惡意裝置冒充伺服器） | Spoofing | 客戶端以 `/api/health` 比對 `facility_code`；首次連線在精靈顯示院所名稱由醫師按「是」（B6）；探索階段不傳任何資料（既有規則） |
| 探索埠被放大利用 | DoS | 回覆小於請求兩倍或限制速率；只回 JSON 小封包 |
| DNS rebinding／跨站請求 | Tampering | `is_allowed_host`、`is_cross_site_request`（既有）；OPEN-32-03 擴及 GET |
| 帶 XFF 的反向代理旁路 | Spoofing | 已 fail-closed（既有） |
| 備份目的端含病歷 | Info disclosure | 目錄權限 0700；外接磁碟遺失風險須告知（屬政策決策） |
| 安裝檔被竄改 | Tampering | SHA256 公布於內部；簽章為開放問題 |
| 安裝腳本下載執行 | Tampering | install.sh 不自動 `curl | sh` |

## Open Questions

1. **SoapVoice 診間端是否需要本機推論？**
   - 已知：`client/` 模組僅見錄音、分段、上傳、IPC 控制；`pyproject.toml` 卻含 torch 等重依賴；`soapvoice.spec` 入口為 `src/gui/desktop_app.py`（含 whisper），不是 `client/`。
   - 不清楚：實際部署在診間 PC 的是哪個入口。
   - 建議：規劃第一個任務為「確認入口與依賴」，決定 OPEN-32-06。
2. **是否購買程式碼簽章憑證？** 影響 SmartScreen；屬採購決策，建議 phase 內不阻塞，文件記載「點選更多資訊→仍要執行」。
3. **備份媒體實際種類與檔案系統？** 決定是否可用硬連結（Pitfall 8）。
4. **C2 範圍是否同意由「mDNS＋UDP」縮為「僅 UDP」？**（OPEN-32-07）
5. **`REQUIREMENTS.md` 不存在，ROADMAP Phase 32 需求為 TBD**：需由規劃者以 B/C/D/E/F 代號建立需求映射。
6. **E（醫師模式）範圍極大**：計畫原定為第四期；本 phase CONTEXT 範圍含「醫師介面」，建議規劃時拆為至少兩個子批次（E8 拆檔先行），否則單一 phase 過大。

## Sources

### Primary（已讀取，HIGH）
- 專案原始碼：`deploy/windows_agent/discovery.py`、`config.py`、`src/elc_audit_engine/lan_trust.py`、`deploy/*.service`、`healthcheck.sh`、`gunicorn.conf.py`、`installer/build_clinic_installer.py`、`SoapVoice/soapvoice.spec`、`SoapVoice/pyproject.toml`、`SoapVoice/installer/soapvoice.iss`
- `Fable5.2improvplan.md` 第三、五、七節；`32-CONTEXT.md`
- Phase 31 計畫 31-08（`temp_cache_max_mb` 預設 2048）

### Secondary（MEDIUM）
- Inno Setup 官方說明 PrivilegesRequired：https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm（僅由搜尋摘要取得；`{userstartup}`／`{autopf}` 在 lowest 下的行為未直接核對官方頁，標 [ASSUMED]）

### Tertiary（LOW，未驗證）
- Windows 防火牆 UDP、zeroconf／avahi、pystray、PyInstaller 防毒行為：訓練知識，標 [ASSUMED]；本次 Context7／官方文件查詢未執行（環境與時間），規劃者應在對應任務前補查。

## Metadata

**Confidence breakdown:**
- Standard stack：MEDIUM — 工具選擇合理但 Windows 行為未實測、套件未跑 slopcheck
- Architecture：MEDIUM — 對應既有程式的掛勾已確認，Windows 行為待實機
- Pitfalls：MEDIUM — 程式相關為 HIGH，Windows／防毒為 LOW
- OPEN 建議：MEDIUM，全部為建議

**Research date:** 2026-11-14
**Valid until:** 2026-12-14（Inno／Windows 行為相對穩定；專案現況以 git 狀態為準）
