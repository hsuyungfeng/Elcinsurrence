# Elcinsurrence 既有文件已知問題盤點與程式碼對照

**研究範圍**：`/home/hsu/Desktop/Elcinsurrence`（分支 `feat/phase-17-evidence-vault`，以 `git branch --show-current` 所見為準）。
**方法**：本地靜態閱讀文件與原始碼，以 `grep` 定位，引用格式為 `路徑:行號`（本地來源，無 URL）。未執行 pytest，測試基線數字僅為文件宣稱，未經驗證。
**讀取範圍**：`deepflash4improve.md`（全文）、`progress.md`（第 55–175 行之待辦與變更記錄）、`電子抽審.md`（以關鍵字掃描，屬法規背景）、`README.md`（以關鍵字與路由表掃描）、`AGENTs.md`（全文）、`SUMMARY.md`、`reasonix.toml`、`.planning/ROADMAP.md`、`.planning/STATE.md`、`.planning/PROJECT.md` 與 `.planning/phases/` 目錄。未讀 `TOTFA.xml`、`.venv/`、`graphify-out/`、`officialdocument/`。

**狀態標記說明**：已解決／部分解決／未解決／未確認（未能在本次閱讀中定位或覆核，需另行驗證）。行號以本次 grep 結果為準，`deepflash4improve.md` §7 內的舊行號多數已因重構位移，不可直接沿用。

---

## 關鍵問題一：deepflash4improve.md 與 progress.md 的已知問題，目前在程式碼中的狀態為何？

### Takeaway

`deepflash4improve.md` 的 P0/P1 項目大多已在程式碼中落實（P0-1、P0-2、P1-1～P1-4、P1-6 的 flask 部分），但文件引用的 `server.py` 行號已失效，因為 `server.py` 已縮為 42 行的工廠呼叫，路由移至 `api/routes/`。目前仍確定未解決的主要是：`config/llama_config.json` 的本機絕對路徑仍被版控、`judger.py` 的 JSON 解析正則為貪婪匹配、`DeductionRecord.raw` 保留未遮罩出生日期、`Local Gateway` 七元件與 NHI_EIIAPI DLL 全數未開工、雲端病歷 Provider 未實作、ruff 未設定。

### Cited Findings

#### A. deepflash4improve.md 第三節（原始 P0～P2）

| 編號 | 項目 | 狀態 | 證據 |
|---|---|---|---|
| P0-1 | soffice 探測太弱 | 已解決 | `src/elc_audit_engine/rule_repository/docx_tree/doc_converter.py:47` `soffice_is_functional()` 改為真實轉檔探測 |
| P0-2 | `get_rule` 把所有 `sqlite3.Error` 降級為 not_found | 已解決 | `src/elc_audit_engine/rule_repository/__init__.py:117-120` 系統性故障改拋 `RuleRepositoryError`；`rule_repository/errors.py` 定義例外 |
| P1-3 | docx 表格未併入 `full_text` | 已解決（文件宣稱，程式未逐行覆核） | 文件 `progress.md:136` 記載 165→282 chunks；對應模組 `rule_repository/docx_tree/extractor.py` |
| P1-4 | `rule_mapping` 無版本追蹤、無增量 | 已解決 | `rule_repository/mapping/versions.py:23-42`（檔名日期＋SHA-256 前 12 碼）、`versions.py:45-51`（docx 語料 hash）、`rule_repository/embeddings/chroma_store.py:101-145`（`source_version` 綁定與重建） |
| P1-5 | ChromaDB `skipped` 不可觀測（無 log、無 count 健康檢查） | 部分解決 | 版本綁定與重建已做（`chroma_store.py:101-145`）；`main()` 健康檢查與 `logger.error` 未確認 |
| P1-6 | 未用依賴、README 管線、ruff | 部分解決 | `pyproject.toml:9-20` 依賴已收斂（flask 已加回，見 P0-2）；`README.md:318-327` 管線指令存在；**ruff 未設定**：`pyproject.toml` 無 `[tool.ruff]`，根目錄無 `ruff.toml`，`.github` 無 CI 設定 |
| P2-7 | `build_all_trees` 的 zip 配對脆弱 | 已解決（推定） | `rule_repository/docx_tree/tree_builder.py:38-59` 改用 `converted_key_by_path` 顯式映射並比對檔名集合 |
| P2-8 | `_score_candidate` 逐字掃描效能 | 未確認 | 函式仍在 `rule_repository/mapping/build_mapping.py:73`，本體未重讀；屬建置期，優先度低 |
| P2-9 | `parse_flexible_date` 未驗證曆法、dead try | 已解決 | `rule_repository/loaders/dates.py:49-80`：以 `date(year, month, day)` 驗證，`ValueError` 回 `None` 並記 warning |
| P2-10 | `patterns.py` depth 6 未覆蓋全語料 | 未確認 | 未重讀 `docx_tree/patterns.py` 與對應測試 |
| 第五節 | 複雜度熱點（`build_rule_mapping` 等）建議抽函式 | 未確認 | `build_mapping.py` 仍為單檔批次邏輯，未重新量測複雜度 |

#### B. deepflash4improve.md 第七節（2026-08-04 全項目審查）

| 編號 | 項目 | 狀態 | 證據 |
|---|---|---|---|
| P0-1 | `server.py` 假邏輯＋危險預設（`0.0.0.0`、`debug=True`） | 已解決 | `server.py:24-42` 改為 `create_app()` 工廠呼叫，預設 `127.0.0.1`、`debug` 預設關閉，可由 `ELC_SERVER_*` 覆寫；端點接線位於 `api/routes/sampling.py`、`api/routes/appeal.py`（未逐行覆核內容） |
| P0-2 | flask 依賴漂移 | 已解決 | `pyproject.toml:17` `"flask>=3.0"` |
| P0-3 | `.gitignore` 未排除 PHI 輸出目錄 | 部分解決 | `.gitignore:29-31` 已加 `data/output/*`；`.gitignore:32-38` 已加 `data/uploads/`、`data/attachments/`、`data/audit/`；`.gitignore:41` `.planning/HANDOFF.json`。**未解決**：`config/llama_config.json:3` 仍含 `/home/hsu/llama.cpp/models/...` 絕對路徑，且 `git ls-files config` 確認該檔已被版控；git 歷史清查未見紀錄 |
| P1-1 | 全「待人工」被歸為「裸奔」 | 已解決 | `comparator/support.py:41-45`（全部待人工回 `None`，`manual = any(...)`）；`README.md:23-31` 三種非結論狀態已文件化 |
| P1-2 | LLM prompt 注入面 | 已解決（緩解，非證明安全） | `prompt_safety.py:30` `fence()`；呼叫點 `comparator/judger.py:127-129`、`comparator/narratives.py:96-100`、`comparator/soap_advice.py:174-176`、`rule_repository/mapping/prompts.py:53`。下游白名單 `VERDICTS` 仍是真正邊界（`progress.md:252`） |
| P1-3 | 路徑穿越 | 部分解決 | `safe_paths.py:32` `safe_filename()`；已套用於 `record_aggregator/providers.py:154`、`attachment_store.py:200`、`generators/appeal.py:570`、`generators/reinforcement_report.py:189`、`generators/appeal_print/__init__.py:143`、`generators/evidence_packet/__init__.py:84`、`auth.py:108`、`case_store/store.py:27`。**未確認**：`evidence_vault.py:192` 的 `os.path.basename(target)` 寫入路徑是否經 `safe_filename` 校驗 |
| P1-4 | CSV 版本僅取檔名、ChromaDB 無版本綁定 | 已解決 | 見 A 節 P1-4 證據 |
| P1-5 | 前端 XSS 與入參零校驗 | 部分解決 | CSP 已設定：`api/security.py:136`；Google Fonts 外鏈已移除（`static/` 無 `fonts.googleapis` 命中）；`renderCaseList` 之 innerHTML 樣板已移除（文件 `progress.md:256-257`）；`api/validation.py` 存在。**未解決**：`static/index.html:1622-1624` 仍以模板字串 `pText.innerHTML` 寫入 `${caseId}`（風險低，因 case_id 多為伺服器產生的 `SAMP-…`，但應改 `textContent`）；`index.html:949/982/1016` 之 `innerHTML = ''` 為清空，無注入風險 |
| P1-6（新） | 審計日誌與認證清單共用、審計消失 | 已解決 | `api/security.py:24` `AUDIT_EXEMPT_ENDPOINTS` 與 `security.py:34` `AUTH_EXEMPT_ENDPOINTS` 已拆開；`security.py:149` 審計寫入只看 `AUDIT_EXEMPT_ENDPOINTS` |
| P2 | `parsers/soap.py:80-92` 空標記行落入 unclassified | 未確認 | 該段邏輯已改為關鍵詞評分（`parsers/soap.py` 約 85–95 行），舊行號失效，未能確認原 bug 是否仍在 |
| P2 | `comparator/narratives.py:80-81` LLM 失敗 `except: return []` | 部分解決 | 現存 `except json.JSONDecodeError` 回 `None`（`narratives.py:46-54`）；LLM 呼叫層失敗路徑未重讀 |
| P2 | `parsers/deduction.py:110-113` `_parse_int` 靜默截斷 | 已解決 | `parsers/deduction.py:104-112` 小數、科學記號、非數字拋 `AmountParseError`，不再截斷 |
| P2 | `narratives.py:90` `bool("false")` 誤判 | 已解決 | `narratives.py:65-66` `_parse_bool()`，`narratives.py:116` 使用 |
| P2 | `generators/appeal.py:495-497` p3/p4/p5 恆為 None | 未確認 | 行號已位移，未重讀 |
| P2 | `generators/appeal.py:285-287` `_split_reason` 純字元硬切 | 未確認 | 行號已位移，未重讀；若仍存在，會在正式申復文字中間斷句，**屬使用者可見、送審內容品質問題** |
| P2 | `pipeline.py:161-163` 未傳 `claimed_points` 時草稿恆帶硬檢查錯誤 | 部分解決 | `pipeline.py:235` 已透傳 `claimed_points`；預設值行為未確認（`pipeline.py:176` 文件仍註明「個別覆寫需求由呼叫端自行處理」） |
| P2 | `comparator/judger.py:33` `_JSON_OBJECT_RE` 貪婪匹配 | **未解決** | `comparator/judger.py:44` 仍為 `re.compile(r"\{.*\}", re.S)`，`judger.py:57` 使用；多段 JSON 或 LLM 回覆含額外大括號時會誤解析 |
| P2 | 隱私：病歷號進證據文本 | **未解決** | `comparator/evidence.py:82-83` `【案件】病歷號 {case.record_no}` 進入 LLM prompt（本機 LLM，符合 D2，但仍屬 PHI 進入 prompt）；檔名規則見 `evidence_vault.py` 未確認 |
| P2 | 隱私：`DeductionRecord.raw` 含未遮罩出生日期 | **未解決** | `parsers/models.py:65` 與 `parsers/models.py:95` `raw` 保留全部欄位（設計上 D-02 不丟棄）；序列化路徑（API 回應、日誌）未審查 |
| P2 | `submission_xml.py` 本地 XML 展開內部實體 | 已解決 | `parsers/submission_xml.py:27-28` 匯入 `defusedxml`，`:273` `DefusedET.fromstring(text, forbid_dtd=True)`，`:276` 捕捉 `DefusedXmlException` |
| P2 | `server.py:28` 無 `app.secret_key` | **未解決**（低優先） | `grep secret_key` 全 `src/` 與 `server.py` 無命中；若系統不使用 Flask session 則無實際影響 |
| P2 | 回應無 CSP／`X-Content-Type-Options` | 已解決 | `api/security.py:136` 起之 `after_request` 設定 CSP（文件 `progress.md:259` 宣稱同區塊亦含 nosniff、no-referrer、X-Frame-Options） |
| P2 | Google Fonts 外鏈無 SRI | 已解決（外鏈已移除） | 見 P1-5 |

#### C. deepflash4improve.md 第八節（PaddleOCR 評估與整合）

- 整合已實作：`src/elc_audit_engine/ingest/table_ocr.py` 存在；`pyproject.toml:24-29` 以 `[project.optional-dependencies] ocr` 釘選 `paddlepaddle==3.2.2`、`paddleocr==3.7`、`paddlex[ocr]>=3.7,<3.8`。狀態：已解決。
- ClinFusion 評估為「不採用」結論，屬決策紀錄，無待辦。

#### D. progress.md 的待辦與未完成項目

| 項目（progress.md 行） | 狀態 | 證據 |
|---|---|---|
| 雲端病歷 Provider 接 doctor-toolbox（`progress.md:69`） | **未解決**（外部依賴，Phase 10 blocked） | `record_aggregator/providers.py` 有 `RecordProvider` ABC 與 `LocalFileProvider`（`:152` 起）；`grep doctor.toolbox\|CloudRecordProvider` 於 `src/` 無命中 |
| Flask API 化（`progress.md:70-78`） | 已解決 | `server.py:24-26` 工廠；路由見 `api/routes/*.py` |
| 申復上傳格式／Package Builder（`progress.md:79-82`） | 已解決（序列化部分） | `generators/appeal_xml.py` 存在；`packagers/nhi_case_packager.py` 存在；PDF/DICOM 序列化文件明列不在範圍 |
| Local Gateway 七元件（`progress.md:83-84`） | **未解決，且未開工** | `grep -i heartbeat\|AES\|DLL\|ctypes` 於 `src/` 僅 `bridge_queue.py` 命中（佇列文件用語），無 Heartbeat／Job Downloader／AES 快取／NHI Adapter／Retry Manager／Status Reporter／DLL wrapper 實作 |
| 抽樣清單官方欄位契約（`progress.md:121`） | **未解決** | `ingest/sampling.py` 為自訂 8 欄契約，文件明示待官方樣本對照 |
| 紙本掃描 OCR 品質驗證（`progress.md:121`） | **未解決** | 文件列為待補樣本；無樣本可驗證 |
| 核減代碼表完整來源（`progress.md:123`） | **未解決** | 文件仍寫「完整代碼表待取得實體檔或 VPN HELP」 |
| 申復明細檔 reader 細節（分隔符、編碼、表頭）（`progress.md:124`） | 已解決（文件宣稱） | `README.md:231` 宣稱「編碼／分隔符／表頭自動偵測」；`api/routes/appeal.py` 匯入路徑未逐行覆核 |
| `.embed_cache/` 重用（`progress.md:122`） | 未確認 | `.gitignore:5` 僅忽略規則，無重用程式碼的證據 |
| Phase 10 VPN／實機串接（`.planning/ROADMAP.md:60,79`） | **未解決，阻塞中** | 外部依賴：doctor-toolbox 權限、NHI_EIIAPI.DLL（Windows＋VPN＋SAM）、Local Gateway |

#### E. .planning/ 的 phase 與狀態

| 項目 | 狀態 | 證據 |
|---|---|---|
| Phase 11.1 gap 1：`RecordProvider` 未接入 Flask API（`.planning/STATE.md:95`） | 已解決 | `api/records.py`、`api/routes/sampling.py`、`api/routes/appeal.py` 均引用 `record_aggregator`（`grep` 命中） |
| Phase 11.1 gap 2：`deduct_amount`／`order_seq` 金額欄斷鏈（`.planning/STATE.md:95`） | 已解決 | `api/cases.py:85-88` 透傳 `order_seq`、`deduct_amount`；`generators/appeal_print/case_to_submission.py:102-107` 映射至 `seq`、`points` |
| Phase 9.1 W1：`imported→appealed` 非法轉換（`.planning/STATE.md:94`） | 已解決，但與文件語意衝突（見 Q2） | `case_store/states.py:48-51` 把 `imported→appealed` 列為**合法**邊（D-01 設計決定） |
| Phase 9.1 W4：`/api/appeal/generate` 回應契約與 `render_appeal_json` 不一致 | 未確認 | 未比對回應 schema |
| Phase 21 三個 plan（`.planning/ROADMAP.md:40-43`，宣稱 0/3） | 文件落後，部分已實作 | `packagers/nhi_case_packager.py`、`bridge_queue.py`、`api/routes/bridge.py`（docstring 標示 Phase 21-03）已存在；見 Q3 |

### Inferences

- 文件中多數「已修」的聲明都有對應程式證據，但文件本身的行號與結構已大幅過時；若要以 `deepflash4improve.md` 作為追蹤表，需先把 §7 的 `server.py:行號` 全部改為新位置。
- 目前最接近「可立即修」且風險明確的是：`config/llama_config.json` 絕對路徑、`judger.py:44` 正則、`parsers/models.py` 的 raw 序列化路徑、`_split_reason`（需重讀確認）。
- Local Gateway 與 DLL 是外部依賴門控，不應列為「程式待修」，而應列為「等待條件」。

### Gaps

- 未執行 pytest，無法確認文件宣稱的測試基線（`374 passed`、`458 passed` 等）是否仍成立。
- `appeal.py`、`soap.py`、`narratives.py` 的 LLM 呼叫層、`evidence_vault.py` 寫入路徑等，行號已位移，本次未逐行重讀，標為「未確認」。
- `electronic 電子抽審.md` 為法規背景，未逐段比對；未發現其中有明確的待辦標記。

---

## 關鍵問題二：文件之間是否有矛盾？

### Takeaway

有至少 8 處文件彼此矛盾或與程式碼矛盾。最需要處理的是「認證政策」（README 與 progress.md 說選填、程式碼已部分強制）、「W1 狀態轉換」（STATE.md 視為 bug，程式碼註解視為設計）、以及「Phase 21 狀態」（ROADMAP 宣稱未開始，程式碼已有實作）。

### Cited Findings

1. **P0-3 是否完成**：`deepflash4improve.md:197-199` 寫「P0-3 使用者決定暫緩」，但 `progress.md:165` 寫「`.gitignore` 補 `data/output/*`」，程式碼 `.gitignore:29-31` 確實已加。結論：`data/output/*` 部分已完成，但 llama 絕對路徑仍在版控中，文件兩邊都沒有反映。
2. **P1-4 狀態**：`deepflash4improve.md:104-110` 對照表標「已修」，但 `deepflash4improve.md:235-238` 追溯修正段說明曾長期誤植「未處理」。文件自己已承認此矛盾（`deepflash4improve.md:235-238`），屬歷史追溯，目前一致。
3. **P2-9 狀態**：`deepflash4improve.md:112`（§7.1）標「❌ 未修」，但 `rule_repository/loaders/dates.py:49-80` 已修。文件過時。
4. **認證政策**：`progress.md:75-76` 寫「2026-08-07 業務端點認證改為選填」；`api/security.py:30-33` 寫「2026-09 部分強制」，`security.py:34-46` 將 `sampling.import_sampling_cases`、`appeal.generate_appeal_draft` 等列為豁免，而 `sampling.get_sampling_cases`、`appeal.get_appeal_cases`、`sampling.batch_audit` 等不在清單中，即必填。`progress.md` 未同步。
5. **README 與程式碼認證表不一致**：`README.md:516` `/api/monthly/batch/<id>/clear` 標「選填」，`README.md:518` `/api/sampling/batch-audit` 標「選填」，`README.md:520` `/api/appeal/sample-from-stage2` 標「選填」，`README.md:522` `/api/appeal/cases/clear` 標「選填」；但以上四端點均不在 `security.py:34-46` 豁免清單，程式碼為**必填**。需決定哪邊才是政策；若為程式碼，文件要改；若為文件，程式要改。
6. **W1 語意**：`.planning/STATE.md:94` 把 `imported→appealed` 列為「非法轉換」需清理，但 `case_store/states.py:48-51` 註解明寫為 D-01 設計決定，屬合法邊。兩者不能同時成立。
7. **Phase 21 狀態**：`.planning/ROADMAP.md:40` 宣稱 `[ ] Phase 21（0/3 plans）`，但 `packagers/nhi_case_packager.py`、`bridge_queue.py`、`api/routes/bridge.py` 已存在且 `bridge.py` docstring 標示 Phase 21-03 內容。
8. **STATE.md 內部矛盾**：frontmatter 寫 `current_phase: 20`、`status: Ready to Execute Phase 20`、`stopped_at: Phase 20 Plans Created (2026-11-02)`，但 `ROADMAP.md:33-39` 標示 Phase 19、20 已完成（2026-11-02）；同一檔案 `STATE.md:81-84` 又寫「Milestone v1.1 complete / Awaiting next milestone」，`STATE.md:117-121` 寫「Phase: Not started (defining requirements)」。
9. **`.planning/HANDOFF.json` 是否存在**：`progress.md:162` 寫「移除 `.planning/HANDOFF.json`」，但磁碟上仍有 `.planning/HANDOFF.json`（已被 `.gitignore:41` 忽略，不入版控），與文件不符。
10. **測試基線數字**：`deepflash4improve.md:226` 寫 `277 passed`；`deepflash4improve.md:290` 寫 `374 passed / 2 skipped`；`progress.md:114` 寫 `458 passed / 2 skipped（2026-08-11）`；`STATE.md:36` 寫 `363 passed`。依時序皆可能為真，但無法在不跑測試時驗證，且 `progress.md:114` 的基線與 `.planning/STATE.md` 的數字之間缺少對照表。
11. **`SUMMARY.md` 性質**：`SUMMARY.md` 全文為「Phase 13-02：ODT Filling & PDF Rendering Engine」的執行摘要，不是專案摘要，但檔名易被誤認為專案總覽。
12. **`reasonix.toml`（權限設定，非文件）**：`reasonix.toml:2` 的 `allow` 清單含 `git push origin main`、`rm -rf data/uploads`、`kill_shell`、以及 `git commit` 與 `python server.py` 等具有副作用的指令。此檔屬工具權限設定，不是專案文件；若此檔被其他工具解讀為自動允許清單，會形成「未經確認即推送、刪除資料」的風險。**建議由使用者審視此清單**，本研究未修改該檔。

### Inferences

- 多數矛盾源自「修完之後未回填追蹤文件」（deepflash §7.5/7.6 已自我承認此模式），屬流程問題，不是單一錯誤。
- 認證政策的矛盾風險較高：HIS 端若依 README 選填而不帶 key，對必填端點會得到 401；反之，若依程式碼必填而文件寫選填，同樣會破壞整合。

### Gaps

- 無法確認 `progress.md` 第 175 行以後的 2026-08-11 之後變更是否已反映於 `.planning/`，因為本次只讀到 `progress.md:175`。

---

## 關鍵問題三：文件是否落後於程式碼？

### Takeaway

是。文件落後的面向包括：`deepflash4improve.md` §7 的 `server.py` 行號與描述（`server.py` 已變為工廠）、`progress.md:75-76` 的認證政策、`.planning/ROADMAP.md` Phase 21 狀態、`.planning/STATE.md` 的 current position、`README.md` 認證表與實際豁免清單不符。另外，`README.md` 的程式行為描述大致與程式一致（如三種非結論狀態、`run_presubmission_check` 唯讀），沒有發現描述已刪除功能的情況。

### Cited Findings

- `deepflash4improve.md:118-121` 描述 `server.py:74-104` 硬編碼 if/else 與 `server.py:199-201` 的 `0.0.0.0`／`debug=True`；現行 `server.py:24-42` 已是 42 行工廠（`server.py:29-42` 有安全預設）。文件描述的是已消失的程式。
- `README.md:14` 與 `AGENTs.md:15` 指向 `run_presubmission_check`，`pipeline.py` 存在該函式（`pipeline.py:~160-240` 區段）— 與程式一致。
- `README.md:312-337` 管線指令（`build_sqlite`、`build_docx_trees`、`build_chroma_index`、`mapping.build_mapping`）對應 `rule_repository/scripts/*.py` 與 `mapping/build_mapping.py`，路徑存在。`README.md` 無 `ruff` 或 CI 描述，與程式碼一致（亦即兩者皆無）。
- `AGENTs.md:86` 測試指令 `ELC_ALLOW_NO_AUTH_FOR_TESTS=1 uv run pytest -q tests doc/tests` 中的 `doc/tests` 路徑：專案根目錄之 `doc/` 目錄存在（`ls` 顯示），但本次未確認其內容是否含測試。
- `AGENTs.md:47-49` 宣稱 `AuditFieldError` 會在禁止欄位時拋出，`audit_log.py:44` 與 `:83-87` 存在對應實作，一致。
- `AGENTs.md:57-63` 的 blueprint 清單（`monthly`、`sampling`、`appeal`、`attachments`、`print`、`security`）與 `api/routes/` 檔案（`monthly.py`、`sampling.py`、`appeal.py`、`attachments.py`、`printing.py`、`bridge.py`、`his_integration.py`、`misc.py`、`rules.py`、`vault.py`）大致一致，但 `AGENTs.md` 未提及 `bridge`、`his_integration`、`rules`、`vault` 四個 blueprint；屬文件未更新。
- `AGENTs.md:52` 宣稱「`GET /api/sampling/cases`、`GET /api/appeal/cases`…mandate X-API-Key」，與 `api/security.py` 豁免清單一致。
- `README.md:114` 認證表之「否（選填）」列與 `security.py:34-46` 一致；但 `README.md:516/518/520/522` 與程式不一致（見 Q2-5）。
- `progress.md:164` 宣稱 GET 案例端點「已加 `demo: true` 標記」，`api/demo_data.py:1,9,24` 確實有 `"demo": True`，一致。

### Inferences

- `AGENTs.md` 作為給 LLM agent 的指令，其 blueprint 清單不完整，可能導致 agent 忽略 `bridge` 與 `his_integration` 的安全邊界。
- `deepflash4improve.md` 作為 agent 的讀取來源，行號過時會導致 agent 修錯位置。建議在檔頭加註「行號已於重構後失效，以函式名為準」。

### Gaps

- `README.md` 約 557 行，本次僅以關鍵字與路由表掃描，未逐段覆核所有功能描述（例如 monthly 批次報告、Evidence Vault 流程）。
- 未驗證 `doc/` 目錄下的測試檔是否存在。

---

## 關鍵問題四：哪些未解決項目最值得優先修？

### Takeaway

依「對送審內容正確性與 PHI 外洩風險」排序，建議順序為：(1) 認證政策統一（影響 HIS 整合與 PHI 端點保護）；(2) `config/llama_config.json` 絕對路徑與公開化前的 PHI 清查；(3) `judger.py` JSON 解析正則（影響判定結果正確性）；(4) `DeductionRecord.raw` 序列化路徑審查（PHI）；(5) 申復文字 `_split_reason` 硬切（若仍存在，會直接影響送審文字）；(6) 文件同步（deepflash 行號、STATE、ROADMAP Phase 21、progress 認證政策）。

### Cited Findings（依優先序）

1. **認證政策統一**：程式碼 `api/security.py:34-46` 與 README 認證表不一致，四個端點（`/api/sampling/batch-audit`、`/api/appeal/sample-from-stage2`、`/api/appeal/cases/clear`、`/api/monthly/batch/<id>/clear`）程式為必填、文件為選填。影響：HIS 依文件整合會得到 401；反之若放寬，會讓清除類操作無認證。
2. **llama 絕對路徑與 git 追蹤**：`config/llama_config.json:3`，`git ls-files config` 確認已追蹤。公開化前需移除並清查歷史（`deepflash4improve.md:129-130`）。屬小修但有外洩面。
3. **judger JSON 解析**：`comparator/judger.py:44` `\{.*\}` 貪婪匹配，`judger.py:57` 使用。影響判定結果正確性（會誤把多段 JSON 或含大括號的推理文字解析為判定）。修法小（改為非貪婪或改用 `json.JSONDecoder.raw_decode`）。
4. **DeductionRecord.raw 未遮罩出生日期**：`parsers/models.py:65,95`。需審查所有會序列化 `raw` 的路徑（API 回應、日誌、審計）。
5. **申復文字 `_split_reason` 硬切**：`generators/appeal.py` 行號已位移，需重讀確認；若仍是字元位置硬切，會在正式申復文字中間斷句，屬直接送審內容品質問題，價值高但需先確認。
6. **`evidence_vault.py` 寫入路徑**：`evidence_vault.py:192` 使用 `os.path.basename(target)`，需確認 `target` 是否來自可控輸入且經 `safe_filename`。若未經校驗，屬 P1-3 的殘留。
7. **`static/index.html:1622-1624` innerHTML**：改為 `textContent`，成本低。
8. **ruff／CI 未設定**：`pyproject.toml` 無 ruff 設定，屬 `deepflash4improve.md:62` 列為待辦的 P1-6 殘留，成本低、價值中。
9. **文件同步**：`deepflash4improve.md` §7 行號、`progress.md:75-76` 認證政策、`.planning/STATE.md` current position、`.planning/ROADMAP.md:40` Phase 21、`AGENTs.md` blueprint 清單缺 bridge／his_integration／rules／vault、`SUMMARY.md` 命名誤導。成本低、避免 agent 誤判。
10. **reasonix.toml 權限清單**：建議使用者審視 `git push origin main`、`rm -rf data/uploads` 等是否確實應自動允許。

### Inferences

- 高價值的三項（認證、judger 正則、PHI 序列化）都是小改動、可各自獨立測試，適合先做。
- Local Gateway 七元件與 NHI_EIIAPI.DLL 屬大型工作且受外部依賴阻塞（`.planning/ROADMAP.md:60`），不應列入近期待修清單，應列為「等待條件」。
- `_score_candidate` 與 `build_mapping` 複雜度屬建置期問題，不影響送審結果，優先度低。

### Gaps

- 第 5、6 項需先重讀 `generators/appeal.py` 與 `evidence_vault.py`，本次未完成。
- 未執行測試，無法確認修改的回歸影響面。
- 認證政策的「正確答案」需要使用者裁示（程式或文件哪邊為準），本研究無法自行判定。

---

## 未來工作（文件有寫、程式尚未開始）

| 項目 | 文件來源 | 程式現況 |
|---|---|---|
| Local Gateway 七元件（Heartbeat／Job Downloader／AES 快取／NHI Adapter／Retry Manager／Status Reporter／NHI_EIIAPI.DLL wrapper） | `progress.md:83-84`、`deepflash4improve.md:177`、`.planning/ROADMAP.md:79` | 未開工。僅有 `api/routes/bridge.py` 與 `bridge_queue.py` 之佇列 API（Phase 21-03 方向） |
| 雲端病歷 Provider（doctor-toolbox） | `progress.md:69`、`.planning/ROADMAP.md:79` | 未實作，僅有 `LocalFileProvider` |
| VPN／SAM／Reader 與健保署 IDC 串接 | `deepflash4improve.md:178` | 行政／硬體前置，無程式碼 |
| PDF／DICOM 封包序列化 | `progress.md:82`、`.planning/ROADMAP.md:104-106`（列為範圍外） | 未確認。`packagers/nhi_case_packager.py` 含 DICOM 字樣（`grep` 命中），範圍未確認 |
| 核減代碼表完整來源 | `progress.md:123` | 未取得實體檔 |
| 抽樣清單官方欄位契約對照 | `progress.md:121` | 未取得官方樣本 |
| ruff 靜態檢查門檻 | `deepflash4improve.md:62` | 未設定 |
| 審計日誌與認證分離後之回歸測試 | `deepflash4improve.md:293-297` | 文件宣稱已由 `tests/test_auth.py` 覆蓋，未驗證 |

---

## 附註

- 本研究為唯讀盤點，未修改任何原始碼、設定或文件。
- 本研究中所有「已解決」結論皆以文件宣稱或 grep 命中為依據，未執行測試，屬靜態證據。
- 本研究未讀取 `.env`，未輸出任何金鑰或機敏值。
