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

## 三、區域網路（LAN）部署建議

目前預設只監聽 `127.0.0.1`，僅本機可連。若要讓同一網段的其他電腦使用，建議：

1. **不要直接對外開放 gunicorn**：保持 `ELC_SERVER_HOST=127.0.0.1`，前面加一層反向代理（Caddy 或 Nginx）負責 TLS 加密，代理轉發至 `127.0.0.1:5000`。病患資料在網路上傳輸必須加密。
2. **設定 Host 白名單**：`ELC_ALLOWED_HOSTS` 填入伺服器的 LAN 主機名稱或 IP（不含埠號），例如 `elc-server.lan,192.168.1.50`。未在白名單的 Host 會被拒絕（防 DNS rebinding）。
3. **每個使用者／用戶端一組金鑰**：`ELC_API_KEYS=clinic:金鑰1,reviewer:金鑰2`，金鑰以強隨機產生，定期輪替，且只放在 600 權限的環境檔中。
4. **確認沒有認證旁路**：`security.py` 有 `DISABLE_AUTH=1` 的測試用旁路，正式環境必須確保未設定此變數。
5. **防火牆限制來源**：例如 `sudo ufw allow from 192.168.1.0/24 to any port 443`，只允許內網網段連入，且不開放 5000 埠。
6. **備份**：`data/`（案件資料庫、上傳檔）與 `logs/` 需定期備份；`data/` 含病患相關資料，儲存與傳輸皆須符合醫療資料保護規範。
7. **單一 worker 是刻意設計**：CaseStore 使用 SQLite，多程序寫入會有鎖競爭，因此採「1 個 worker + 多執行緒」。

## 四、已知限制

- `gunicorn` 只負責 HTTP；LLM 服務（本機 llama-server／vLLM）若停止，審核功能會失敗但服務本身仍存活，需另行監控。
- 健康檢查只探測服務本身；若磁碟滿或 SQLite 鎖死，`/api/health` 可能仍回 200，建議另加磁碟用量監控。
