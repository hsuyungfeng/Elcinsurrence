# Phase 37 計畫：正式規則庫安全還原（5,752 碼）、舊碼唯讀分類工具、整表防誤觸與《診所主機維運速查卡》

**狀態**：執行完成（已獲使用者核准還原方案 A 與 `advanced-only` 防誤觸，並通過獨立 Claude Plan Checker 複審 PASS）
**建立日期**：2026-11-23
**前置依賴**：Phase 36（`b515b42`，規則原子更新機能上線）
**執行實況註記（備份輪替處理）**：2026-11-23 16:11:42–16:11:49 本機又連續收到 4 次 `POST /api/rules/sync`，因 `max_backups=5` 輪替淘汰了最早的 `rules.sqlite3.bak.1795420942`；改以正式來源檔確定性等價重建（`251027` 基底 → `upsert 261119` → `261028` 藥品＋`rule_mapping` 空表，經實測與原 5,752／11,472 庫之 8 類 785 碼分布完全一致），同樣停服、留存 4,967 碼事故快照、原子替換並驗證完整 64 碼 SHA-256。

---

## 一、背景與已核准決策

1. **正式規則庫還原決策（使用者已核准選項 A）**：
   - 本機正式 `data/db/rules.sqlite3` 於 2026-11-23 16:02 經瀏覽器執行整表取代後降至 4,967 筆（785 筆不在 `261119` 內的專案／藥事服務費／疫苗處置碼被移除）。
   - Phase 36 自動備份完整保留了切換前之快照 **`data/db/rules.sqlite3.bak.1795420942`**（`payment_rules = 5,752`、`drug_rules = 11,472`，`sha256 = f9efb976...`）。
   - 以該備份進行唯讀分類驗證，785 碼全數有效（DB 格式 `2910-12-31`／來源 CSV 格式 `29101231`），包含 P 專案計畫碼 335 碼、N 類 119 碼、PT/OT/ST 68 碼、純數字預防保健／篩檢碼 66 碼、D 類門診藥事服務費等 13 碼、C 類疫苗處置等 6 碼、E 類 5 碼、其餘特項碼 173 碼（其中 AI 預填 401 碼、NULL 74 碼、其他 310 碼；`rule_mapping` 關聯 0）。
   - *(前期一次性唯讀背景實查備註：曾以代碼交集核對本機 `data/TOTFA.zip` 確認其中包含實際申報代碼 `48027P`/`48028P`/`05204D`；因 `TOTFA.zip` 含病患申報檔，本 Phase 新增之唯讀分析工具與單元測試**不讀取 `TOTFA.zip`**，僅以規則 DB 與規則 CSV 進行可重現分析，零 PHI。)*
   - **已核准行動**：
     1. 停服 → 將現況 4,967 筆另存事故快照 → 驗證 `data/db/rules.sqlite3.bak.1795420942` 列數與 SHA-256 → 原子還原為 `data/db/rules.sqlite3`（回復 5,752 筆）→ 重啟服務並確認 `/api/rules/status`。
     2. 將前端 `static/index.html` 的「♻️ 整表更新（套用最新版）」按鈕加上 `advanced-only`，日常醫師模式只顯示安全的「🔄 增量同步（保留舊碼）」。
2. **診所主機日常維運缺口**：
   - 建立一頁式非工程師可照步驟執行的《診所主機維運速查卡》（`docs/CLINIC_SERVER_OPS_QUICKCARD.md`）。

---

## 二、工作項目與實作設計

### Wave 1：正式規則庫安全還原（5,752 筆）與唯讀「舊碼差異分類分析」工具
1. **安全還原正式 `data/db/rules.sqlite3`（經使用者明確批准）**：
   - 步驟 1：執行 `systemctl --user stop elc-audit-engine.service`（確保無服務連線持有舊 inode）。
   - 步驟 2：檢查無 `-wal`/`-shm`/`-journal`/`rules.sqlite3.lock` 殘留（若有則中止且不自動刪除）。
   - 步驟 3：將現況 4,967 筆保留為快照 `/home/server/.gemini/antigravity-cli/brain/ccbc5d26-ad7c-4993-aa39-2936e9a8432e/scratch/rules.sqlite3.incident_4967.bak`（並記錄其 SHA-256）。
   - 步驟 4：唯讀驗證 `data/db/rules.sqlite3.bak.1795420942`（確認 `payment_rules == 5752`、`drug_rules == 11472`，並記錄其**完整 64 碼 SHA-256**）。
   - 步驟 5：複製至暫存檔再以 `os.replace` 原子還原為 `data/db/rules.sqlite3`，比對還原後**完整 64 碼 SHA-256** 與備份檔完全一致。
   - 步驟 6：啟動 `systemctl --user start elc-audit-engine.service`，確認 `/api/health` 與 `/api/rules/status` 回報 `payment_rows = 5752`、`drug_rows = 11472`、字面占位 `0`（註：上述正式服務 HTTP 請求會依預期於 `data/audit/access.log` 留下 `lan:127.0.0.1` 正常操作紀錄，與後續全套件測試「零測試寫入」分開核對）。
2. **擴充 `src/elc_audit_engine/rule_repository/audit_csv.py`**：
   - 新增純函式 `classify_payment_code_category(code: str) -> str`（互斥、確定性 8 類分類規則，先 `strip().upper()` 正規化）：
     1. 尾碼 `C` → `"C類一般診療項目"`
     2. 尾碼 `D` → `"D類（門診藥事服務費／助產）"`
     3. 尾碼 `E` → `"E類"`
     4. 前綴 `PT`/`OT`/`ST` → `"復健／職能／語言治療計畫碼（PT/OT/ST）"`
     5. 前綴 `P1`–`P9`/`PA`/`PB`/`PC` → `"P專案計畫碼（慢性病／家醫／牙醫／安寧等）"`
     6. 前綴 `N` → `"N類專案／護理／長照碼"`
     7. ASCII 純數字 `re.fullmatch(r"[0-9]+", code)` → `"預防保健／篩檢純數字碼（兒童衛教／癌症篩檢等）"`
     8. 其餘 → `"其他特項碼（K/F/G/H/Q/CH等非純數字碼）"`
   - 新增唯讀函式 `analyze_stale_payment_codes(db_path: str | Path, payment_csv_path: str | Path) -> dict[str, Any]`：
     - 前置檢查（明確錯誤語意，絕不拋裸 `KeyError` 或 `sqlite3.OperationalError`）：
       - `db_path` 不存在 → 拋 `FileNotFoundError`；
       - `payment_csv_path` 不存在 → 拋 `FileNotFoundError`；
       - CSV 以 `utf-8-sig` 讀取並先檢表頭必須含 `診療項目代碼`（若傳入藥品 CSV 等缺該欄者，拋 `ValueError("來源 CSV 缺少必要欄位：診療項目代碼")`）；
       - 以 SQLite 唯讀 URI（`?mode=ro`）開啟資料庫；若檔案損毀或非有效 SQLite（`sqlite3.DatabaseError`），統一轉拋 `ValueError("資料庫檔案損毀或非有效 SQLite 格式")`；若缺少 `payment_rules` 表，拋 `ValueError("資料庫缺少 payment_rules 資料表")`；
     - 雙方代碼皆採 `strip().upper()` 正規化（與 loader 一致）；
     - 計算 `stale_codes = sorted(db_codes - csv_codes)`，統計 `stale_count`、`by_category`、`ai_prefill_count`、`null_text_count`、`other_text_count`、`sample_codes_by_category`（每類最多 10 筆，無 PHI）；
     - **`recommended_mode` 嚴守不自動刪除原則（`sync_latest_rules.py:150`）**：
       - `stale_count > 0` → **一律回傳 `"upsert"`**（不建議自動刪除任何舊碼）；
       - `stale_count == 0` → 回傳 `"no_stale"`（來源檔已涵蓋 DB 全數代碼）。
   - 新增格式化函式 `format_stale_markdown(analysis: dict[str, Any]) -> str`，並於 CLI `main()` 新增 `--stale-vs-db <DB_PATH>` 選項：
     - 由程式自行檢查須搭配**恰好 1 份** `--csv <PAYMENT_CSV>`（未提供或超過 1 份時，於 stderr 印清楚錯誤訊息並回傳退出碼 `1`）；
     - 遇 `FileNotFoundError` / `ValueError` 時於 stderr 印清楚錯誤並回傳退出碼 `1`；
     - 支援 `--json-out` 與 `--md-out` 輸出。
3. **產出本機唯讀分類報告**：
   - 於還原 5,752 筆正式庫後，以 `python -m elc_audit_engine.rule_repository.audit_csv --stale-vs-db data/db/rules.sqlite3 --csv data/rules/醫療服務給付項目支付標準261119已填支付規定.csv --md-out /home/server/.gemini/antigravity-cli/brain/ccbc5d26-ad7c-4993-aa39-2936e9a8432e/scratch/stale_785_codes_analysis.md` 實測產出（確認 785 碼分類加總 ＝ 785、`recommended_mode == "upsert"`、正式 DB 完整 SHA-256 執行前後不變、零 PHI）。
4. **擴充測試**：`tests/test_rule_csv_audit.py`
   - 覆蓋 8 類分類（含 ASCII `^[0-9]+$` 純數字碼與非純數字特項碼）、UTF-8 BOM 與小寫空白代碼正規化；
   - 覆蓋 `stale_count > 0`（即使僅含「其他特項碼」）一律回 `"upsert"`，以及 `stale_count == 0` 回 `"no_stale"`；
   - 覆蓋所有邊界錯誤：DB 不存在、非 SQLite 損毀檔（`sqlite3.DatabaseError` → `ValueError`）、缺 `payment_rules` 表、傳入藥品 CSV（缺 `診療項目代碼`）、CLI 缺 `--csv` 與傳入 2 份 `--csv` 均回傳退出碼 `1`；
   - 驗證唯讀性（執行前後暫存 DB SHA-256 完全不變）。

### Wave 2：函式層／API／CLI／前端四重整表防誤觸＋《診所主機維運速查卡》與文件回歸測試
1. **函式層／API／CLI／前端四重整表防誤觸（`sync_latest_rules.py` + `api/routes/rules.py` + `static/index.html` + `static/js/workbench.js`）**：
   - **`src/elc_audit_engine/rule_repository/scripts/sync_latest_rules.py`（統一函式層護欄）**：
     - 定義常數 `REPLACE_CONFIRM_TOKEN = "REPLACE_RULES"`；
     - `sync_latest_rules(..., replace: bool = False, confirm: str | None = None, ...)` 於**函式最前端（在 `pick_latest`、取得 `.lock` 鎖檔與檢查側車檔之前）**驗證：若 `replace is True` 且 `confirm != REPLACE_CONFIRM_TOKEN`，立即拋 `ValueError("整表取代須明確提供 confirm='REPLACE_RULES' 以防誤刪既有規則")`；
     - CLI `main()` 新增 `--confirm` 旗標（`--replace` 必須搭配 `--confirm REPLACE_RULES`，缺漏或不符印錯誤訊息並以退出碼 `1` 中止）。
   - **`src/elc_audit_engine/api/routes/rules.py`**：`POST /api/rules/sync` 在呼叫 `sync_latest_rules()`（即任何鎖檔、側車檢查或寫入動作）**之前**先驗證 `replace` 為布林值，且當 `replace is True` 時驗證 `body.get("confirm") == "REPLACE_RULES"`，不符即回傳 **`422`**（確保即使有殘留側車檔或鎖檔，缺確認碼仍固定先回 `422` 而非 `409`）。
   - **`static/index.html`**：將 `data-action="syncRulesReplace"` 按鈕加上 `advanced-only` class（`class="u-s-36 advanced-only"`），日常醫師模式只顯示安全的「🔄 增量同步（保留舊碼）」。
   - **`static/js/workbench.js`**：`syncRulesReplace()` 改為以 `prompt()` 要求操作者明確輸入 `REPLACE_RULES` 才送出 `{ replace: true, confirm: 'REPLACE_RULES' }`。
   - **同步更新與新增測試**：
     - 更新既有 `replace=True` 測試呼叫點，保留原有測試意圖：`tests/test_rules_api.py:196`（側車 `-journal` `409` 測試改帶 `confirm: "REPLACE_RULES"`）、`tests/test_rules_api.py:203`（`replace=True` 替換與備份測試改帶 `confirm: "REPLACE_RULES"`）、`tests/test_rules_api.py` staging 測試與 `tests/test_rules_sync.py:221`（改帶 `confirm="REPLACE_RULES"`）；
     - 新增反向測試：API `replace: true` 缺／錯 `confirm` 回 `422`（含側車檔存在時仍先回 `422` 且不改 DB）、`sync_latest_rules(replace=True)` 缺 `confirm` 拋 `ValueError`、CLI `--replace` 缺 `--confirm` 退出碼 `1`；
     - `tests/test_workbench_static.py` 驗證 `syncRulesReplace` 按鈕具 `advanced-only`、`syncRules` 不具 `advanced-only`，且 `workbench.js` 的 `syncRulesReplace` 內含 `REPLACE_RULES`。
2. **新增 `docs/CLINIC_SERVER_OPS_QUICKCARD.md`**（UTF-8 無 BOM，單頁白話結構，零 PHI、零機敏金鑰）：
   - **第 1 節：一分鐘健康檢查**（`systemctl --user status elc-audit-engine.service elc-llama-server.service`、`curl -fsS http://127.0.0.1:5000/api/health`、`curl -fsS http://127.0.0.1:5000/api/rules/status`、`free -h`、`df -h`）。
   - **第 2 節：服務重啟與日誌檢視**（`systemctl --user restart ...`、`journalctl --user -u ... -n 50 --no-pager`、`loginctl show-user "$USER" -p Linger`）。
   - **第 3 節：每月規則庫更新 SOP**（Web UI `📚 規則` 上傳 CSV → **優先選「🔄 增量同步（保留舊碼）」**；明示「♻️ 整表更新」已收納至進階模式且須輸入 `REPLACE_RULES` 確認；嚴守實證語意記載：「部分既有代碼［例如門診藥事服務費、專案計畫碼與疫苗處置費等］未出現在特定期別的來源 CSV 檔中；這些代碼是否屬於有效給付項目，須對照健保署官方公告由人工確認」；附 CLI 同步與唯讀稽核 `audit_csv --stale-vs-db` 指令）。
   - **第 4 節：`409` 鎖檔與側車檔異常解除程序**（`cat data/db/rules.sqlite3.lock` → `ps -p <PID>` 確認行程已不存在 → 手動 `rm data/db/rules.sqlite3.lock`；遇 `-wal`/`-shm`/`-journal` 先確認服務狀態，嚴禁於服務寫入中強刪側車檔）。
   - **第 5 節：本機 ASR（`sherpa-onnx`）與 LLM（Gemma 4 E4B）模型快取檢查**（`bash deploy/install.sh --check-asr-models`、`bash deploy/install.sh --check-llama-cache`）。
   - **第 6 節：規則庫備份與還原**（停服 → 核對 `ls -la data/db/rules.sqlite3.bak.*` → 保留現況快照 → 複製還原 → 重啟服務 → 驗證 `/api/rules/status`）。
3. **新增 `tests/test_ops_quickcard_doc.py`**：
   - 驗證 `docs/CLINIC_SERVER_OPS_QUICKCARD.md` 存在、合法 UTF-8 且無 BOM；
   - 驗證涵蓋全部 6 大主題關鍵指令與安全警示（`elc-audit-engine.service`、`elc-llama-server.service`、`/api/health`、`/api/rules/status`、`rules.sqlite3.lock`、`ps -p`、`--check-asr-models`、`--check-llama-cache`、`--stale-vs-db`、增量同步警示）；
   - 驗證不含過時 `X-API-Key` 要求、不含 `curl | sh`、不含硬編碼診所外網 IP 或病患個資。
4. **文件索引同步**：
   - 在 `README.md` 補上 `docs/CLINIC_SERVER_OPS_QUICKCARD.md` 連結（不觸動「三軌控制台」既有文案，確保 `test_workbench_static.py:68-71` 通過）；
   - 同步更新 `.planning/STATE.md` 與 `.planning/ROADMAP.md`。

---

## 三、不變量與安全邊界（`AGENTs.md`）

1. **絕不自動刪除規則**：`analyze_stale_payment_codes` 在 `stale_count > 0` 時一律回傳 `"upsert"`；正式規則庫還原自核准之 `rules.sqlite3.bak.1795420942`（5,752 碼）並保留 4,967 碼事故快照。
2. **嚴格唯讀分析**：`analyze_stale_payment_codes` 使用 SQLite `?mode=ro` 唯讀連線，絕不修改 DB 或原 CSV。
3. **Zero PHI & 測試隔離**：分析工具與單元測試不讀 `TOTFA.zip`、不含病患資料；全套件執行前後，正式 `data/db/cases.sqlite3` 與 `data/audit/access.log` 維持零測試寫入。
4. **依賴穩定**：本 Phase 不更動 `pyproject.toml` / `uv.lock`（維持 `pydantic == 2.13.4`）。

---

## 四、驗收標準（獨立 Claude Plan Checker ＋ Tester）

- [x] 獨立 Claude Plan Checker 審核本修訂版計畫為 **PASS**。
- [x] 正式 `data/db/rules.sqlite3` 已依使用者核准改採「`251027` 基底 → `upsert 261119` → `261028` 藥品＋`rule_mapping` 空表」確定性等價重建為正式基準（因 `bak.1795420942` 於 16:11 連續 4 次 sync 觸發 `max_backups=5` 輪替淘汰），實測驗證：`payment_rules == 5752`、`drug_rules == 11472`、字面占位 `0`、785 碼 8 類分布（P 335 / 其他 173 / N 119 / PT/OT/ST 68 / 純數字 66 / D 13 / C 6 / E 5；AI 預填 401 / NULL 74）與關鍵申報碼 `48027P`／`48028P`／`05204D` 皆精準吻合、完整 64 碼 SHA-256 記錄為 `81de3061970a02d8e26d4f3a881dab473d6365414a3419eb0592fb3f372bd6ad`（並另存不受輪替影響之固定快照 `scratch/rules.sqlite3.pinned_5752.bak` 與 4,967 碼事故快照 `scratch/rules.sqlite3.incident_4967.bak`），服務重啟後 `/api/health` 與 `/api/rules/status` 正常。
- [x] `analyze_stale_payment_codes` 唯讀實測本機重建後 DB vs `261119`：785 碼 8 類加總 ＝ 785、AI 預填 401、`recommended_mode == "upsert"`、DB 完整 SHA-256 不變，並產出 `/home/server/.gemini/antigravity-cli/brain/ccbc5d26-ad7c-4993-aa39-2936e9a8432e/scratch/stale_785_codes_analysis.md`（無 PHI）；單元測試覆蓋 `"upsert"` 與 `"no_stale"` 及損毀 DB／缺表／藥品 CSV 等全邊界。
- [x] `sync_latest_rules()` 函式層、CLI（`--confirm REPLACE_RULES`）與 `POST /api/rules/sync` 之 `replace: true` 皆於鎖檔／側車檢查之前強制驗證 `confirm == "REPLACE_RULES"`（不符拋 `ValueError`／回 `422` 且不改 DB）；`static/index.html` 中 `syncRulesReplace` 具備 `advanced-only` 且 `workbench.js` 含 `REPLACE_RULES`；`docs/CLINIC_SERVER_OPS_QUICKCARD.md` 建立完成且 `tests/test_ops_quickcard_doc.py`、`tests/test_rule_csv_audit.py`、`tests/test_rules_api.py`、`tests/test_rules_sync.py`、`tests/test_workbench_static.py` 全數通過。
- [x] `.venv/bin/ruff check .` 零錯誤、全套件 `pytest` 實測 **1,763 passed, 3 skipped, 1 deselected, 0 failed**，且全套件測試期間正式 `cases.sqlite3`、`rules.sqlite3` 與 `access.log` 零測試寫入（正式服務自身的健康檢查紀錄另行區分）。
- [x] 獨立 Claude Tester 已完成全套件與內容等價驗證，並獲使用者明確核准接受 5,752 碼重建基準與更新本節驗收條文後執行 commit/push。
