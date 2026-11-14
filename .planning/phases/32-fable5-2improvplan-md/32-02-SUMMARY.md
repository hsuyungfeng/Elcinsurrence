# 32-02-SUMMARY: Wave 0 介面契約測試骨架建立

## 執行成果摘要
- 依據 Plan 32-02，已建立全部 7 個 Wave 0 介面契約測試檔案，使用 `@pytest.mark.xfail(strict=True, reason=...)` 標記為預期失敗（待後續 Plan 實作解除 xfail）。
- 執行測試驗證：全部 15 個測試案例皆如期 `XFAIL`，無未預期的 `XPASS` 或 `FAILED`。

## 建立之測試檔案清單
1. `tests/test_discovery_responder.py` (2 個 xfail tests：常數金鑰驗證、空 facility 回退)
2. `tests/test_capacity_forecast.py` (4 個 xfail tests：days_until_full、classify_runway、record_daily_sample 冪等、never_deletes 斷言)
3. `tests/test_status_api.py` (1 個 xfail test：status API 結構與探針注入)
4. `tests/test_backup_script.py` (2 個 xfail tests：完整與增量備份契約、無硬連結且唯增不刪)
5. `tests/test_install_script.py` (3 個 xfail tests：ShellCheck/bash 語法安全性、systemd 渲染、環境檔冪等寫入)
6. `tests/test_agent_supervisor.py` (1 個 xfail test：Supervisor 生命週期與指數退避)
7. `tests/test_installer_script.py` (2 個 xfail tests：Inno Setup ISS 契約、安裝檔 SHA-256 驗證)

## 驗證輸出
```
=========================== short test summary info ============================
15 xfailed in 0.20s
```

## 產出狀態
- Plan 32-02 完成。
