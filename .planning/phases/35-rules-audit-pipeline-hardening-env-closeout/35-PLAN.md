# Phase 35 計畫：規則庫資料品質稽核、ASR→SOAP 管線定向強化與主機部署收尾

**狀態**：已完成（已通過獨立 Claude Plan Checker 與 Tester 驗收 PASS：全套件 1,748 passed, 0 failed，零寫入正式 data/）
**建立日期**：2026-11-23
**前置依賴**：Phase 33（Gemma 4 E4B 128K、臨床 SOAP 分流）、Phase 34（`sherpa-onnx` SenseVoice int8 預設 ASR）與 `finalize` 自動背景管線（`1cc862e`、`ce9b0d4`）

---

## 一、背景與問題來源

1. **規則庫 CSV 資料品質風險**：
   - `build_sqlite` 預設載入 `officialdocument/審查注意事項/醫療服務給付項目251027準確板_已優化填入支付規定.csv`（2,669 筆）。初探掃描發現：
     - **455 筆** `支付規定` 為字面字串 `"null"`，因 `_csv_table.py` 未比照 `drug_loader.py` 的 `_PLACEHOLDER_TEXTS` 轉為 `NULL`，導致被原封不動寫入 `rules.sqlite3`。
     - 約 **1,500 筆**含 AI 預填樣板標記（如 `審查原則：`、`Version 1.0`、`版 1.0`、Markdown `**`）、**62 筆**引用表內不存在的醫令碼（其中 **29 筆**含疑似幻覺非標準後綴如 `43006D`、`51002D`、`60001L`、`92043D`），且如 `62010C` 等條文與較新 C 類 CSV（`data/rules/醫療服務給付項目_醫療服務給付項目及支付標準260801_C類已填支付規定.csv`）差異顯著。
   - **硬不變量（`AGENTs.md`）**：絕不憑 AI 記憶捏造或改寫健保法規條文；僅能以確定性只讀稽核清查問題條文供人工對照官方原檔處理，以及統一以 `NULL` 淨化純字面占位字串。
2. **8 支真實門診 WAV 全流程實測露出的 2 個小缺口**：
   - 160.7 分鐘真實音檔實測結果為 7/8 `AWAITING_CONFIRM`（100 分）、1/8 `DRAFT_UNUSABLE`（`sample_03`，純台語重雜訊，19.3 分鐘僅 605 字，A 欄觸發 `placeholder` 扣分）、0 系統錯誤。
   - 另觀察到 `sample_05` 雖 SOAP 四欄滿分 100 過關，但 `conversation_summary` 為空（`summary_zh_chars=0`）。
3. **本機部署與規劃文件收尾**：
   - `deploy/install.sh` 尚未納入 `elc-llama-server.service` 渲染與 `~/.cache/elc-sherpa/` 模型檢查／輔助指引；
   - `.planning/STATE.md` 與 `.planning/ROADMAP.md` 仍停留在 Phase 32 描述，需同步至 Phase 33–35；
   - 本機 Phase 35 實作前開發端自測基線參考值：**`1,735 passed, 3 skipped, 1 deselected`（0 failed，含 LibreOffice 列印測試；最終數字須由獨立 Claude Tester 實測確認）**。

---

## 二、工作項目與實作設計

### Wave 1：規則庫只讀品質稽核與載入器 `NULL` 契約統一
1. **新增只讀稽核模組與 CLI**：`src/elc_audit_engine/rule_repository/audit_csv.py`
   - 支援掃描給付項目（payment）與藥品（drug）CSV（可指定檔案路徑或掃描預設目錄），**嚴格唯讀，絕不修改原 CSV、絕不捏造或自動改寫法規條文**。
   - 確定性稽核項目：
     - `literal_placeholder`：字面 `"null"`、`"none"`、`"n/a"`、`"nan"`、`"未找到給付規定"`（大小寫不敏感）。
     - `missing_code_ref` / `non_standard_suffix_ref`：條文引用 5 碼數字 + 1 碼字母代碼但不存在於同表代碼集；標記非標準尾碼（非 `A/B/C/E/G/H`）。
     - `ai_prefill_marker`：含 `審查原則：`、`Version 1.0`、`版 1.0`、Markdown `**`／` ``` ` 等非官方預填痕跡。
     - `structural_anomaly`：空代碼、生效起日 > 生效迄日、重複代碼且條文不一致。
   - 輸出脫敏 JSON／Markdown 稽核報告（可選 `--json-out` / `--md-out`），供人工對照官方原檔（`完整給付規定1140221.odt` 或健保署公告）覆核。
2. **統一 `_csv_table.py` 占位字串存為 SQLite `NULL`（對齊 `drug_loader.py:57` 與 `RuleResult.payment_text: str | None`）**：
   - 修改 `src/elc_audit_engine/rule_repository/loaders/_csv_table.py`：新增 `_normalize_rule_text(raw: str) -> str | None`，將純占位字串（`{"", "null", "none", "n/a", "nan", "未找到給付規定"}`，忽略前後空白與大小寫）統一轉為 `None`（SQLite `NULL`），與 `drug_loader.py` 的 `load_drug_csv_full` 及 `tests/test_rules_sync.py:110` 契約完全一致。
   - **安全重建本機 `data/db/rules.sqlite3`**：先建立暫存新庫 `data/db/rules.sqlite3.new` → 驗證 `payment_rules` / `drug_rules` 列數與字面 `'null'` 筆數皆為 `0` → 檢查原目錄無殘留 `rules.sqlite3-wal`／`rules.sqlite3-shm` 側車檔 → 備份原庫為 `data/db/rules.sqlite3.bak.<timestamp>` 並記錄前後 SHA-256 → 原子替換 `os.replace` → 重啟 `elc-audit-engine.service` 確保行程改讀新 inode。
3. **新增測試**：`tests/test_rule_csv_audit.py`
   - 全程以合成暫存 CSV 測試 4 類稽核檢出、原檔 SHA-256 不變（唯讀保證）、以及 `load_payment_csv` / `load_drug_csv` 將字面 `"null"`／`"未找到給付規定"`／空白統一存為 SQLite `NULL`（`RuleResult.payment_text is None`）。

### Wave 2：ASR → Gemma 4 E4B SOAP 管線定向強化
1. **定向修正與空摘要補齊（`src/elc_audit_engine/comparator/soap_advice.py`）**：
   - 在 `generate_clinical_soap_from_transcript()` 新增可選參數 `allow_retry: bool = True`（預設啟用），精確使用 `validate_soap_quality(..., profile="clinical")` 的既有鍵名 **`quality["pass"]`** 與 **`quality["quality_score"]`**（見 `soap_advice.py:67`）：
     - **品質問題單次定向修正**：初次產出若 `not quality["pass"]`（例如觸發 `placeholder` 或字數異常），執行**最多 1 次**修正呼叫；**必須一併傳入原始逐字稿 `fence(cleaned_tr[:18000], 'transcript')`**、原 SOAP 與 `quality["issues"]`，指示 LLM 僅依據逐字稿修正指定問題欄位並移除佔位語句，嚴禁捏造未提及之症狀、檢查、數值、診斷或處置。僅當重試產出合法 JSON 且**（原 failed 轉為 `retry_quality["pass"] is True`，或 `retry_quality["quality_score"] > quality["quality_score"]`）**才採用，否則回退原結果交由既有 `DRAFT_UNUSABLE` 閘門把關。
     - **空摘要單次輕量補齊**：若最終 SOAP 品質已通過（`quality["pass"] is True`）但 `conversation_summary` 為空，執行**最多 1 次**輕量摘要補齊（`max_tokens=200`），**同樣傳入 `fence(cleaned_tr[:18000], 'transcript')`**，要求嚴格依逐字稿產出 60–120 字繁體中文摘要；若補齊失敗／逾時／為空，優雅保留原已合格之 SOAP。
   - 回傳字典附帶非 PHI 元資料 `retried: bool`、`summary_backfilled: bool`（向下相容新增欄位）。
2. **選配低字數密度 Whisper 備援與重複率護欄（`src/elc_audit_engine/cycles/pipeline.py`）**：
   - 新增純函式 `_transcript_repetition_ratio(text: str, *, window: int = 8) -> float`（確切公式）：
     1. 以 `re.sub(r"\s+", "", text or "")` 去除所有空白字元得 `cleaned`；
     2. 若 `len(cleaned) < window`，回傳 `0.0`；
     3. 取步長為 1 之全部連續 `window` 字元滑動視窗 `windows = [cleaned[i : i + window] for i in range(len(cleaned) - window + 1)]`；
     4. 回傳 `round(1.0 - (len(set(windows)) / len(windows)), 4)`（重複視窗占比，範圍 `[0.0, 1.0)`；單元測試具完全確定性期望值）。
   - 新增選配環境變數（預設關閉，維持純 SenseVoice 零額外延遲）：
     - `ELC_ASR_LOW_DENSITY_WHISPER_FALLBACK`（預設 `"0"`；設 `"1"` 開啟）。
     - `ELC_ASR_MIN_CHARS_PER_MIN`（預設 `60`，只對音長 ≥ 60 秒之錄音判定）。
   - 在 `run_cycle_auto_pipeline()` 新增測試注入點 `fallback_transcriber: Optional[Callable[[Path], TranscriptionResult]] = None`（未提供時預設呼叫 `transcribe_audio(audio_path, backend="whisper")`）。
   - 當主轉錄為 `sherpa`、音長 ≥ 60 秒且「去除空白後字元數 / 分鐘數 < 門檻」時，嘗試備援轉錄；**必須同時滿足**「非空」、「有效字元數 ≥ 原結果 × 1.25」且「重複率 `< 0.15`」才採用備援結果；若備援未安裝（`ASRUnavailableError`）或失敗或重複率過高，記錄 PHI-safe warning 並**優雅保留原 `sherpa` 逐字稿**。
3. **新增／擴充測試**：
   - 新增 `tests/test_clinical_soap_retry.py`：驗證 `quality["pass"]` / `quality["quality_score"]` 判定、placeholder 定向重試成功、重試仍差／失敗時安全回退、空摘要單次補齊成功與失敗保底、**明確斷言兩次重試呼叫的 `user_prompt` 皆包含原始逐字稿**、`allow_retry=False` 不重試、嚴格最多 1 次重試。
   - 擴充 `tests/test_cycle_pipeline.py`：以 `fallback_transcriber` 注入測試低密度觸發採用（≥1.25× 且低重複率）、高重複率 Whisper 結果被護欄拒收、低於 60 秒不觸發、預設關閉不觸發、Whisper 缺套件（`ASRUnavailableError`）優雅保底原逐字稿與 PHI-safe logging。

### Wave 3：主機一鍵安裝整合、全套件健康檢查與文件同步
1. **更新 `deploy/install.sh` 與 `tests/test_install_script.py`**：
   - `render_units_to()` 納入 `elc-llama-server.service`（共 6 個 unit）；在 systemd 啟用步驟中，須**同時確認**：
     1. `"$USER_HOME/.local/bin/llama"` 可執行檔存在；且
     2. 離線 GGUF 快取檔存在且符號連結目標有效：`find "$USER_HOME/.cache/huggingface/hub/models--unsloth--gemma-4-E4B-it-GGUF/snapshots" -name '*Q4_K_M*.gguf' -exec test -e {} \; -print -quit 2>/dev/null` 回傳非空；
     才執行 `systemctl --user enable --now elc-llama-server.service`；否則僅渲染單元檔並印出離線快取下載指引，不中斷安裝。
   - `sync_deps`（在 `set -euo pipefail` 下安全降級）：先嘗試 `uv sync --no-config --extra asr-sherpa`；若離線環境下載 wheel 失敗，捕捉失敗並自動退回 `uv sync --no-config`，同時印出明確警告與執行 `check_asr_models` 顯示目前 ASR 狀態，讓操作者清楚知道本機 ASR 套件未裝上。
   - 新增 `--check-asr-models` 旗標（同步加入 `case` 分支、`-h/--help` 說明與 `ELC_SHERPA_CACHE_DIR` 可覆寫目錄以便測試）：逐一檢查以下 **4 個必備檔案**：
     1. `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09/model.int8.onnx`（或 `model.onnx` 擇一）
     2. `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09/tokens.txt`
     3. `sherpa-onnx-pyannote-segmentation-3-0/model.onnx`（或 `model.int8.onnx` 擇一）
     4. `3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx`
     齊全回傳 0、缺任一檔印出缺檔清單與下載指引並回傳非 0（絕不使用 `curl | sh`、不於 `--dry-run` 聯網）。
   - 擴充 `tests/test_install_script.py`：驗證 `elc-llama-server.service` 渲染、HF `snapshots/` 快取偵測函式（含有效／失效 symlink）、`--check-asr-models` 4 檔齊全與缺檔情境（含 `pyannote` `model.onnx` / `model.int8.onnx` 擇一）與既有安全性／語法檢查全過。
2. **全套件回歸驗證**：
   - 開發端實作前自測參考基線為 `1,735 passed, 3 skipped, 1 deselected`（0 failed；所有測試均以 tmp 目錄與隔離 SQLite 執行，不觸碰正式 `data/db/cases.sqlite3`）；Phase 35 實作後由開發端與獨立 Claude Tester 各自實測確認 **0 failed**。
3. **規劃文件同步**：
   - 更新 `.planning/STATE.md` 與 `.planning/ROADMAP.md` 補齊 Phase 33、34、35 進度與最新全套件基線數字。

---

## 三、不變量與安全邊界（`AGENTs.md`）

1. **絕不捏造規則或臨床事實**：規則稽核工具嚴格唯讀；SOAP 定向修正與空摘要補齊 prompt 皆傳入原始逐字稿 `fence(transcript)` 並明示嚴禁捏造，重試次數硬上限為 1 次。
2. **系統故障語意**：Whisper 備援缺套件或高重複率不破壞原 `sherpa` 結果；空摘要補齊失敗不丟棄已合格 SOAP；`install.sh` 離線降級不中斷核心安裝。
3. **Zero PHI**：稽核報告、重試日誌、測試輸出皆不含病患資料、逐字稿或 SOAP 原文；絕不碰正式 `data/db/cases.sqlite3`。
4. **依賴穩定**：本 Phase 不更動 `pyproject.toml` / `uv.lock`（維持 `pydantic == 2.13.4`）。

---

## 四、驗收標準（獨立 Claude Plan Checker ＋ Tester）

- [ ] 獨立 Claude Plan Checker 審核本修訂版計畫為 **PASS**。
- [ ] `python -m elc_audit_engine.rule_repository.audit_csv` 可唯讀掃描並產出結構化異常清單；備份驗證後重建 `data/db/rules.sqlite3`，確認字面 `'null'` 筆數為 `0`（統一存為 SQLite `NULL`）。
- [ ] `tests/test_rule_csv_audit.py`、`tests/test_clinical_soap_retry.py`、`tests/test_cycle_pipeline.py`、`tests/test_install_script.py` 與既有關聯測試全數通過。
- [ ] `.venv/bin/ruff check .` 零錯誤。
- [ ] 全套件 `pytest` 重跑維持 **0 failed**（對照 1,735 passed 基線只增不減）。
- [ ] 隔離實測 `sample_03` 與 `sample_05` 驗證定向修正與空摘要補齊效果（零 PHI 輸出）。
- [ ] 獨立 Claude Tester 驗收 **PASS**，確認後再依使用者指示決定是否 commit/push。
