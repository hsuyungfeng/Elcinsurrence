---
gsd_state_version: 1.0
milestone: v1.3
milestone_name: milestone
current_phase: 38
status: Phase 33–38 已完成並通過獨立 Claude Plan Checker 與 Tester 雙重 PASS（1,766 passed, 0 failed）
stopped_at: null
last_updated: "2026-11-23T17:14:00+08:00"
last_activity: 2026-11-23 — Phase 38 完成零 LLM 確定性官方完整給付規定條文建置器（build_fulltext_mapping.py，冷啟動 1.27s 建置 8,302 筆 rule_mapping：藥品 5,453 筆＋診療項目 2,849 筆）、一二三階全文展開區出處與不重複優化，以及 sync_latest_rules 自動連動與防洗空保護
progress:
  total_phases: 38
  completed_phases: 38
  total_plans: 30
  completed_plans: 30
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
- **Phase 38（已完成，Claude Plan Checker & Tester 雙重 PASS，1,766 passed / 0 failed）**：
  - Wave 1：新增零 LLM 確定性官方全文建置器 `rule_repository/mapping/build_fulltext_mapping.py`（純 Python 標準庫解析 `完整給付規定1140221.odt` 附表／章節、21 份官方 `.docx` 跨段落審查注意事項與手術節表格、`261119` CSV `備註`），冷啟動 1.27s（熱快取 0.53s）為正式 `data/db/rules.sqlite3` 建置 **8,302 筆** `rule_mapping`（藥品 5,453 筆解開 303 字截斷＋診療項目 2,849 筆，原 5,752／11,472 主表零遺失）。
  - Wave 2：`rule_summary.py` 避免 ≤140 字短結構文無意義上下重複；`monthly_report_html.py`、`report_renderer.py`、`sampling_service.py`、`appeal.py` 統一於「📜 檢視完整給付規定條文」優先呈現帶官方出處（`article_location`）之 100% 未截斷全文。
  - Wave 3：`sync_latest_rules.py` 於暫存庫原子同步時自動連動 `build_fulltext_mapping`（缺官方目錄時保留既有列不洗空，`replace=True` 時清理孤立列），`/api/rules/status` 新增回報 `rule_mapping_rows`。

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
