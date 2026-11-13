# Plan 31-07 Summary: SoapVoice 分段落地錄音器 (Task 1 & Task 2)

## 成果摘要
- **模組交付**：
  1. `SoapVoice/client/audio_recorder.py`：
     - **邊錄邊落地（D-31-21）**：移除 `audio_frames.append` 記憶體累積，每批讀取 frames 立即寫入 `chunk_{seq:06d}.pcm.part` 並執行 `flush()` 與 `fsync()`。
     - **定長切段（D-31-19）**：每達 `frames_per_segment`（預設 20 秒，介於 15–30 秒夾取）以 tmp 檔 + `fsync` + `os.replace` 原子方式封段為 `chunk_{seq:06d}.wav`，並觸發 `on_segment(seq, path)`。
     - **回呼例外隔離（D-31-22）**：`on_segment` 拋出例外時轉入 `on_error`，不中斷背景錄音迴圈。
     - **崩潰恢復**：提供 `recover_partial(cycle_dir)`，可將未封段之殘留 `.pcm.part` 自動轉為 WAV 分段。
     - **分段串接**：提供 `concat_segments(cycle_dir, out_path)` 與 `pcm_sha256(paths)`（符合契約 §2 audio_sha256）。
     - **舊介面相容**：`start()` / `stop()` 舊呼叫模式自動建立暫存子目錄並於停止時串接回傳單一 WAV 路徑。
  2. `SoapVoice/tests/test_segmented_recorder.py`：
     - TDD 測試套件，涵蓋假串流分段、磁碟即時 flush、崩潰恢復、回呼例外隔離、分段秒數夾取、舊模式相容串接、接續 seq 等 7 項測試。
- **測試驗證**：
  - RED 階段確認：新增前執行 `tests/test_segmented_recorder.py` 遭遇 `ImportError: cannot import name 'concat_segments'`（RED 證據已確認）。
  - GREEN 階段：
    - `tests/test_segmented_recorder.py` 7 passed。
    - `tests/test_client.py` 60 passed（全套件合計 67 passed）。
    - `grep -n "audio_frames.append" client/audio_recorder.py` 結果為空（無累積）。

## 偏離與路徑對應
- **路徑偏離**：依使用者指示，所有 SoapVoice 客戶端修改一律實作於 `/home/hsu/Desktop/Elcinsurrence/SoapVoice`，禁止寫入 `~/Desktop/SoapVoice`。
- **Git 狀態**：遵守使用者指示，未對任何 repo 進行 git commit。
