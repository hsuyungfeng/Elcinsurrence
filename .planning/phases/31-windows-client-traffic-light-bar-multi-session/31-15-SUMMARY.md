# Plan 31-15 Summary: SoapVoice 本機控制伺服器與循環工作階段 (Wave 4)

## 成果摘要
- **模組交付**：
  1. `/home/hsu/Desktop/Elcinsurrence/SoapVoice/client/cycle_session.py`：
     - `CycleSession`：統籌管理錄音器（`AudioRecorder`）、清冊（`SegmentStore`）、上傳器（`ChunkUploader`）與管線（`CyclePipeline`）。
     - 實作 `start(command_id, cycle_id)`、`stop(command_id, cycle_id)`、`status()`、`archived(cycle_id)`。
     - 執行緒安全與冪等性：以 `threading.RLock()` 確保重入安全，快取最近指令結果，重複指令回傳相同狀態。
     - 錄音保護（Pitfall 5）：錄音中以不同 `cycle_id` 呼叫回傳 409 `busy`，絕不中斷或重設進行中錄音。
     - 資訊安全與脫敏（D-31-02）：`capture_patient` 於錄音開始時截圖並由 GUI 取得病人資訊存入 manifest context，`status()` 僅回傳 `patient_bound: true/false`，絕不包含病人姓名、醫師姓名或任何病歷內文。
     - 封存校驗（D-31-30 ~ D-31-33）：`archived()` 嚴格以伺服器端 `GET /api/cycles/{id}` 為準，確認 `ARCHIVED` 終態後才標記本機 manifest 並觸發空間清理（`cleanup_eligible: true`）；伺服器未確認時回傳 409，無法連線時回傳 503，本機絕不標記。
     - 重啟自癒（D-31-33）：啟動時自動呼叫 `recover_partial` 恢復未正常停止的 `.pcm.part` 音檔並標記 `recording_interrupted`（狀態為 `ERROR`）；背景執行緒定期向伺服器確認，伺服器標記 `ABANDONED` 後本機循環封存恢復 `IDLE`，所有音檔與清冊零刪除保留於磁碟。
  2. `/home/hsu/Desktop/Elcinsurrence/SoapVoice/client/control_server.py`：
     - `ControlServer`（`http.server.ThreadingHTTPServer`）：
       - 強制綁定 `127.0.0.1` / `localhost`，設定非 loopback 主機時拋出 `ValueError`（T-31-57）。
       - 驗證 `Host` 標頭防範 DNS rebinding 跨站攻擊（T-31-58）。
       - 使用 `hmac.compare_digest` 比對 `X-Local-Token`，Token 檔案首次自動生成（32 位 urlsafe，長度 43 字元，POSIX 權限 `0o600`，T-31-61）。
       - 限制請求主體 ≤ 4 KB（413 Payload Too Large）。
       - 安全日誌：日誌僅記錄方法、路徑與狀態碼，絕不洩漏 Token、請求 Body 或病歷資訊。
  3. `/home/hsu/Desktop/Elcinsurrence/SoapVoice/client/main.py`：
     - 初始化 `SegmentStore`、`ChunkUploader`、`CyclePipeline`、`CycleSession` 與 `ControlServer`。
     - `AudioRecorder.on_segment` 回呼綁定 `store.register_chunk` 與 `uploader.notify`（零網路 I/O）。
     - `App.run()` 在背景啟動上傳器、工作階段與本機控制伺服器，若伺服器未設定則友善提示不影響舊版 GUI 錄音。
     - `App.shutdown()` 依序安全停止控制伺服器、工作階段背景執行緒、分段上傳器與錄音器。
     - 提供 `SoapVoiceClientApp = App` 別名相容介面。
  4. 測試套件：
     - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/tests/test_cycle_session.py`（5 項工作階段與狀態自癒測試全數通過）
     - `/home/hsu/Desktop/Elcinsurrence/SoapVoice/tests/test_consultation_ipc.py`（4 項認證、Host 檢查、Token 權限與負載限制測試全數通過）
- **測試結果**：
  - SoapVoice 客戶端測試套件共 101 passed。
  - `import client.main` 驗證通過。

## 偏離與修正
1. 所有 SoapVoice 改動嚴格落地於 `/home/hsu/Desktop/Elcinsurrence/SoapVoice`，完全未寫入 `~/Desktop/SoapVoice`。
2. `CycleSession._lock` 使用 `threading.RLock()` 避免 `start()` / `stop()` 內部呼叫 `status()` 時發生重入死鎖。
3. `tests/test_segmented_recorder.py` 中 `FakeAudioStream.read()` 增加 1ms 等候避免在單一測試內瞬間讀取 10 萬 frames 造成封段競爭。
4. 未修改 `lan_client.py` 與 `lan_config.py` 之未提交內容。
5. 無 git commit，無 git push。
