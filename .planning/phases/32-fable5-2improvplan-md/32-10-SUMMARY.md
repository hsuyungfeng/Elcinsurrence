# Phase 32 Plan 10: D4 增量備份與雜湊驗證 Summary

> **日期**：2026-11-14  
> **狀態**：✅ COMPLETE  
> **需求**：D4、D-32-04、D-32-07、D-32-11  

---

## 執行成果

1. **備份核心模組實作 (`src/elc_audit_engine/backup_job.py`)**：
   - 實作 `sha256_file`、`plan_incremental`、`run_backup` 與 `main` 入口。
   - **SQLite 一致性快照**：以 `sqlite3.connect().backup()` 匯出一致性快照，排除 `-wal`、`-shm`、`-journal` 暫存檔。
   - **exFAT 相容增量複製**：首次執行建立 `elc-backup/full/`，後續執行建立 `elc-backup/incr/$STAMP/`。不使用硬連結、符號連結或 Unix 權限。
   - **雙向雜湊驗證**：複製每個檔案後立即重新計算 sha256 比對，任何不符即中止、不寫出 manifest，並於狀態檔中標示錯誤。
   - **安全防禦與狀態觀測**：目的端不可與來源位於同一檔案系統（`st_dev` 比對，防止覆寫主機磁碟）；備份狀態寫入 `logs/backup-status.json`（含 `last_backup_at`、`snapshot`、`mode`、`free_bytes`、`verified_files`）。
   - **零刪除保證**：程式碼完全不含 `--delete`、`--link-dest`、`rm -rf`、`rmtree`、`os.remove`、`unlink(`、`os.link`、`symlink`。

2. **排程與腳本包裝**：
   - `deploy/backup.sh`：bash 薄殼，支援 uv 與 venv 自動 fallback。
   - `deploy/elc-backup.service`：systemd user service 樣板（`Type=oneshot`，`Nice=10`，`IOSchedulingClass=idle`，使用 `@ROOT@` 佔位符）。
   - `deploy/elc-backup.timer`：systemd user timer（每日 02:30 執行，`Persistent=true` 支援關機後補跑）。

3. **測試與驗證**：
   - 移除 `tests/test_backup_script.py` 的 xfail 標記。
   - 新增雜湊破損模擬測試 (`test_backup_hash_mismatch_failure`)、同裝置防護測試 (`test_backup_same_fs_rejected_without_override`)、增量決策邏輯測試 (`test_plan_incremental_logic`)。
   - 5 項測試全數通過（5 passed in 4.02s）。
