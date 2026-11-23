# Phase 36 計畫：工作台版面釋放、規則庫更新機能升級（套用 261119／261028）與臨床 `pending` 精準化

**狀態**：已完成（已通過獨立 Claude Plan Checker 與 Tester 驗收 PASS：全套件 1,755 passed, 0 failed，正式 cases.sqlite3 與 access.log 零測試寫入，已套用 261119/261028 並完成重啟健康檢查與 sample_03 實音驗證）
**建立日期**：2026-11-23
**前置依賴**：Phase 35（`9819fcb`，規則庫唯讀稽核、NULL 契約統一、全套件測試隔離 1,748 passed / 0 failed）

---

## 一、背景與實查事實

1. **工作台版面空間釋放**：
   - `static/index.html:60-73` 頂端的 3 步驟導引列（`① 上傳申報檔 → ② 智慧檢查 → ③ 下載送審檔`，`id="workflow-stepper"`）佔用垂直空間且日常操作不需要，需移除以把垂直空間讓給主工作區 `<main>`。
2. **最新規則來源檔已就位（`data/rules/`）**：
   - `醫療服務給付項目支付標準261119已填支付規定.csv`：**4,967 筆**（相較舊 `251027` 之 2,669 筆**淨增 2,298 筆**：新增 3,083 碼、另有 785 個舊 `251027` 代碼不在 `261119` 中；0 筆字面 `null`）。
   - **正則口徑與偵測數對照**（新正則 `(?<![A-Za-z0-9])(\d{5}[A-Za-z])(?![A-Za-z0-9])` 補齊中文緊鄰偵測，會較舊 `\b` 檢出更多引用）：
     - `251027`：舊 `\b`（非標準尾碼 29 列／引用不存在碼 62 列）→ 新正則（非標準尾碼 **35 列**／引用不存在碼 **80 列**）。
     - `261119`：舊 `\b`（非標準尾碼 1 列／引用不存在碼 17 列）→ 新正則（非標準尾碼 **3 列**／引用不存在碼 **33 列**）；完整 3 筆非標準尾碼為 `51002C`→`51002D`、`92043C`→`92043D`、`97421B`→`97405K/97407K/97409K/97411K`。
   - `藥品項查詢項目檔261028AI  摘要支付價大於0.csv`：**11,472 筆**（25 MB，涵蓋原 DB 全部 11,273 碼且新增 199 碼，0 碼遺失，含 `支付價` 與 `AI-note`）。
   - **重要不變量（`sync_latest_rules.py:150`）**：「自動刪除規則不可接受，是否下架需由人工決定」。因此本機更新預設採 **`upsert`（`replace=False`）** 模式，更新全部 4,967 筆給付項目與 11,472 筆藥品、保留 785 個舊碼不刪除，並產出「785 筆不在 `261119` 的代碼清單」供人工審核後再決定是否日後整表取代。
   - 既有規則管理機制存在 5 個實戰缺口：
     1. `api/app.py` 全域 `MAX_CONTENT_LENGTH = 26 MB`，與 `rules.py` 宣告的 `MAX_RULE_CSV_BYTES = 64 MB` 不一致，導致 25–35 MB 藥品 CSV 經瀏覽器上傳易觸發 `413`。
     2. `sync_latest_rules()` 兩表分開寫入非原子，且缺 `-wal`/`-shm`/`-journal` 側車檔檢查與自動備份；`POST /api/rules/sync` 無法選 `replace` 或回傳品質摘要；缺 `GET /api/rules/status`。
     3. `pick_latest()` 版本 regex `\d{6}` 若遇 8 位數字（如 `20261119`）會誤擷取前 6 碼 `202611`。
     4. 前端 `📚 規則` 按鈕被 `advanced-only` 隱藏，且未顯示目前規則庫筆數與來源版本。
     5. `audit_csv.py` 的 `_CODE_REF_RE` 使用 `\b` 會漏抓中文緊鄰醫令碼（如 `如51002D`）；`_AI_PREFILL_MARKERS` 把 `261119` 正常條文前綴 `"審查原則："` 誤標為 AI 預填（3,097 筆）。
3. **`sample_03` `placeholder` 誤判根因**：
   - 實測確認 `sample_03` A 欄唯一命中 `_PLACEHOLDER_RE` 的詞為 `pending`（臨床待檢驗結果語境如 `urinalysis pending`），而非模型留空佔位。
4. **未追蹤大檔確認**：
   - `Wavesample/` 已不在本機專案目錄，需同步清除 `.planning/STATE.md` 過時註記。

---

## 二、工作項目與實作設計

### Wave 1：移除 3 步驟導引列釋放工作台空間
1. **更新 `static/index.html`**：
   - 移除第 60–73 行的 `<div id="workflow-stepper" class="step-indicator">...</div>`；因 `body` 為 `flex-direction: column; height: 100vh`，`<main>` 自動擴展回收該區塊高度。
   - **不動** `static/css/workbench.css` 中 `01e1a13` 基準 CSS（維持 `test_extracted_css_and_js_preserve_head_content` 契約）；`static/js/workbench.js:2700` 之 `updateWorkflowStep` 已有 `if (!stepper) return;` 守衛（L2702）不報錯。
2. **同步前端測試**：
   - `tests/test_workbench_static.py`：`test_stepper_and_empty_state` 改斷言 `id="workflow-stepper"` **不在** HTML 中，並保留 `id="empty-state-guide"` 與空白引導斷言。
   - `tests/test_workbench_e2e_smoke.py`：改斷言 `id="workflow-stepper"` **不在** HTML 中。
   - 確認 `tests/test_phase32_readiness.py:177` 維持綠燈。

### Wave 2：規則庫品質稽核精準化、對照報告與完整原子更新功能（套用 `261119`／`261028`）
1. **精準化 `src/elc_audit_engine/rule_repository/audit_csv.py`**：
   - `_CODE_REF_RE` 改為 `re.compile(r"(?<![A-Za-z0-9])(\d{5}[A-Za-z])(?![A-Za-z0-9])")`，正確抓出中文括號或中文緊鄰之醫令碼引用（如 `（92043D）`、`如51002D`）。
   - `_AI_PREFILL_MARKERS` 改為 `("審查原則：(202", "Version 1.0", "版 1.0", "```", "**")`，不再誤報 `261119` 正常條文之「審查原則：」開頭。
   - 擴充 `tests/test_rule_csv_audit.py` 覆蓋中文緊鄰異常尾碼檢出與正常「審查原則：」不被誤報為 AI 預填。
2. **產出唯讀版本對照與下架候選報告（無 PHI）**：
   - 輸出至完整路徑 `/home/server/.gemini/antigravity-cli/brain/ccbc5d26-ad7c-4993-aa39-2936e9a8432e/scratch/rules_251027_vs_261119_vs_odt.md`：
     1. 逐筆對照 `251027` 原本的 29 筆異常尾碼在 `260801`、`261119` 與官方 `officialdocument/審查注意事項/完整給付規定1140221.odt` 的實際條文；
     2. 列出「785 個存在於原 `rules.sqlite3` 但不在 `261119` 中的給付代碼」摘要與清單，供人工確認後才決定是否日後整表下架。
   - 嚴格唯讀，絕不修改任何 CSV 或捏造條文，輸出不含任何 PHI。
3. **升級規則同步與狀態檢視（`sync_latest_rules.py`、`api/routes/rules.py`、`api/security.py`）**：
   - **`api/security.py`**：於 `before_request` 中對 `request.path == "/api/rules/upload"` 設定 `request.max_content_length = 65 * 1024 * 1024`（覆蓋 64 MB 藥品 CSV + 1 MB 表單餘裕）；其餘路由維持全域 `26 MB` 不變。
   - **`sync_latest_rules.py`**：
     - `_VERSION_RE` 改為 `re.compile(r"(?<!\d)\d{6}(?!\d)")`（避免 8 碼日期被誤抓前 6 碼），並補測試。
     - 新增 `RulesSyncConflictError(RuntimeError)` 與 `_assert_no_sidecars(db_path)`：同時檢查 `-wal`、`-shm`、`-journal` 三種 SQLite 側車檔，任一存在即拋出例外（API 回 `409 Conflict`），絕不自行刪除側車檔。
     - 新增 `rules_status(db_path=None, rules_dir=None) -> dict`：唯讀回報目前 `rules.sqlite3` 之 `payment_rules`／`drug_rules` 列數與 `NULL` 列數，以及 `rules_dir` 內偵測到的最新 `payment_file`／`drug_file` **僅 basename**（無伺服器絕對路徑）與檔案大小。
     - **整庫原子替換與行程間鎖（消除雙表半切換與併發覆蓋）**：升級 `sync_latest_rules(..., replace=False, backup=True, max_backups=5, include_audit=True)`：
       1. 以 `os.open(f"{target}.lock", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)` 取得排他行程鎖並寫入 `pid=<PID>` 與 `created_at=<UTC ISO>`（遇 `FileExistsError` 立即拋 `RulesSyncConflictError`，API 回 `409 Conflict`、**絕不自動刪除鎖檔**，訊息明確提示操作者確認無同步行程執行中後手動移除 `rules.sqlite3.lock` 再重試），正常路徑於 `try/finally` 釋放移除鎖檔；
       2. 取得鎖後檢查 `_assert_no_sidecars(target)`（`-wal`/`-shm`/`-journal` 存在即拋 `RulesSyncConflictError`，回 `409` 且絕不自行刪除側車檔）；
       3. 建立同目錄暫存庫 `rules.sqlite3.staging.<uuid>`（若原 `target` 存在，先 `shutil.copy2(target, staging)` 以完整保留 `rule_mapping` 表及 `upsert` 舊列）；
       4. 在 `staging` 上依序執行 `load_drug_csv_full(..., replace=replace)` 與 `load_payment_csv(..., replace=replace)`；任一步失敗即清理 `staging`，原 `target` 絲毫不動；
       5. 兩表皆成功後，若原 `target` 存在且 `backup=True`，先備份為同目錄 `rules.sqlite3.bak.<timestamp>` 並依時間戳淘汰超過 `max_backups`（預設 5 份）之最舊備份（僅限 `rules.sqlite3.bak.*`，絕不碰其他檔案）；
       6. 以 `os.replace(staging, target)` 單一原子替換整庫；
       7. 回傳 `SyncResult` 附帶 `backup_file`（僅 basename 或 `None`）與唯讀 `audit` 品質計數摘要。
   - **`api/routes/rules.py`**：
     - 新增 `GET /api/rules/status`（受院內信任網段保護，不豁免審計）。
     - 升級 `POST /api/rules/sync`：接受可選 JSON 物件 body `{"replace": bool}`（未帶 JSON body 時預設 `False`；傳入非物件 JSON 如陣列回 `400`；若 `replace` 非布林值，於任何寫入前先回 `422`；遇 `RulesSyncConflictError` 回 `409`）。
   - **測試隔離與覆蓋**：`tests/test_rules_api.py` 與 `tests/test_rules_sync.py` 所有新測試均明確指定 `tmp_path` 之 `ELC_RULES_DB_PATH` 與 `ELC_RULES_DIR`（絕不碰正式 `data/db/rules.sqlite3`），驗證 `GET /api/rules/status`、`/api/rules/upload` 單路由 65 MB、`replace=True`、非布林 `422`、`-wal`/`-journal` 側車檔 `409`、預放殘留 `.lock` 檔回 `409`（含手動移除指引且不自動刪除鎖檔）、半切換失敗不損原庫、備份輪替上限 5 份與 `pick_latest` 6 碼邊界。
4. **升級前端規則庫更新面板（`static/index.html` + `static/js/workbench.js`）**：
   - `static/index.html:104-111`：`btnQuickRules` 移除 `advanced-only` 使日常醫師模式亦可展開；面板內新增目前版本狀態列（`id="rulesCurrentInfo"`）與「🔄 增量同步（保留舊碼）」及「♻️ 整表更新（套用最新版）」按鈕（依 `docs/plans/Fable5.2improvplan.md` E4 白話規範，不含禁止工程術語、零 inline style、零 `on*` 屬性）。
   - `static/js/workbench.js`：於 `ACTIONS` 白名單（L2802）新增 **`syncRulesReplace`**（`syncRules`、`uploadRuleCsvChange`、`toggleQuickPanel` 已於白名單內）；展開 `rules` 面板時自動呼叫 `loadRulesStatus()`（`GET /api/rules/status`）顯示目前筆數與最新來源檔名；`syncRulesReplace` 經 `confirm()` 二次確認後送 `{"replace": true}`，全部文字均以 `textContent` 安全寫入。
5. **本機正式 `data/db/rules.sqlite3` 以安全 `upsert` 套用 `261119` ＋ `261028`**：
   - 於維護操作下執行 `sync_latest_rules(replace=False, backup=True)`（自動備份原庫、原子替換整庫、保留 785 個舊碼不自動刪除），記錄替換前後 SHA-256，隨後重啟 `elc-audit-engine.service` 切換新 inode（避免運作中連線讀取舊 inode 或發生 lock 競爭），並實測 `GET /api/rules/status` 驗證筆數（`payment_rules = 5,752`［4,967 最新＋785 保留舊碼］、`drug_rules = 11,472`、字面占位 `0`）。

### Wave 3：臨床 `pending` 精準化與環境收尾
1. **精準化 `src/elc_audit_engine/comparator/soap_advice.py`**：
   - `template` profile 維持原 `_PLACEHOLDER_RE` 完全不變（任何 `pending` 皆阻斷）。
   - `clinical` profile 採兩步防繞過檢核（在 `_PLACEHOLDER_RE` 前執行）：
     1. **第一步（硬攔截）**：`_BARE_DIAG_PENDING_RE = re.compile(r"\b(?:diagnosis|diagnoses|diagnostic|differential|ddx|dx|icd(?:\s*-?\s*10)?|code|codes|assessment|impression|plan|treatment)\s+pending\b", re.IGNORECASE)` — 若命中（包含 `"diagnosis pending ultrasound"`、`"differential pending ultrasound"`、`"ddx pending urinalysis"`、`"dx pending ultrasound"`、`"ICD 10 pending ultrasound"`、`"ICD pending urinalysis"`、`"plan pending ultrasound"`、`"treatment pending urinalysis"`、`"impression pending lab"`），**直接判定為 `placeholder` 阻斷，絕不豁免**。
     2. **第二步（精準白名單剝離）**：僅於第一步未命中時，剝離緊鄰明確臨床檢驗／影像／病理／處置追蹤語境之 `pending` 片語（前置 `pending\s+(?:urinalysis|ua|lab(?:s|oratory)?|imaging|x-?ray|ultrasound|sonography|ct|mri|ekg|ecg|culture|biopsy|pathology|results?|workup|evaluation|follow-?up|consult(?:ation)?|review)\b` 或後置 `\b(?:urinalysis|ua|lab(?:s|oratory)?|imaging|x-?ray|ultrasound|sonography|ct|mri|ekg|ecg|culture|biopsy|pathology|results?|workup)\s+pending\b`），再套用原 `_PLACEHOLDER_RE`；任何裸 `"pending"`、`"[pending]"`、`"not documented"`、`"N/A"`、`"TBD"`、`"待補"` 依然嚴格攔截。
   - 擴充 `tests/test_clinical_soap_retry.py` 驗證正反雙向完整矩陣（放行 `"dysuria (R30.0), urinalysis pending"` 與 `"pending urinalysis"`；嚴格攔截 `"diagnosis pending ultrasound"`、`"differential pending ultrasound"`、`"ddx pending urinalysis"`、`"dx pending ultrasound"`、`"ICD 10 pending ultrasound"`、`"ICD pending urinalysis"`、`"plan pending ultrasound"`、`"treatment pending urinalysis"`、`"impression pending lab"`、`"[pending]"`；且 `template` profile 仍攔截 `"urinalysis pending"`）。
   - 於隔離環境實測 `sample_03` 驗證修正效果（零 PHI 輸出）。
2. **文件與狀態同步**：
   - 更新 `.planning/STATE.md`（移除已不存在的 `Wavesample/` 註記，記錄 Phase 36 成果與 `261119`/`261028` 同步版本）與 `.planning/ROADMAP.md`。

---

## 三、不變量與安全邊界（`AGENTs.md`）

1. **絕不捏造規則或臨床事實**：規則對照報告與 `audit_csv` 嚴格唯讀；臨床 `pending` 採兩步防繞過檢核，絕不放水裸診斷待定或佔位符。
2. **不自動刪除既有規則**：本機更新預設採 `upsert`（保留 785 個不在 `261119` 的舊碼）並產出候選清單供人工決定。
3. **原子替換與側車防護**：暫存庫建完驗證後單一 `os.replace` 替換整庫，遇 `-wal`/`-shm`/`-journal` 回 `409` 不自行刪除，替換後重啟服務切換 inode。
4. **Zero PHI & 測試隔離**：所有新規則測試明確設定 `tmp_path` DB/目錄；全套件維持對正式 `data/db/cases.sqlite3` 與 `data/audit/access.log` 零測試寫入；所有報告與輸出不含 PHI。
5. **依賴穩定**：本 Phase 不更動 `pyproject.toml` / `uv.lock`（維持 `pydantic == 2.13.4`）。

---

## 四、驗收標準（獨立 Claude Plan Checker ＋ Tester）

- [ ] 獨立 Claude Plan Checker 審核本修訂版計畫為 **PASS**。
- [ ] `static/index.html` 已移除 `workflow-stepper`（①→②→③），CSP 嚴格 `'self'`、0 處 inline style、0 處 `on*` 屬性、所有 `data-action` 皆在 `ACTIONS` 白名單。
- [ ] 新正則 `audit_csv.py` 實測計數與預期吻合：`251027` 非標準尾碼 35 列／缺碼引用 80 列；`261119` 非標準尾碼 3 列（`51002C`、`92043C`、`97421B`）／缺碼引用 33 列／`ai_prefill_marker` 0 列。
- [ ] `GET /api/rules/status`、`POST /api/rules/upload`（單路由 65 MB 上限）、`POST /api/rules/sync`（`O_EXCL` 行程鎖 `409`、整庫原子替換、`-wal`/`-shm`/`-journal` `409` 防護、自動備份保留上限 5 份、唯讀 `audit` 摘要、`replace` 參數驗證）全數實作並通過隔離測試。
- [ ] 本機 `data/db/rules.sqlite3` 以安全 `upsert` 套用 `261119` ＋ `261028`（`payment_rules = 5,752`、`drug_rules = 11,472`、字面占位 `0`），重啟 `elc-audit-engine.service` 後 `/api/rules/status` 與 `/api/health` 正常。
- [ ] 產出 `/home/server/.gemini/antigravity-cli/brain/ccbc5d26-ad7c-4993-aa39-2936e9a8432e/scratch/rules_251027_vs_261119_vs_odt.md`（無 PHI，含 35 筆異常尾碼對照與 785 筆舊碼清單）。
- [ ] `sample_03` 隔離實測確認臨床 `pending` 精準化生效，同時完整 9 組反向矩陣（`"diagnosis pending ultrasound"`、`"differential pending ultrasound"`、`"ddx pending urinalysis"`、`"dx pending ultrasound"`、`"ICD 10 pending ultrasound"`、`"ICD pending urinalysis"`、`"plan pending ultrasound"`、`"treatment pending urinalysis"`、`"impression pending lab"`）皆被嚴格攔截。
- [ ] `.venv/bin/ruff check .` 零錯誤、全套件 `pytest` 維持 **0 failed** 且正式 `cases.sqlite3` / `access.log` 零測試寫入。
- [ ] 獨立 Claude Tester 驗收 **PASS**，確認後再依使用者指示決定是否 commit/push。
