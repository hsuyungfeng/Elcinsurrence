# Phase 33 實作計畫：本機 Whisper ASR・Gemma 4 E4B 落地・錄音上限修正與 SOAP 品質分流

**狀態**：已完成（程式碼、測試與本機實測驗證完成，尚未提交）
**建立日期**：2026-11-20
**依據**：`compare.md`（30 組金標準 100% 實測・8 支真實門診 160.7 分鐘 WAV 評測）

---

## 一、工作項目與檔案對照

1. **工作 1：本機語音辨識（ASR）模組**
   - `config/asr_hotwords.json`：診所專科熱詞與確定性同音專詞校正表。
   - `src/elc_audit_engine/asr/transcriber.py`：延遲載入 `faster-whisper`（預設 `large-v3-turbo`、`int8`、`vad_filter=True`、`condition_on_previous_text=False`）、PHI-safe logging、系統故障誠實回報（`ASRUnavailableError` / `ASRTranscriptionError`）。
   - `pyproject.toml`：新增可選依賴 `[project.optional-dependencies] asr = ["faster-whisper>=1.2.0"]`。
   - `tests/test_asr_transcriber.py`：替身模型單元測試。
2. **工作 2：LLM 模型選型（Gemma 4 E4B）與 ICD-10 核對**
   - `config/llama_config.json`：預設改為 `gemma-4-E4B-it-Q4_K_M`（`n_ctx=32768`）；新增 `config/llama_config.q8.example.json`（`Q8_0`, `n_ctx=16384`）。
   - `src/elc_audit_engine/rule_repository/icd_titles.py`：補齊高頻門診骨科／復健／代謝科 ICD-10 中文名稱。
   - `src/elc_audit_engine/comparator/icd10_validator.py`：本機 `medical.db`（唯讀可選）＋內建對照表核對與高風險語意誤碼警告（絕不自動改碼）。
   - `tests/test_icd10_validator.py`：核對器測試。
3. **工作 3：API 音檔大小上限對齊與 Opus 支援**
   - `src/elc_audit_engine/api/app.py`：`MAX_CONTENT_LENGTH` 由 `11 MB` 調升為 `26 MB`（對齊 `soap_recording.py` 25 MB 契約＋1 MB 表單餘裕；非錄音路由維持各自 10 MB 限制）。
   - `src/elc_audit_engine/api/routes/soap_recording.py`：新增 `.opus`（`audio/opus`, `audio/ogg`）支援並依副檔名落盤。
   - `tests/test_soap_recording_contract.py`：補齊 12 MB WAV、26 MB+ 超限與 `.opus` 端到端測試。
4. **工作 4：SOAP 品質檢核分流與佔位符防線**
   - `src/elc_audit_engine/comparator/soap_advice.py`：`validate_soap_quality(soap_dict, *, profile="template"|"clinical")` 分流、整合 `icd10_validator` 非阻斷警告、新增 `_CLINICAL_TRANSCRIPT_SOAP_PROMPT` 與 `generate_clinical_soap_from_transcript`。
   - `src/elc_audit_engine/api/routes/soap_review.py`、`src/elc_audit_engine/cycles/archive.py`：改用 `profile="clinical"`；`monthly_pregen.py` 與 `his_integration.py` 範本快取維持預設 `profile="template"`。
   - `tests/test_monthly_pregen_soap.py`、`tests/test_soap_advice_bilingual.py`：新增分流與門診逐字稿 SOAP 測試。

---

## 二、驗收標準

- 新增測試全數通過。
- 全套件回歸測試通過：`ELC_ALLOW_NO_AUTH_FOR_TESTS=1 uv run pytest -q tests doc/tests`。
- `uv run ruff check .` 零違規。
- 本機 `Gemma 4 E4B Q4_K_M` 驗證新版 `_CLINICAL_TRANSCRIPT_SOAP_PROMPT` + `profile="clinical"` 在實測樣本上零 `not documented` 佔位符且 `validate_soap_quality(..., profile="clinical")` 通過。
- 不自行 `git commit`。
