# MockHIS 探針測試操作說明

本文件說明如何在 Windows 測試機上執行 MockHIS 探針，驗證「寫入 → 讀回 → 比對」流程。

## 一、重要注意事項（請先閱讀）

- **只能在測試機上執行**，且測試機上的資料必須是**示範資料**。
- 本工具只會操作標題含「MockHIS」的測試替身視窗。若找不到此視窗，或偵測到其他視窗，程式會**立即中止**，不會寫入任何資料。
- **不要**把此工具指向任何真實醫療系統（HIS）的視窗，也**不要**在正式環境執行。
- 測試過程中的假資料為 `TEST-*` 開頭，不會被儲存。

## 二、需要的檔案

請確認收到的壓縮檔名稱為 `MockHIS_Probe_Bundle_handoff.zip`，並核對以下 SHA-256 校驗碼：

```
7de567fd1e657942cbbc8fe627336fd5889ef7a9147e9ca4f860f006d3725d10
```

在 PowerShell 內可用以下指令核對：

```powershell
Get-FileHash .\MockHIS_Probe_Bundle_handoff.zip -Algorithm SHA256
```

若校驗碼不一致，請**不要執行**，並通知傳送者重新傳送。

壓縮檔內容：

| 檔案 | 用途 |
|---|---|
| `mock_his.py` | MockHIS 測試替身視窗 |
| `probe_readback_check.py` | 探針程式（寫入與讀回驗證） |
| `agent-desktop.exe` | 探針所使用的執行檔 |
| `python-3.12.10-amd64.exe` | Python 安裝程式（若機器沒有 Python 3.12 才需要） |
| `run_probe.bat` | 一鍵執行的批次檔 |

## 三、操作步驟

1. 解壓縮 `MockHIS_Probe_Bundle_handoff.zip`，會得到 `MockHIS_Probe_Bundle` 資料夾。
2. 進入該資料夾，**雙擊 `run_probe.bat`**。
   - 第一次執行時，若機器沒有 Python 3.12，批次檔會自動安裝（只安裝給目前使用者，不加入 PATH）。
   - 批次檔會先開啟 MockHIS 測試視窗（標題含「MockHIS」），**請保持此視窗開啟**。
3. 等待約 3 秒後，批次檔會自動執行探針，畫面會顯示探針輸出。
4. 探針結束後畫面會顯示「Probe finished. Copy the output above.」，此時**請把畫面上的完整輸出複製下來**，連同測試機的 Windows 版本一起回傳給傳送者。
5. 按任意鍵關閉視窗。測試完成後，請關閉 MockHIS 測試視窗。

## 四、如何判讀結果

- 輸出中若顯示寫入的 nonce（`PROBE-` 開頭的隨機碼）與讀回的值一致，代表寫入與讀回流程正常。
- 若出現「找不到含 MockHIS 之視窗」等訊息，代表探針主動中止，這是安全機制正常運作，**不是錯誤**。請確認 MockHIS 視窗是否仍開啟、標題是否正確。
- 若出現其他錯誤訊息，請完整複製輸出並回傳。

## 五、常見問題

| 狀況 | 處理方式 |
|---|---|
| 雙擊 `run_probe.bat` 後跳出 Python 安裝視窗 | 這是正常的首次安裝，請等待完成。 |
| 顯示 `ERROR: Python installation failed.` | 請確認有足夠權限，或改用手動安裝 `python-3.12.10-amd64.exe` 後再執行。 |
| 探針找不到 MockHIS 視窗 | 確認 MockHIS 視窗已開啟且沒有被最小化；必要時關閉後重新執行 `run_probe.bat`。 |
| 校驗碼不一致 | 停止操作，通知傳送者重新傳送檔案。 |

## 六、回傳內容

請回傳以下資訊：

1. 探針的完整輸出（從 `Starting MockHIS test window` 到 `Probe finished` 為止）。
2. 測試機的 Windows 版本（可在 PowerShell 執行 `[System.Environment]::OSVersion.VersionString`）。
3. 是否有任何錯誤訊息或異常畫面，請附上截圖。

請勿回傳任何真實病患資料。
