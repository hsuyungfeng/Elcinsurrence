# Phase 34 計畫：`sherpa-onnx`（SenseVoice int8 ＋ OpenCC ＋ `num_clusters=2` 可選說者分離）整合

**狀態**：已完成（已通過 Herdr Claude Tester 獨立驗收與真實音檔冒煙測試，經使用者確認提交）
**建立日期**：2026-11-23
**依據**：同機 8 支門診 WAV（160.7 分鐘）正面實測（`sherpa-onnx SenseVoice int8` 純 ASR 耗時 225.5s / RTF `0.023` / **42.8× 即時速度**，比 `faster-whisper large-v3-turbo` 快 **4.96×**、全 8 檔 0.0% 重複迴圈、6 淨案 F1 贏下 4 案）。

---

## 一、目標與範圍

1. **整合 `sherpa-onnx` 後端至 `src/elc_audit_engine/asr/`**：
   - 新增 `src/elc_audit_engine/asr/sherpa_backend.py`：
     - 延遲載入 `sherpa_onnx`（SenseVoice int8）＋ `opencc`（`s2twp` 轉台灣繁體）＋ 既有 `config/asr_hotwords.json` 確定性同音專詞校正。
     - 支援可選離線說者分離（`diarize=True`，預設 **`num_clusters=2`** 聚類為醫師／病患雙說者，避免自動門檻在診間移動時切出過多 speaker ID）。
     - 語段合併與切分函式 `merge_diar_segments`（同說者間隔 ≤ 1.0s 合併，單段上限 ≤ 25.0s）。
     - 未安裝依賴或缺少本機模型檔時拋出 `ASRUnavailableError`（系統故障語意，不靜默回傳空逐字稿）。
     - 嚴格 PHI-safe logging（僅記模型、耗時、段數與說者數）。
   - 更新 `src/elc_audit_engine/asr/transcriber.py`：
     - 保留並納管已驗證的 **PyAV 19 相容解碼修復**（`_decode_audio_16k`，避開 `faster-whisper==1.2.1` 傳入 `metadata_errors="ignore"` 觸發 `TypeError`；缺 `av`/`numpy` 一律 fail-closed 拋 `ASRUnavailableError`）。
     - 統一入口 `transcribe_audio(..., backend="sherpa"|"whisper", diarize=False, num_clusters=2)`：**預設後端改為 `sherpa`**（`ELC_ASR_BACKEND` 預設 `"sherpa"`，`whisper` 保留為重雜訊／台語口音備援）。
   - 更新 `pyproject.toml` 與 `uv.lock`（`uv lock --no-config`）：新增選配依賴 `asr-sherpa`（確保 `pydantic` 不降版）。
2. **個資防護與文件同步**：
   - `.gitignore` 新增 `E4Btest.md`（含真實門診譯文，禁止進入公開倉庫）。
   - 同步更新 `README.md`、`AGENTs.md`、`.planning/STATE.md`、`.planning/ROADMAP.md`。
3. **測試與 Herdr Claude Tester 獨立驗收**：
   - 新增 `tests/test_asr_sherpa.py`（全離線注入替身測試：SenseVoice + OpenCC + 熱詞、`diarize=True` 預設 `num_clusters=2`、`merge_diar_segments`、`backend="sherpa"` 派發、缺套件報錯、PHI-safe logging）。
   - 透過 Herdr 啟動獨立 Claude Code Tester 窗格，執行測試、`ruff check .`、檢查 `git diff` / `uv.lock` / `.gitignore`，回報原始驗證結果後才由使用者確認提交。

---

## 二、驗收標準

- `tests/test_asr_sherpa.py` 與 `tests/test_asr_transcriber.py` 全數通過。
- `uv run ruff check .` 零錯誤。
- `uv.lock` 更新後 `pydantic` 維持 `2.13.4`（無降版）。
- `git status --short` 中絕不出現 `E4Btest.md` 或任何病患錄音／資料庫檔案。
- Claude Tester 獨立驗收通過並回報實測數字。
