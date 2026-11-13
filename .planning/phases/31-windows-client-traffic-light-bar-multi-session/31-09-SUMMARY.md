# Plan 31-09 Summary: Server 分段儲存、去重與 finalize 串接 (Task 1 & Task 2)

## 成果摘要
- **模組交付**：
  1. `src/elc_audit_engine/cycles/chunks.py`：
     - `store_chunk`：分段寫入 `DATA_DIR/cycles/{cycle_id}/chunk_{seq:06d}.wav`。
     - **去重防競態（D-31-20）**：`BEGIN IMMEDIATE` 交易內比對 `(cycle_id, seq)`。相同雜湊重送回傳 `duplicate=True`；不同雜湊拋出 `ChunkConflictError`。
     - **雜湊與格式驗證（D-31-30）**：重算 SHA-256，不符拋出 `ChunkHashMismatchError`；驗證 16 kHz mono 16-bit PCM WAV，非 WAV 拋出 `ChunkFormatError`；上限 4 MiB。
     - `finalize_cycle_audio`（D-31-23, D-31-27）：檢查 0..total_chunks-1 完整性（缺段拋 `MissingChunksError`）、計算 PCM 串接 SHA-256（不符拋 `AudioHashMismatchError`）、產生 `full.wav`（tmp+replace）並設定 `upload_complete=1`。重送相同參數冪等成功。
     - `cycle_artifacts`（D-31-28）：查詢循環成果檔案路徑。
     - **零刪除不變量（D-31-29）**：模組內所有 `unlink()` 嚴格限定於臨時暫存檔（`.tmp`），絕不刪除任何正式分段。
  2. `src/elc_audit_engine/api/routes/cycle_chunks.py`：
     - `POST /api/cycles/<cycle_id>/chunks`（接收 multipart，支援 Content-Length 預檢、seq 驗證、去重狀態碼 201/200/409/422/413/404）。
     - `POST /api/cycles/<cycle_id>/finalize`（驗證全段到齊與 PCM 雜湊，回傳 200/409/422/404）。
     - **安全隔離**：全域 API Key 保護；Agent 金鑰一律 403；私有 IP 亦需金鑰（不套用 `/api/soap/recordings` 免金鑰例外）；日誌嚴格過濾音訊內容與 PHI。
  3. `tests/test_cycle_chunks.py`：
     - 包含核心邏輯與 API 整合測試共 14 項測試，全數通過。
- **測試結果**：
  - `tests/test_cycle_chunks.py` 14 passed。
  - 既有循環測試套件 26 passed。

## 偏離與路徑對應
- 無偏離。本計畫全數於 `Elcinsurrence` 倉庫實作，遵守無 git commit 規則。
