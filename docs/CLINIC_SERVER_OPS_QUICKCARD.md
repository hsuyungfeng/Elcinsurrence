# 診所主機維運速查卡（ELC Audit Engine）

> 對象：診所管理員與現場維護人員（所有指令皆可於主機終端機直接複製貼上執行；院內信任網段不需 API 金鑰）。

---

## 1. 一分鐘健康檢查

```bash
# 檢查兩項常駐服務是否皆為 active (running)
systemctl --user status elc-audit-engine.service elc-llama-server.service --no-pager

# 檢查網頁／API 健康與目前規則庫筆數
curl -fsS http://127.0.0.1:5000/api/health && echo ""
curl -fsS http://127.0.0.1:5000/api/rules/status && echo ""

# 檢查記憶體與硬碟剩餘空間
free -h && df -h /home
```

- 正常狀態：兩項服務皆為 `active (running)`，`/api/health` 回傳 `"status":"ok"`，`/api/rules/status` 中 `payment_literal_placeholder_rows` 與 `drug_literal_placeholder_rows` 皆為 `0`。

---

## 2. 服務重啟與日誌檢視

```bash
# 重啟審查引擎服務（更新規則或設定後建議執行，確保切換至新檔案）
systemctl --user restart elc-audit-engine.service

# 重啟本機 LLM 服務（Gemma 4 E4B 128K）
systemctl --user restart elc-llama-server.service

# 查看最近 50 行服務日誌
journalctl --user -u elc-audit-engine.service -n 50 --no-pager
journalctl --user -u elc-llama-server.service -n 50 --no-pager

# 確認開機自啟常駐（Linger 應為 yes）
loginctl show-user "$USER" -p Linger
```

---

## 3. 每月規則庫更新標準作業（SOP）

### 方式 A：透過瀏覽器工作台（推薦）
1. 開啟工作台左側 **「📚 規則」** 面板，檢視目前規則庫筆數與偵測到的最新來源檔名。
2. 選擇新版給付項目 CSV（`醫療服務給付項目*.csv`）或藥品 CSV（`藥品項查詢項目檔*.csv`）上傳。
3. **日常月更請優先點擊「🔄 增量同步（保留舊碼）」**。
   - **重要說明**：部分既有代碼（例如門診藥事服務費、專案計畫碼與疫苗處置費等）未出現在特定期別的來源 CSV 檔中；這些代碼是否屬於有效給付項目，須對照健保署官方公告由人工確認。增量同步會更新來源檔內所有新條文，同時保留未出現在該期來源檔的既有代碼。
   - **「♻️ 整表更新」**已收納於「進階模式」，且須手動輸入 `REPLACE_RULES` 才會執行；除非經人工逐項確認所有舊碼皆可移除，否則勿執行整表更新。

### 方式 B：透過主機終端機（CLI）
```bash
cd ~/Elcinsurrence

# 先做唯讀差異分析，確認不在新檔中的既有代碼分類（絕不改動資料庫）
PYTHONPATH=. .venv/bin/python -m elc_audit_engine.rule_repository.audit_csv \
  --stale-vs-db data/db/rules.sqlite3 \
  --csv "data/rules/醫療服務給付項目支付標準261119已填支付規定.csv"

# 預設安全增量同步（upsert，不刪除既有代碼，自動備份原庫）
PYTHONPATH=. .venv/bin/python -m elc_audit_engine.rule_repository.scripts.sync_latest_rules

# 若確實經人工確認須整表取代（須同時提供 --confirm REPLACE_RULES）
# PYTHONPATH=. .venv/bin/python -m elc_audit_engine.rule_repository.scripts.sync_latest_rules \
#   --replace --confirm REPLACE_RULES

# 同步完成後重啟服務切換新資料庫
systemctl --user restart elc-audit-engine.service
```

---

## 4. `409` 鎖檔與側車檔異常解除程序

### 情況 A：回應 `409` 提示 `rules.sqlite3.lock` 鎖定中
若先前同步曾遇斷電或強制終止，可能殘留鎖檔。**系統絕不自動刪除鎖檔**，請依序確認：

```bash
# 1. 檢視鎖檔內的 PID 與建立時間
cat data/db/rules.sqlite3.lock

# 2. 以該 PID 檢查是否仍有同步行程正在執行（將 <PID> 換為實際數字）
ps -p <PID> -f

# 3. 確認查無該行程（確實無同步進行中）後，才手動移除鎖檔
rm data/db/rules.sqlite3.lock
```

### 情況 B：回應 `409` 提示偵測到 `-wal`／`-shm`／`-journal` 側車檔
- 側車檔代表 SQLite 可能有進行中的交易，**嚴禁在服務寫入中強行刪除側車檔**。
- 請先以 `systemctl --user status elc-audit-engine.service` 確認服務狀態，待寫入完成或於非看診時段重啟服務讓 SQLite 正常關閉復原後再重試同步。

---

## 5. 本機 ASR（`sherpa-onnx`）與 LLM 模型快取檢查

```bash
cd ~/Elcinsurrence

# 檢查 sherpa-onnx 4 項必備本機模型檔（SenseVoice int8 + Pyannote + 3D-Speaker）
bash deploy/install.sh --check-asr-models

# 檢查本機 Gemma 4 E4B Q4_K_M 離線 GGUF 快取（含符號連結有效性）
bash deploy/install.sh --check-llama-cache
```

---

## 6. 規則庫備份與緊急還原

每次同步皆會於 `data/db/` 自動保留最近 5 份備份（`rules.sqlite3.bak.<時間戳>`）。若需還原：

```bash
cd ~/Elcinsurrence

# 1. 檢視可用備份清單（依時間戳由舊到新）
ls -la data/db/rules.sqlite3.bak.*

# 2. 停止服務，避免執行中連線持有舊檔案
systemctl --user stop elc-audit-engine.service

# 3. 保留目前檔案為快照，再從目標備份還原（將 <備份檔名> 換為實際檔名）
cp -p data/db/rules.sqlite3 "data/db/rules.sqlite3.pre_restore.$(date +%s)"
cp -p "data/db/<備份檔名>" data/db/rules.sqlite3

# 4. 核對 SHA-256 並重啟服務
sha256sum "data/db/<備份檔名>" data/db/rules.sqlite3
systemctl --user start elc-audit-engine.service
curl -fsS http://127.0.0.1:5000/api/rules/status && echo ""
```
