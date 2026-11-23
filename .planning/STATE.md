---
gsd_state_version: 1.0
milestone: v1.3
milestone_name: milestone
current_phase: 35
status: Phase 33–35 已完成並通過獨立 Claude Plan Checker 與 Tester 驗收（1,748 passed, 0 failed）
stopped_at: null
last_updated: "2026-11-23T14:07:00+08:00"
last_activity: 2026-11-23 — Phase 35 完成規則庫只讀 CSV 稽核與 NULL 契約統一、SOAP 定向單次修正與空摘要補齊、選配低密度 Whisper 備援護欄、deploy/install.sh 整合 llama/sherpa 檢查、全套件測試隔離防呆修復（1,748 passed, 0 failed）
progress:
  total_phases: 35
  completed_phases: 35
  total_plans: 27
  completed_plans: 27
  percent: 100
---

# STATE.md — elc-audit-engine

## 目前位置 (Current Position)

- **Phase 33（已完成）**：Gemma 4 E4B Q4_K_M + mmproj-BF16（128K context）systemd 常駐服務、本機 Whisper ASR + 熱詞、26 MB / `.opus` 上傳對齊、`clinical` SOAP 品質分流、月審 `payment_text` 精簡預覽。
- **Phase 34（已完成）**：整合 `sherpa-onnx`（SenseVoice int8 + OpenCC `s2twp` + `num_clusters=2` 可選說者分離）為預設 ASR 後端、`finalize` 自動背景 ASR → Gemma 4 E4B SOAP 管線、`ElcAgent.spec` 排除 ASR 套件、`cycle_chunks.py` 審計參數修復。
- **Phase 35（已完成，Claude Plan Checker & Tester 雙重 PASS）**：
  - Wave 1：規則庫只讀 CSV 稽核工具（`audit_csv.py`）、`_csv_table.py` 純占位字串統一存 SQLite `NULL`（對齊 `drug_loader.py` 與 `RuleResult`）、安全備份驗證後重建本機 `rules.sqlite3`。
  - Wave 2：`generate_clinical_soap_from_transcript()` 定向單次品質修正與空摘要補齊（皆傳入原始逐字稿防捏造）、`pipeline.py` 選配低字數密度 Whisper 備援（≥1.25× 且重複率 `<0.15` 護欄）。
  - Wave 3：`deploy/install.sh` 整合 `elc-llama-server.service` 渲染與 HF `snapshots/` 快取檢查、`--check-asr-models` 4 檔檢核與離線降級提示；修復 `tests/conftest.py`、`test_zip_import.py`、`test_agent_desktop_bridge.py` 測試隔離漏洞（全套件 `1,748 passed, 3 skipped, 1 deselected, 0 failed`）。

## 未結與承接項目 (Pending & Deferred Items)

- **Windows 實機人工驗收**：依 `deploy/release-20261116/31-WINDOWS-MANUAL-VERIFY.md` 的 12 項逐一實測（Phase 31–34 共同承接）。**尚未執行。**
- **Windows 打包驗證**：以最新 `deploy/windows_agent/ElcAgent.spec` 與 `soapvoice_client.spec`（D-32-26）於 Windows 環境建置。
- **Ubuntu 乾淨 VM 一鍵安裝驗證**：`deploy/install.sh` 需於獨立乾淨 Ubuntu Server VM 實測。
- **規則庫人工覆核**：依 `python -m elc_audit_engine.rule_repository.audit_csv` 產出的異常清單（含非標準尾碼如 `92043D`、`51002D`、AI 預填條文），由專人對照健保署官方原檔逐項更新。
- **Phase 10（健保 VPN／`NHI_EIIAPI` 實機串接）**：阻塞於外部院所 VPN 與 SAM 卡環境。

## 已知風險與維護註記

- `config/facility.json`、`E4Btest.md`、`data/`（SQLite、音檔、審計日誌）皆由 `.gitignore` 排除，絕不納入 git 提交。
- 本機依賴釘選 `pydantic == 2.13.4`，更新依賴務必使用 `uv lock --no-config` 並確認不降版。
- `Wavesample/` 訓練資料位於工作區內（已 gitignore），日後建議移出。
