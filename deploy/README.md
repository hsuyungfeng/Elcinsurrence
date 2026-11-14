# 服務部署與穩定性（elc-audit-engine）

本目錄提供正式部署所需檔案：

| 檔案 | 用途 |
|---|---|
| `gunicorn.conf.py` | 正式 WSGI 伺服器設定（取代 Flask 開發伺服器） |
| `elc-audit-engine.service` | systemd 使用者服務：崩潰自動重啟、每次停止寫入 `logs/crash.log` |
| `healthcheck.sh` | 探測 `/api/health`，連續 3 次失敗即重啟服務，記錄至 `logs/healthcheck.log` |
| `elc-audit-engine-healthcheck.{service,timer}` | 每分鐘執行一次健康檢查 |
| `elc-audit-engine.env.example` | 環境變數範本（實際檔放在 `~/.config/elc-audit-engine/env`，權限 600） |

## 一、安裝（需由使用者在終端執行）

```bash
mkdir -p ~/.config/elc-audit-engine ~/.config/systemd/user
cp deploy/elc-audit-engine.env.example ~/.config/elc-audit-engine/env
chmod 600 ~/.config/elc-audit-engine/env        # 編輯並換成強隨機金鑰
cp deploy/elc-audit-engine.service deploy/elc-audit-engine-healthcheck.service \
   deploy/elc-audit-engine-healthcheck.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now elc-audit-engine.service elc-audit-engine-healthcheck.timer

# 開機後不登入也要保持運作（需要一次 sudo）
sudo loginctl enable-linger "$USER"
```

## 二、日常操作

```bash
systemctl --user status elc-audit-engine.service
systemctl --user restart elc-audit-engine.service
journalctl --user -u elc-audit-engine.service -f     # 即時日誌
cat logs/crash.log        # 每次服務停止的時間與退出碼（崩潰原因線索）
cat logs/error.log        # gunicorn 錯誤與 Python 例外堆疊
cat logs/healthcheck.log  # 健康檢查失敗與自動重啟紀錄
```

健康端點：`curl http://127.0.0.1:5000/api/health` 回傳 `{"status":"ok"}`。

## 三、區域網路（LAN）部署：院內免驗證模式

**設計前提（使用者裁示 2026-11-13）**：本系統僅供診所區域網路使用，醫師不應被要求輸入任何金鑰。存取控制以**請求來源位址**判定：

- loopback 與院內網段 → 放行，不需金鑰。
- 其他來源 → 一律 `403`（不是降級成要求金鑰）。

### 必要設定

1. **綁定對外網卡**：`ELC_SERVER_HOST=0.0.0.0`，診間電腦才連得進來。
2. **信任網段**：預設自動取伺服器所在介面的 `/24` 子網，通常無需設定。遮罩非 `/24` 或需信任多個網段時，以 `ELC_TRUSTED_SUBNETS=192.168.1.0/24,10.0.5.0/24` 明示。
3. **確認信任範圍**：服務啟動時會在日誌印出「院內信任模式：信任來源 …」，請核對是否與預期相符。

### ⚠️ 免驗證模式的安全邊界

金鑰移除後，**院內網路本身就是安全邊界**。請務必確認：

1. **訪客 Wi-Fi 必須與診間網段隔離**。否則候診區的任何手機都能讀取病歷。（已確認：本院為不同網段。）
2. **防火牆限制來源**：`sudo ufw allow from 192.168.1.0/24 to any port 5000`，並拒絕其他來源。信任網段判定是應用層防線，防火牆是第一層。
3. **不要把 5000 埠轉發到網際網路**。沒有金鑰保護時，對外曝露等同公開病歷。

程式已內建的兩道配套防護（無需設定）：

- **跨站寫入防護**：醫師瀏覽到惡意網頁時，該網頁可從院內位址對本服務發出寫入請求。所有 `POST`／`PUT`／`PATCH`／`DELETE` 會檢查 `Origin`／`Sec-Fetch-Site`，跨站一律拒絕。原生客戶端不帶這些標頭，不受影響。
- **DNS rebinding 防護**：`Host` 標頭須為私有 IP 字面值、`localhost` 或 `*.local`；攻擊者網域不符此形式。此項保護 `GET` 讀取路徑（不在跨站寫入檢查範圍內）。

### 其他

- **備份**：`data/`（案件資料庫、上傳檔、錄音）與 `logs/` 需定期備份。**主機端病歷永久保存**（使用者裁示），故備份採「完整一份＋每日增量」，不得使用會覆蓋舊備份的輪替策略；備份媒體需可擴充（NAS 或可換的外接磁碟）。
- **審計軌跡仍然保留**：免驗證不等於免紀錄。每次病歷存取都會寫入 `data/audit/access.log`，`caller_id` 記為 `lan:<來源 IP>`。
- **單一 worker 是刻意設計**：CaseStore 使用 SQLite，多程序寫入會有鎖競爭，因此採「1 個 worker + 多執行緒」。
- **TLS**：院內網段若需加密傳輸，可在前方加反向代理（Caddy／Nginx）負責 TLS 並轉發至 `127.0.0.1:5000`；此時信任網段應改為代理主機位址。

## 四、已知限制

- `gunicorn` 只負責 HTTP；LLM 服務（本機 llama-server／vLLM）若停止，審核功能會失敗但服務本身仍存活，需另行監控。
- 健康檢查只探測服務本身；若磁碟滿或 SQLite 鎖死，`/api/health` 可能仍回 200，建議另加磁碟用量監控。
