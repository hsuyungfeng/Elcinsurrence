# Phase 32 Plan 15: Ubuntu Server 一鍵安裝與服務樣板 Summary

> **日期**：2026-11-14  
> **狀態**：✅ COMPLETE  
> **需求**：D1、C6、D5、D-32-02、D-32-11、D-32-16、D-32-17  

---

## 執行成果

1. **一鍵安裝腳本實作 (`deploy/install.sh`)**：
   - 支援 `--dry-run`、`--yes`、`--render-units <DIR>`、`--write-env <FILE>`。
   - **相依與環境**：檢查 Ubuntu 與 `uv`，若缺少 `uv` 提示官方文件，絕不自動 `curl | sh`。
   - **單元檔樣板渲染**：將 5 個 systemd 單元檔（主服務、健康檢查 service/timer、備份 service/timer）中的 `@ROOT@` 依據 `ELC_INSTALL_ROOT`（或專案目錄）自動代入，移除所有硬編碼 `/home/hsu/Desktop/Elcinsurrence`。
   - **環境變數補齊**：建立或維護 `~/.config/elc-audit-engine/env`，設置權限 600，具等冪性（保留既有自訂設定），預設 `ELC_SERVER_HOST=0.0.0.0`，完全不含 `ELC_API_KEYS`。
   - **信任網段偵測與確認**：呼叫 `python -m elc_audit_engine.lan_trust --describe` 取得實體網卡網段，落實 D-32-16／D-32-17。
   - **外接備份媒體**：提示設定 `ELC_BACKUP_ROOT`，相容 exFAT 媒體（D-32-11）。
   - **系統服務與常駐**：自動安裝並啟用 systemd user units，提示 `loginctl enable-linger` 與 UFW 規則。
   - **固定 IP 提示與總結（C6）**：偵測 DHCP 動態分配狀態，提示分享器保留固定 IP，結尾輸出 `/setup`、`/`、`/status` 網址。

2. **深度健康檢查維護 (`deploy/healthcheck.sh`)**：
   - 於原有 `/api/health` 存活檢查之後，非侵入式探測 `/api/health/deep` 並輸出 `logs/health-deep.json`。
   - 狀態碼變化（200 ↔ 503）時記錄至日誌，深度狀態不觸發引擎重啟（D5：LLM 離線不中斷核心引擎）。

3. **文件全面更新 (`deploy/README.md`)**：
   - 將主機安裝流程收斂為以 `bash deploy/install.sh` 為主。
   - 補充初次設定（`/setup`）、狀態監控（`/status`）、exFAT 每日增量備份（`/backup.sh`）與排錯說明。
   - 移除過時的金鑰說明與手動複製單元檔指令。

4. **測試與驗證 (`tests/test_install_script.py`)**：
   - 移除 Wave 0 xfail 標記。
   - 驗證腳本語法、安全無 `curl|sh`、單元檔樣板渲染與路徑取代、環境檔寫入等冪性、dry-run 網址輸出。
   - 4 項測試全數通過（4 passed in 1.78s）。
