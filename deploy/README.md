# 服務部署與維運指南（elc-audit-engine）

本目錄提供主機正式部署所需之自動化腳本、systemd 樣板與設定檔：

| 檔案 / 目錄 | 用途 |
|---|---|
| `install.sh` | Ubuntu Server 一鍵安裝腳本（自動安裝依賴、渲染單元檔、啟用服務與計時器） |
| `gunicorn.conf.py` | 正式 WSGI 伺服器設定（1 個 worker + 多執行緒，支援 SQLite 併發） |
| `elc-audit-engine.service` | systemd 服務樣板（`@ROOT@` 由 `install.sh` 自動代入） |
| `healthcheck.sh` | 健康檢查腳本：探測 `/api/health`（連續失敗重啟）與 `/api/health/deep` 深度記錄 |
| `elc-audit-engine-healthcheck.{service,timer}` | 每分鐘執行一次健康檢查 |
| `backup.sh`、`elc-backup.{service,timer}` | D4 每日 02:30 自動增量備份至 exFAT 媒體 |
| `elc-audit-engine.env.example` | 環境變數範本（實際設定檔位於 `~/.config/elc-audit-engine/env`，權限 600） |

> **注意**：本目錄下之 `.service` 與 `.timer` 檔案均為樣板檔（內含 `@ROOT@` 佔位符），請一律透過 `install.sh` 進行安裝與渲染，請勿直接手動複製。

---

## 一、主機安裝（一個指令）

在剛安裝完成之 Ubuntu Server 上，進入專案目錄並執行一鍵安裝腳本：

```bash
bash deploy/install.sh
```

此腳本將自動依序完成：
1. 檢查作業系統環境、`uv` 套件管理工具與 Python 3.12。
2. 執行 `uv sync --no-config` 建立虛擬環境並安裝相依套件。
3. 建立 `data/` 與 `logs/` 目錄。
4. 偵測主機實體網路介面與網段，設定院內信任網段（`ELC_TRUSTED_SUBNETS`）。
5. 提示外接備份媒體掛載點（支援 exFAT），寫入 `ELC_BACKUP_ROOT`。
6. 將 systemd 服務與計時器樣板渲染並安裝至 `~/.config/systemd/user/`，自動執行 `daemon-reload` 與 `enable --now`。
7. 提示設定使用者 linger（登出後服務持續常駐）與 UFW 防火牆規則。
8. 檢查主機 IP 是否由 DHCP 分配，並提供固定 IP 設定建議與後續網址。

若需無人值守或預設安裝，可加上 `--yes`（非互動）或 `--dry-run`（僅模擬）：
```bash
bash deploy/install.sh --yes
```

---

## 二、網頁初次設定（/setup）

主機安裝完成後，無需手動編輯任何 JSON 設定檔。請直接在瀏覽器開啟：

👉 **`http://<主機IP>:5000/setup`**

一頁式表單填寫：
1. **健保特約院所代碼**（10 位數字）
2. **醫療院所名稱**
3. **負責醫師姓名**（選填）
4. **診間清單**（可新增多個診間代號與顯示名稱，供診間快捷列下拉選擇）

設定送出後會原子寫入 `config/facility.json`。完成後即可直接進入審查工作台。

> **安全限制**：初次設定頁面之寫入權限僅限伺服器本機（`127.0.0.1`）；若從其他診間電腦開啟，頁面將自動以唯讀模式顯示並提示需至主機本機進行設定。

---

## 三、系統狀態監控（/status）

隨時可透過瀏覽器檢視伺服器即時運作狀態：

👉 **`http://<主機IP>:5000/status`**

狀態頁即時顯示 6 項核心指標：
- **審查引擎**：核心 API 與進程存活。
- **LLM 推論服務**：本機推論引擎連線。
- **磁碟空間與成長預警**：依每日新增資料量推估剩餘容量天數（Runway，黃燈 180 天、紅燈 90 天）。
- **資料庫**：SQLite 讀寫正常。
- **資料備份**：上次成功備份時間與媒體剩餘空間。
- **各診間連線**：即時在線之診間工作站數量。

---

## 四、資料備份（D4：exFAT 媒體、只增不刪、雜湊驗證）

本系統遵循「主機端病歷永久保存」原則，備份採**完整一份＋每日增量**，**只增不刪**：

- **排程時間**：每日凌晨 02:30 由 `elc-backup.timer` 自動執行 `deploy/backup.sh`（開機後錯過自動補跑）。
- **支援媒體**：相容 exFAT 外接隨身硬碟與 NAS，不依賴 Linux 硬連結或特殊權限。
- **資料目錄結構**：
  - `elc-backup/full/`：首次完整備份快照。
  - `elc-backup/incr/<時間戳記>/`：每日僅複製新增或變更之檔案。
  - `elc-backup/manifests/<時間戳記>.json`：該時點完整檔案目錄清單與雜湊值。
- **一致性快照與校驗**：SQLite 資料庫透過 `.backup` API 取得一致性快照；每個檔案複製完成後以 SHA-256 進行來源雜湊比對，確保資料絕對完整。
- **災難還原**：根據最新一份 `manifests/<時間戳記>.json`，將每個檔案依其記錄之 `location` 指標還原至 `data/` 目錄即可完整復原該時點之所有資料庫與附件。

---

## 五、區域網路信任模式（院內免驗證）

存取控制以**請求來源位址**判定：
- loopback（本機）與院內信任網段 → 放行，不需金鑰。
- 非信任來源 → 一律回應 `403`。

### ⚠️ 安全維護要點
1. **訪客 Wi-Fi 必須與診間網段實體或 VLAN 隔離**。
2. **防火牆限制來源**：
   ```bash
   sudo ufw allow from 192.168.1.0/24 to any port 5000 proto tcp
   sudo ufw allow from 192.168.1.0/24 to any port 5002 proto udp
   ```
3. **切勿將 5000 埠對外發佈至網際網路**。
4. **跨站防護**：系統內建 CSRF 與跨站 GET 阻斷（帶有 `Sec-Fetch-Site: cross-site` 一律拒絕 403），防範惡意網頁攻擊。

---

## 六、常見問題與排錯

### 1. SSH 登入後提示 `XDG_RUNTIME_DIR` 未設定
執行以下指令載入 runtime 環境變數：
```bash
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
```

### 2. 登出 SSH 後服務停止
啟用使用者 linger 功能，讓登出後 systemd user 服務持續執行：
```bash
sudo loginctl enable-linger "$USER"
```

### 3. 診間開啟網頁出現 403 拒絕
請檢查 `~/.config/elc-audit-engine/env` 中的 `ELC_TRUSTED_SUBNETS`：
```bash
# 查看伺服器辨識的網路介面與網段
python3 -m elc_audit_engine.lan_trust --describe
# 編輯環境檔加入診間所在網段（以逗號分隔）
nano ~/.config/elc-audit-engine/env
# 範例：ELC_TRUSTED_SUBNETS=192.168.1.0/24,192.168.2.0/24
systemctl --user restart elc-audit-engine.service
```

### 4. 服務狀態與日誌查詢
```bash
systemctl --user status elc-audit-engine.service
journalctl --user -u elc-audit-engine.service -f
cat logs/crash.log        # 崩潰原因紀錄
cat logs/healthcheck.log  # 健康檢查日誌
cat logs/backup-status.json # 備份最新狀態
```
