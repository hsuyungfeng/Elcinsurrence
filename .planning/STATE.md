---
gsd_state_version: 1.0
milestone: v1.3
milestone_name: milestone
current_phase: 37
status: Phase 33–37 已完成並通過獨立 Claude Plan Checker 與全套件驗收（1,763 passed, 0 failed）
stopped_at: null
last_updated: "2026-11-23T16:40:00+08:00"
last_activity: 2026-11-23 — Phase 37 完成正式規則庫安全等價重建至 5,752 筆（已獲使用者核准為正式基準並留存固定快照）、audit_csv 舊碼唯讀 8 類分類工具、函式／API／CLI／前端四重整表防誤觸（advanced-only＋REPLACE_RULES 確認碼），以及一頁式《診所主機維運速查卡》（docs/CLINIC_SERVER_OPS_QUICKCARD.md）與自動檢核測試（1,763 passed, 0 failed）
progress:
  total_phases: 37
  completed_phases: 37
  total_plans: 29
  completed_plans: 29
  percent: 100
---

# STATE.md — elc-audit-engine

## 目前位置 (Current Position)

- **Phase 33（已完成）**：Gemma 4 E4B Q4_K_M + mmproj-BF16（128K context）systemd 常駐服務、本機 Whisper ASR + 熱詞、26 MB / `.opus` 上傳對齊、`clinical` SOAP 品質分流、月審 `payment_text` 精簡預覽。
- **Phase 34（已完成）**：整合 `sherpa-onnx`（SenseVoice int8 + OpenCC `s2twp` + `num_clusters=2` 可選說者分離）為預設 ASR 後端、`finalize` 自動背景 ASR → Gemma 4 E4B SOAP 管線、`ElcAgent.spec` 排除 ASR 套件、`cycle_chunks.py` 審計參數修復。
- **Phase 35（已完成）**：規則庫只讀 CSV 稽核工具（`audit_csv.py`）、`_csv_table.py` 純占位字串統一存 SQLite `NULL`、SOAP 定向單次修正與空摘要補齊、選配低密度 Whisper 備援護欄、`deploy/install.sh` 整合 llama/sherpa 檢查、全套件測試隔離防呆修復（`1,748 passed, 0 failed`）。
- **Phase 36（已完成，Claude Plan Checker & Tester 雙重 PASS，1,755 passed, 0 failed）**：
  - Wave 1：移除工作台頂部 3 步驟導引列（`workflow-stepper`）釋放垂直版面空間。
  - Wave 2：精準化 `audit_csv.py`（中文緊鄰醫令碼正則＋避免誤報官方「審查原則：」）、新增 `GET /api/rules/status`、`/api/rules/upload` 單路由放寬至 65 MB、`sync_latest_rules` 升級為 `O_EXCL` 行程鎖＋側車檢查（`-wal`/`-shm`/`-journal`）＋整庫原子替換＋依檔名時間戳備份輪替（上限 5 份）＋唯讀稽核摘要；升級前端 `📚 規則` 面板；本機 `data/db/rules.sqlite3` 以安全 `upsert` 套用最新 `261119`（4,967 筆＋785 保留舊碼 ＝ 5,752 筆）＋ `261028`（11,472 筆）；修正 `OrderJudgment.llm_failed` 區分官方 `NULL` 條文（業務待人工 `reviewed`）與 LLM 系統故障（`failed`）。
  - Wave 3：`soap_advice.py` 臨床 `pending` 兩步防繞過精準化（放行明確檢驗追蹤語境，嚴格攔截 10 組診斷／計畫／`problem` 待定繞過與裸佔位）。
- **Phase 37（已完成，Claude Plan Checker PASS、全套件 1,763 passed / 0 failed，5,752 碼重建基準獲使用者核准）**：
  - Wave 1：正式 `data/db/rules.sqlite3` 經確定性等價重建為 5,752 筆給付＋11,472 筆藥品（`sha256: 81de3061...`，並留存 4,967 碼事故快照與不受輪替影響的 5,752 碼固定快照）；擴充 `audit_csv.py` 新增唯讀 8 類舊碼差異分析（`classify_payment_code_category`、`analyze_stale_payment_codes`、`format_stale_markdown`、`--stale-vs-db`），驗證 `stale_count > 0` 一律建議 `upsert`。
  - Wave 2：建立函式層／API（422）／CLI（`--confirm REPLACE_RULES`）／前端（`advanced-only`＋`prompt` 確認詞）四重整表防誤觸；新增一頁式非工程師《診所主機維運速查卡》（`docs/CLINIC_SERVER_OPS_QUICKCARD.md`）與自動檢核測試（`tests/test_ops_quickcard_doc.py`），並同步 `README.md` 索引。

## 未結與承接項目 (Pending & Deferred Items)

- **Windows 實機人工驗收**：依 `deploy/release-20261116/31-WINDOWS-MANUAL-VERIFY.md` 的 12 項逐一實測（Phase 31–37 共同承接）。**尚未執行。**
- **Windows 打包驗證**：以最新 `deploy/windows_agent/ElcAgent.spec` 與 `soapvoice_client.spec`（D-32-26）於 Windows 環境建置。
- **Ubuntu 乾淨 VM 一鍵安裝驗證**：`deploy/install.sh` 需於獨立乾淨 Ubuntu Server VM 實測。
- **785 筆不在 `261119` 的舊給付碼人工確認**：已完成唯讀 8 類分類分析（確認含專案計畫碼、門診藥事服務費、疫苗處置等，維持 `upsert` 保留；整表更新已收納至進階模式並需 `REPLACE_RULES` 確認）。
- **Phase 10（健保 VPN／`NHI_EIIAPI` 實機串接）**：阻塞於外部院所 VPN 與 SAM 卡環境。

## 維運與已知風險註記

- **規則同步鎖檔恢復程序**：同步過程建立 `data/db/rules.sqlite3.lock`（內含 `pid=<PID>` 與 `created_at`）。若服務曾遭強制中止（如 `kill -9` 或斷電）導致鎖檔殘留而回 `409`，請先執行 `cat data/db/rules.sqlite3.lock` 取得 PID，再以 `ps -p <PID>` 確認無同步行程執行中，確認後手動執行 `rm data/db/rules.sqlite3.lock` 即可恢復。
- `config/facility.json`、`E4Btest.md`、`data/`（SQLite、音檔、審計日誌）皆由 `.gitignore` 排除，絕不納入 git 提交。
- 本機依賴釘選 `pydantic == 2.13.4`，更新依賴務必使用 `uv lock --no-config` 並確認不降版。
