# 分步部署說明：主機（Local Server）與 Windows 診間端

> 本文件依序說明如何部署 **主機（Ubuntu 伺服器）** 與 **Windows 診間端（ElcAgent）**。
> 較完整的背景、FAQ 與安全說明見 `CLINIC_DEPLOYMENT_GUIDE.md`；醫師一頁式指引見 `CLINIC_QUICKSTART_DOCTOR.md`。

---

## 0. 先決條件與共用資訊

| 項目 | 需求 |
|---|---|
| 主機 | Ubuntu 22.04 或 24.04 LTS，有 `sudo` 權限 |
| 診間電腦 | Windows 10 / 11 64 位元，與主機位於同一院內網段 |
| 網路 | 所有電腦在同一區域網路；主機有固定 IP（建議在分享器做 DHCP 綁定） |
| 網段範例 | 本文以 `192.168.68.0/24` 為例，請換成你院內的實際網段 |

**連接埠（請勿改動）**

| 用途 | 協定 | 連接埠 |
|---|---|---|
| Web 服務 | TCP | `5000` |
| 診間自動探索回應 | UDP | `5002` |

---

## 第一部分：主機（Local Server）

### 步驟 1：安裝基本工具

```bash
sudo apt update
sudo apt install -y git curl
# 安裝 uv（Python 套件管理器）
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc   # 讓 uv 在目前終端機生效
uv --version       # 應顯示版本號
```

### 步驟 2：取得程式碼

```bash
cd ~
git clone https://github.com/hsuyungfeng/Elcinsurrence.git
cd Elcinsurrence
git checkout main
git log --oneline -1   # 確認為最新提交
```

### 步驟 3：建立院所設定檔

院所資料**不進版本控制**。以範本為基礎建立本機檔案：

```bash
cp config/facility.example.json config/facility.json
nano config/facility.json   # 填入 code（院所代碼）、name、physician_name、address、email
```

> `config/facility.json` 已在 `.gitignore` 中，不會被提交。

### 步驟 4：先做演練（不會改動系統）

```bash
bash deploy/install.sh --dry-run
```

檢查輸出：應看到「偵測到本機網段」與「安裝完成」字樣。這一步不會寫入設定、不會啟動服務。

### 步驟 5：正式安裝

```bash
bash deploy/install.sh
```

安裝過程會依序：
1. 同步套件（`uv sync`）並建立環境檔 `~/.config/elc-audit-engine/env`。
2. **偵測院內網段並要求你確認**。畫面會顯示例如 `192.168.68.0/24`，輸入 `y` 才會寫入信任網段；輸入其他內容會取消安裝。
3. 詢問備份硬碟路徑（可直接按 Enter 略過，日後再設定 `ELC_BACKUP_ROOT`）。
4. 安裝並啟動 systemd 服務 `elc-audit-engine.service`，以及健康檢查與備份計時器。
5. 嘗試啟用 Linger（讓服務開機即啟動）。若提示權限不足，依畫面指示執行 `sudo loginctl enable-linger $USER`。
6. 印出防火牆指令與總結。

> 若偵測到多個不同網段，安裝會**報錯停止**，請在環境檔加入 `ELC_TRUSTED_SUBNETS=<你的網段>` 後重新執行。

### 步驟 6：確認服務設定

```bash
nano ~/.config/elc-audit-engine/env
```

確認以下項目（LAN 服務需要）：

```
ELC_SERVER_HOST=0.0.0.0        # 院內其他電腦才能連入
ELC_TRUSTED_SUBNETS=192.168.68.0/24   # 你的院內網段
```

修改後重新啟動：

```bash
systemctl --user restart elc-audit-engine.service
```

### 步驟 7：驗證服務

```bash
systemctl --user status elc-audit-engine.service    # 應為 active (running)
curl -s http://127.0.0.1:5000/api/health            # 應回傳 status ok
```

### 步驟 8：設定防火墙（僅允許院內網段）

> 防火墙指令需要 root 權限，請你自己在終端機執行。**先放行 SSH，避免啟用後連不上主機。**

```bash
sudo ufw allow ssh
sudo ufw allow from 192.168.68.0/24 to any port 5000 proto tcp
sudo ufw allow from 192.168.68.0/24 to any port 5002 proto udp
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw enable
sudo ufw status verbose
```

> 將 `192.168.68.0/24` 換成你的院內網段（與步驟 5 確認的網段一致）。
> ⚠️ 若先前已設定過 `18766/udp` 的規則，那是錯誤的埠號，請改為 `5002/udp`，並可刪除舊規則：`sudo ufw delete allow 18766/udp`。

### 步驟 9：從診間電腦驗證

在任一診間電腦的瀏覽器開啟：

```
http://<主機 IP>:5000/
```

能看到審查工作台即表示主機部署完成。若無法開啟，請檢查防火墙（步驟 8）與網段（步驟 5、6）。

---

## 第二部分：Windows 診間端（ElcAgent）

### 步驟 1：取得安裝檔並核對雜湊

取得 `ElcAgentSetup.exe`，並比對 SHA-256 雜湊（與發布包中 `SHA256SUMS.txt` 一致）：

```powershell
Get-FileHash .\ElcAgentSetup.exe -Algorithm SHA256
```

> 雜湊不一致請勿安裝，改由維護人員重新提供。

### 步驟 2：執行安裝檔

1. 雙擊 `ElcAgentSetup.exe`。
2. 若出現 Windows SmartScreen 藍色警告（本系統未購買程式碼簽章憑證，見 D-32-10）：
   - 點選「其他資訊」。
   - 點選「仍要執行」。
3. 依畫面完成安裝（免系統管理員權限，會設定開機啟動，並一併安裝 SoapVoice 客戶端）。

### 步驟 3：首次啟動三步精靈

安裝完成後，ElcAgent 會自動開啟首次啟動精靈，流程為：

1. 按 **是**（確認自動找到的伺服器）。
2. 按 **下一步**。
3. 按 **完成**。

精靈透過 UDP `5002` 自動探索主機，醫師不需要輸入位址或金鑰。

### 步驟 4：確認常駐與連線

- 工作列右下角應出現 ElcAgent 系統匣圖示（背景常駐）。
- 以瀏覽器開啟 `http://<主機 IP>:5000/status`，查看系統狀態頁（實際顯示內容以畫面為準；本步驟未逐項實測）。
- SoapVoice 客戶端由 ElcAgent 看管；斷線會自動重新啟動。

### 步驟 5：若精靈找不到伺服器

依序檢查：
1. 診間電腦與主機是否在同一網段（`ipconfig` 查看 IPv4 位址）。
2. 主機防火墙是否放行 UDP `5002`（主機步驟 8）。
3. 主機服務是否執行中（主機步驟 7）。

仍無法解決，請參考 `CLINIC_DEPLOYMENT_GUIDE.md` 第四節 FAQ。

---

## 附錄：維護人員建置 Windows 安裝檔（非診間人員）

若需由原始碼重新建置 `ElcAgentSetup.exe`，請依發布包 `deploy/release-20261116/BUILD-WINDOWS.md` 的完整步驟，在 Windows 機器上進行（PyInstaller 無法在 Linux 產出 `.exe`）。

---

## 驗收狀態（請如實標示）

| 項目 | 狀態 |
|---|---|
| 主機 `install.sh` 於乾淨 Ubuntu 上的完整安裝 | **未實測**（僅完成 `--dry-run`，需乾淨 VM） |
| 主機服務健康檢查與院內存取 | 已於正式主機實測（回環與 Win11 測試機皆 200） |
| ElcAgent 建置與 `--selftest` | 已於 Win11 測試機實測（退出碼 0） |
| `ElcAgentSetup.exe` 安裝與首次啟動精靈 | **未實測**（安裝檔已編譯，尚未在診間機安裝） |
| 12 項 Windows 實機人工驗收 | **未完成**（見 `驗收結果.md`） |
