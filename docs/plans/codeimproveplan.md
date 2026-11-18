# Elcinsurrence 程式改進計畫

> 分支：`feat/phase-17-evidence-vault`（對照 `main`）
> 依據：六份靜態研究筆記（架構、安全、測試與工具、可靠性與效能、文件已知問題、分支程式碼審查）與研究報告 `reports/Elcinsurrence code improvement research.md`
> 狀態：**僅靜態閱讀，未執行任何測試**。行號可能因未提交修改而位移，實作前請重讀程式。

---

## 一、總覽

最需要先處理的兩類風險：

1. **病歷（PHI）存取控制**：免認證端點可把全月病歷報告寄到任意信箱；前端含有與 `.env` 某把 API 金鑰相同的預設字串。
2. **送審內容與審查狀態正確性**：批次 XML 件數寫死為 1、LLM 失敗的案件被標為「已審查」、TOTFA 高風險篩選實際失效、橋接佇列會靜默丟件。

結構問題（大型模組、重複邏輯、缺少 CI）會放大上述風險，但應排在風險修復之後。

**重要原則**：多數高風險問題屬於「失敗時靜默」。失敗必須可見（回 503、標 `failed`、揭露筆數、拋出例外），不得由 `except` 或預設值吸收。

---

## 二、需要使用者先裁示的事項（P0-8）

以下矛盾無法由研究代為選擇，必須先決定，否則部分修法方向無法定案：

| 議題 | 來源 A | 來源 B | 需要決定 |
|---|---|---|---|
| **認證政策** | `progress.md:75-76`、`README.md` 將業務端點標為「選填」 | `api/security.py:30-46`：多個業務端點已強制認證；豁免清單仍含 `monthly_batch_report`、`printing.*` | 以程式或文件為準？PHI 讀取端點是否必須認證？ |
| **W1 狀態轉換** | `.planning/STATE.md:94` 視 `imported→appealed` 為非法 | `case_store/states.py:48-51` 註解為 D-01 合法設計 | 此轉換是否合法？ |
| **Phase 21 狀態** | `.planning/ROADMAP.md:40` 寫 0/3 未開始 | `packagers/nhi_case_packager.py`、`api/routes/bridge.py` 已存在 | 文件落後或程式超前？ |
| **閉環是否推進狀態** | `sampling_closed_loop.py:8`、`:214` 宣稱會流轉 | 閉環模組無 transition；只有單案 audit 路徑會推進 | 批次與單案閉環語意是否統一？ |
| **測試基線** | `deepflash4improve.md` 寫 277／374 passed | `progress.md:114` 寫 458；`.planning/STATE.md:36` 寫 363 | 以實際執行結果為準 |
| **測試旁路** | `AGENTs.md:86` 測試指令設定 `ELC_ALLOW_NO_AUTH_FOR_TESTS=1` | 安全建議不應存在於正式路徑 | 測試旗標改由 conftest 提供？ |
| **工具自動允許清單** | `reasonix.toml:2` 允許 `git push origin main`、`rm -rf data/uploads` | 屬權限設定，非專案文件 | 是否保留自動允許？ |

---

## 三、優先序清單

證據標籤：**已確認**＝讀碼或 grep 可見；**疑似**＝依程式形狀推論，需執行驗證；**推論**＝由結構推得，未實測。

### P0：立即處理（PHI 與送審正確性）

| 編號 | 項目 | 位置 | 證據 |
|---|---|---|---|
| P0-1 | **查證 `data/TOTFA.zip` 內容**。此檔被 git 追蹤，但 `.gitignore:45-47` 意圖排除 XML 與 PHI。若為真實病患資料，停止追蹤並評估 git 歷史清除。 | `data/TOTFA.zip`；`.gitignore:45-47` | 追蹤已確認，內容未確認 |
| P0-2 | `monthly.email_monthly_report` 移出免認證清單，加入 Origin 檢查與收件人限制 | `api/security.py:34-46`；`routes/monthly.py:175-206` | 已確認 |
| P0-3 | 前端移除硬編碼預設金鑰；確認 `ELC_API_KEYS` 是否已部署，必要時**輪換金鑰**。（金鑰值不在本計畫中記錄。） | `static/index.html` 預設字串與 localStorage 寫入處（約 :615、:2048、:2001-2005） | 已確認（精確字串比對） |
| P0-4 | 批次閉環在 LLM 判定失敗時標為 `failed`，不得寫入 `reviewed` | `static/index.html:1638-1647`；`sampling_closed_loop.py:73-88`；`api/routes/sampling.py:232-250`；AGENTs.md §2.2 | 已確認（code review，高） |
| P0-5 | 批次抽審 XML 的 `t9`、`t17`、`t37` 改為實際件數，不得寫死為 1 | `generators/sampling_xml.py:136-146`；對照 `電子抽審.md:989-993` | 已確認（code review，高） |
| P0-6 | 修正 TOTFA 高風險篩選：風險條件在筆數不足 50 時必為真，實際等同取前 50 筆。閾值收斂為具名常數，並補回歸測試 | `api/routes/sampling.py:656-693`（:678-680）；`api/routes/appeal.py:358-390`（:430-432） | 已確認（靜態推導） |
| P0-7 | 修正 `order_name` 未定義；`except Exception` 不得靜默吞掉 NameError（此為 main 上即存在的缺陷） | `api/routes/appeal.py:175`、`:180-181` | 已確認 |

### P1：修正功能與可靠性

| 編號 | 項目 | 位置 | 證據 |
|---|---|---|---|
| P1-1 | `list_pending` 改在 SQL 層以狀態過濾與分頁，取消 `limit=1000` 視窗 | `bridge_queue.py:88-102`；`case_store/store.py:398-420` | 已確認（高） |
| P1-2 | 橋接加入 SENDING 的 lease 逾時回收、FAILED 重試計數、CAS 條件更新 | `bridge_queue.py:31-34`、`:105-130`；`store.py:512-524` | 已確認（狀態機）；重複傳送為疑似 |
| P1-3 | `enqueue_job` 對 `target_id` 做 fullmatch 校驗並 URL 編碼 | `bridge_queue.py:47-53`、`:56-70` | 已確認 |
| P1-4 | 統一 SQLite 連線設定（WAL、busy_timeout），集中於 `get_connection` | `case_store/db.py:104-119`；`attachment_store.py:133`；`rule_repository/db.py:71-85` | 已確認 |
| P1-5 | `update_payload`、`save_review` 的讀改寫包進單一交易或加版本條件 | `store.py:512-524`；`sampling_closed_loop.py:184-189` | 程式形狀已確認；衝突頻率為疑似 |
| P1-6 | 審查 `DeductionRecord.raw` 的序列化路徑，遮罩出生日期；病歷號進入 LLM prompt 應評估 | `parsers/models.py:65`、`:95`；`comparator/evidence.py:82-83` | 已確認 |
| P1-7 | 審計 `path` 中的 vault_key 需遮罩；豁免端點的呼叫者應可辨識，不一律記為 `anonymous` | `api/security.py:119-127`、`:149-156`；`audit_log.py:34-38` | 已確認 |
| P1-8 | 修正 judger JSON 解析：正則改為非貪婪，或改用 `raw_decode` | `comparator/judger.py:44` | 已確認 |
| P1-9 | 閉環不得以範本 SOAP 作為判定依據；「查無規則」獨立為狀態，不併入「待判定」 | `sampling_closed_loop.py:86-88`、`:163-176`、`:225-235`；`monthly_pregen.py:99-103` | 已確認（中） |
| P1-10 | 統一批次讀取 `limit=1000`：比對總數，超過時揭露截斷 | `api/routes/sampling.py:140`；`appeal.py:228`、`:307`、`:326`；`store.py:401-403` | 已確認 |
| P1-11 | 統一規則查詢的 db_path 傳遞；例外只降級 `RuleRepositoryError`，其他例外不吞 | `sampling.py:176`、`:182-183`；`appeal.py:124`、`:268`、`:274-275`；`api/cases.py:39-43`；`pipeline.py:89-132` | 已確認 |
| P1-12 | 移除 bare `except:` | `sampling.py:665`、`:671`、`:676`；`appeal.py:366`、`:372`、`:377` | 已確認 |
| P1-13 | 將 `pypdf`、`Pillow` 移入 runtime dependencies（`uv sync --no-dev` 目前會 ImportError） | `pyproject.toml:31-34`；`attachment_store.py:20-22`；`generators/evidence_packet/pdf_exporter.py:4`；`image_processor.py:2` | 已確認（未實際執行） |
| P1-14 | 建立最小工具鏈：`[tool.ruff]`、pytest-cov、CI（`uv sync --locked`、pytest、ruff） | `pyproject.toml:44-50`；`.github/` 不存在 | 已確認 |
| P1-15 | `doc/tests/`（約 108 個測試）納入預設 pytest 路徑或 CI | `pyproject.toml:45`；`doc/tests/conftest.py:4` | 已確認 |
| P1-16 | `test_zip_import.py` 改用 fixture 或加 skip；`test_llama_smoke.py` 移出 collection 期 HTTP 探測；`test_chroma_store.py` 的 `skipif(True)` 改為正式 marker | `tests/test_zip_import.py:38,52`；`tests/test_llama_smoke.py:39-43`；`tests/test_chroma_store.py:119-122`、`:176-179` | 已確認 |
| P1-17 | 為 `appeal_linkage.py` 補單元測試（`seed=None`、duplicates、RuleRepositoryError 傳遞）；目前只靠 API 間接覆蓋 | `appeal_linkage.py:35`；`tests/test_phase20_stage_batch.py:191-249` | 已確認 |
| P1-18 | 修正統一報告的 onclick 注入：改用 data 屬性加事件委派，或以 `json.dumps` 編碼 | `unified_review_report.py:682-685`；`api/security.py:55-56`（CSP 含 unsafe-inline） | 已確認（需惡意匯入資料） |
| P1-19 | ZIP 解壓加入實際位元組上限（目前只檢查宣告大小）；`inspect_zip_contents` 加成員數與總量上限 | `evidence_vault.py:221-234`；`ingest/zip_support.py:70-78` | 已確認 |
| P1-20 | 移除 `config/llama_config.json:3` 的本機絕對路徑（`/home/hsu/...`），並清查 git 歷史 | `config/llama_config.json:3` | 已確認 |
| P1-21 | 正式啟動時拒絕 `ELC_ALLOW_NO_AUTH_FOR_TESTS`；測試旗標改由 conftest 提供 | `api/security.py:82-98`、`:92` | 已確認 |
| P1-22 | 確認 `generators/appeal.py` 的 `_split_reason` 是否仍做字元硬切，造成句中斷開 | `generators/appeal.py`（行號待重定位） | **未確認** |
| P1-23 | 確認 `evidence_vault.py:192` 的檔名寫入是否經過 `safe_filename` | `evidence_vault.py:192` | **未確認** |
| P1-24 | 使用者審視 `reasonix.toml` 的自動允許清單 | `reasonix.toml:2` | 內容已確認；風險判斷需使用者 |

### P2：重構與衛生

| 編號 | 項目 | 位置 |
|---|---|---|
| P2-1 | 拆分大型模組並抽出 service 層：`unified_review_report.py`（860 行）、`routes/sampling.py`（752 行）、`monthly_audit.py`（657 行）；路由內的業務流程（月批次上傳、寄信、稽核、his_integration）搬到 service | 架構筆記第 1、4 節 |
| P2-2 | 消除重複：`_stage2_view`／`_stage3_view`（回退鍵不同，縮圖上限一處具名、一處寫死）、ROC 民國日期解析（至少八處）、SOAP 範本讀寫（四處）、報告 HTML 的 JS／CSS／案件標題／規則區塊（兩檔重複）、`_save_stream` 與未使用的 `api/uploads.py:save_upload`、`_BATCH_RE` | `sampling.py:143-194`；`appeal.py:239-286`；`monthly_report_html.py`；`unified_review_report.py`；`api/uploads.py:18` |
| P2-3 | `create_app` 注入 Config，`migrate_legacy` 預設改為 False；設定統一為呼叫時讀取（目前 import 時與呼叫時並存） | `api/app.py:27-31`、`:62`、`:70-72`；`case_store/store.py:18`、`:119-120` |
| P2-4 | 確認位置後刪除 `require_api_key` 死碼（筆記記為 `auth.py`，本次 grep 未找到，需重新定位） | 待定位 |
| P2-5 | 效能：`get_rule` 以 db_path 為鍵做程序內快取；批次寫入改單一交易；消除 N+1（每案開連線、逐醫令查規則、報告 GET 每次重跑） | `rule_repository/__init__.py:45-118`；`case_store/monthly.py:83-96`；`monthly_audit.py:644-648`；`monthly_pregen.py:125-132`；`comparator/comparator.py:115-125`（以上為推論，未實測） |
| P2-6 | `audit_batch` 改為串流篩選，只保留 flagged 案件 | `monthly_audit.py:637-656`；`page_size=500` 只限制 DB 讀取 |
| P2-7 | `table_ocr._get_engine` 惰性單例加 Lock | `ingest/table_ocr.py:45-70` |
| P2-8 | 長時間 LLM 批次改背景工作與進度查詢；pregen 設總時限（上限 50 筆、串行可能阻塞約 2.5 小時） | `api/routes/monthly.py:283-299`；`monthly_pregen.py:154-161` |
| P2-9 | 例外記錄類別而非全文；`soap_advice` 不得把 `str(exc)` 回傳前端；traceback 不含病歷片段 | `comparator/soap_advice.py:198-205`；`judger.py:141-146`；`api/errors.py:58-61`；`printing.py:134` |
| P2-10 | 安全衛生：`safe_filename` 改 fullmatch（目前 `$` 允許結尾換行）；innerHTML 改 textContent；拆出 inline script 後移除 CSP unsafe-inline；附件錯誤改固定訊息；`xml.etree` 改 defusedxml；`sync_latest_rules` 表名白名單；失敗認證節流；Werkzeug 請求日誌遮罩 path | `safe_paths.py:25`；`static/index.html:1622-1624`；`api/security.py:55-56`；`attachments.py:82` |
| P2-11 | 業務規則常數集中管理（閾值 1000、350、5.0、50、Phase 規則等散落多處） | `monthly_audit.py:547`、`:552`；`monthly_report_html.py:75-77`；`unified_review_report.py:630`；`sampling.py:678` |
| P2-12 | 文件同步：`deepflash4improve.md` §7 行號失效、`AGENTs.md` blueprint 清單缺 bridge／his_integration／rules／vault、`SUMMARY.md` 易誤認（實為 Phase 13-02 摘要）、`progress.md:162` 所稱已移除的 `HANDOFF.json` 仍存在、`STATE.md` frontmatter 與正文矛盾 | 文件筆記第 3、5 節 |
| P2-13 | 外部條件（非程式待修，近期不排入）：Local Gateway 七元件、NHI_EIIAPI.DLL、雲端病歷 Provider、官方欄位契約 | `progress.md:69`、`:83-84`、`:121`、`:123`；`.planning/ROADMAP.md:60`、`:79` |

---

## 四、建議執行順序

1. **裁示**：完成 §二 的決定，特別是認證政策（決定 P0-2 的修法方向）。
2. **查證**：P0-1（TOTFA.zip 內容）與 P0-3（金鑰是否已部署）。
3. **建立基線**：執行 `uv run pytest tests` 與 `uv run pytest doc/tests`，記錄真實通過數，以單一來源更新文件。
4. **把發現變成失敗測試**：每個 P0、P1 項目先寫一個會失敗的回歸測試，再修復。
5. **依 P0 → P1 修復**，每項獨立提交。
6. **工具鏈**：ruff、coverage、CI 在修復穩定後加入，避免一次改太多。
7. **P2 重構**：在行為測試保護下拆分模組與抽出 service 層。

---

## 五、設計原則（修復時遵守）

- **失敗必須可見**：LLM 失敗標 `failed`；查詢截斷揭露 count；規則查詢只降級 `RuleRepositoryError`；不得以 `pass` 或預設值吸收例外。
- **三種狀態不混用**：支持、不支持、待判定、查無規則應各自獨立（AGENTs.md §2.2）。
- **引文必須來自病歷原文**：範本 SOAP 不得作為判定依據（AGENTs.md §2.1）。
- **PHI 不進入日誌、錯誤訊息或未經遮罩的 prompt**。

---

## 六、未驗證事項

- 本計畫所有結論來自靜態閱讀，**未執行測試**。
- 研究中標為「未確認」的 P1-22、P1-23、P2-4 需先重讀程式。
- 行號以研究時的 commit `6ea9be6` 與當時的未提交修改為準，部分已位移。
