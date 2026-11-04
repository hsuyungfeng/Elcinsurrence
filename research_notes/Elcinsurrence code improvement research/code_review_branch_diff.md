# 程式碼審查：feat/phase-17-evidence-vault 相對於 main

- 審查範圍：`git diff main...HEAD`（78 個檔案，+9037 / -114）
- 審查 HEAD：`6ea9be627ecace63c7cefecb301b14429f7518ed`
- 連結基底：`https://github.com/hsuyungfeng/Elcinsurrence/blob/6ea9be627ecace63c7cefecb301b14429f7518ed/`
- 適用規則：`AGENTs.md`（§2 Hard Invariants 與 §3 架構）。`.claude/` 內無 CLAUDE.md；使用者全域 CLAUDE.md 無與本 diff 相關之程式規則。
- 語法檢查：本次 diff 內 46 個 Python 檔案皆可通過 `ast.parse`；新增模組之 `from ... import` 目標皆已確認存在（如 `record_aggregator/` 為套件目錄，可正常匯入）。

## 結論

共 5 項經驗證的發現（高 2、中 2、低 1）。未發現會導致 import／語法失敗的問題。

---

## 發現 1：高 — 批次閉環 UI 在 LLM 判定失敗時仍將案件標為 `reviewed`

- 位置：
  - `static/index.html:1638-1647`（前端把 HTTP 200 一律視為 `c.state = 'reviewed'`）
  - `src/elc_audit_engine/sampling_closed_loop.py:73-88`（`judgment_level` 為 None 時回傳 `待判定`）
  - `src/elc_audit_engine/api/routes/sampling.py:232-250`（單案閉環端點對待判定仍回 200）
- 說明：`run_closed_loop` 在 LLM 判定服務異常時，`support_level` 為 None，`resolve_support_state` 回傳 `待判定`，端點仍回 HTTP 200。前端只以 `res.ok` 判斷成功，並直接設定 `c.state = 'reviewed'`。
- 失敗情境：LLM 逾時 → 閉環回傳 `support_state: 待判定` → 前端左側狀態徽章顯示「已審查」。違反 AGENTs.md §2.2 的規則：「If an LLM call fails, the case state transitions to `failed`, NEVER to `reviewed`.」同一檔案中的單案 `audit_sampling_case`（`sampling.py:560-565`）有處理此情況，批次閉環路徑卻沒有。
- 連結：
  - https://github.com/hsuyungfeng/Elcinsurrence/blob/6ea9be627ecace63c7cefecb301b14429f7518ed/static/index.html#L1638-L1647
  - https://github.com/hsuyungfeng/Elcinsurrence/blob/6ea9be627ecace63c7cefecb301b14429f7518ed/src/elc_audit_engine/sampling_closed_loop.py#L73-L88

---

## 發現 2：高 — 批次健保抽審 XML 的件數欄位（t9／t17／t37）寫死為 1

- 位置：`src/elc_audit_engine/generators/sampling_xml.py:136-146`
- 說明：`_outpatient_document` 在批次導出時，`<t9>`、`<t17>`、`<t37>` 固定輸出 `1`，與實際 `<ddata>` 數量無關。`電子抽審.md:989-993` 將這三個欄位定義為「申請件數」，範例值為 633；`tests/fixtures/submission_sample.xml` 中同三欄為 4。
- 失敗情境：`build_batch_sampling_xml` 收到 N ≥ 2 個案件時，檔案內含 N 個 `<ddata>`，但件數欄位宣告為 1，申報內容與件數不一致，健保端可能退件或誤計。單案導出（`build_sampling_xml`）經過同一函式，但單案時 1 是正確的，故問題只在批次路徑出現，且對任何 N ≥ 2 都會發生。
- 連結：https://github.com/hsuyungfeng/Elcinsurrence/blob/6ea9be627ecace63c7cefecb301b14429f7518ed/src/elc_audit_engine/generators/sampling_xml.py#L136-L146

---

## 發現 3：中 — 以範本 SOAP 判定時，仍可能產生「✅ 充分」的狀態

- 位置：
  - `src/elc_audit_engine/sampling_closed_loop.py:86-88`（只有 `records_degraded` 會把「充分」降為「薄弱」）
  - `src/elc_audit_engine/sampling_closed_loop.py:225-235`（SOAP 缺漏時改用 `soap_templates` 範本，並餵入比對器）
  - `src/elc_audit_engine/api/routes/sampling.py:534`（`audit_sampling_case` 同樣以 `resolve_soap_text` 帶入範本）
  - `src/elc_audit_engine/monthly_pregen.py:99-103`（LLM 生成的範本以 `llm_validated` 寫入快取）
- 說明：`fallback_soap` 會把範本當成「本案 SOAP」送進 `run_presubmission_check`。`build_review` 只依 `records_degraded` 降級，`soap_source` 為 `template_*` 時只附加警示文字，狀態仍可能是「充分」。AGENTs.md §2.1 規定：「Citations must match exact substrings of the patient SOAP record」，範本文字並非病患病歷。
- 失敗情境：某案件沒有 SOAP，但存在同醫令的通用範本；病歷來源可取得半年病史（`records_degraded=False`）；比對器依範本文字判定為「充分」→ 狀態顯示 ✅ 充分，醫師只看到一行警示文字。
- 附註：範本內容由 `comparator/soap_advice.py:101-103` 的既有提示詞產生，該提示詞要求模型「GENERATE A REALISTIC ... TEMPLATE」並寫出「exact ICD-10 diagnostic codes」（此段在 main 即已存在，屬既有問題；本分支新增的是把這些生成內容持久化並用於判定的路徑）。
- 連結：
  - https://github.com/hsuyungfeng/Elcinsurrence/blob/6ea9be627ecace63c7cefecb301b14429f7518ed/src/elc_audit_engine/sampling_closed_loop.py#L86-L88
  - https://github.com/hsuyungfeng/Elcinsurrence/blob/6ea9be627ecace63c7cefecb301b14429f7518ed/src/elc_audit_engine/sampling_closed_loop.py#L225-L235

---

## 發現 4：中 — 「查無規則」被併入「待判定」，違反 AGENTs.md 的三種狀態區分

- 位置：`src/elc_audit_engine/sampling_closed_loop.py:163-165` 與 `174-176`（`build_review`）
- 說明：`level = judgment_level if rule_found else None`，接著 `resolve_support_state(None)` 回傳 `待判定`。因此醫令無規則時，寫入 `payload["review"]["support_state"]` 的值為 `待判定`，而非獨立的「查無規則」狀態。
- 規則依據：AGENTs.md §2.2 明定三種狀態不可混用：`待判定 (support_level is None and undetermined is True)` 與 `查無規則 (support_level is None and rule_found is False)`。`SUPPORT_STATES` 亦未包含「查無規則」。
- 失敗情境：醫令代碼不在規則庫 → 批次閉環結果以 ⏳ 待判定計數（`by_state`），與系統故障的待判定混在一起，醫師無法區分「規則缺漏」與「服務異常」。（註：`audit_sampling_case` 回應中的 `undetermined` 欄位能正確區分，但持久化的 `support_state` 與批次統計未區分。）
- 連結：https://github.com/hsuyungfeng/Elcinsurrence/blob/6ea9be627ecace63c7cefecb301b14429f7518ed/src/elc_audit_engine/sampling_closed_loop.py#L163-L176

---

## 發現 5：中 — 統一審查報告的 `onclick` 屬性可因單引號跳脫而注入 JavaScript

- 位置：`src/elc_audit_engine/unified_review_report.py:682-685`
- 說明：`c_diag = escape(view.primary_diagnosis or "")` 與 `c_order` 使用 HTML 跳脫後，直接放入以單引號包住的 JavaScript 字串：`onclick="openSoapModal('{c_order}', '{c_diag}', '{c_id}')"`。HTML 跳脫會把 `'` 轉成 `&#x27;`，瀏覽器解析屬性值時會還原成 `'`，因此 JavaScript 字串可被跳出。`primary_diagnosis` 來自匯入檔案（`unified_review_report.py:352`），未經格式驗證。
- 失敗情境：匯入的 CSV／TOTFA 中某案件的主診斷為 `x');alert(document.cookie);('`，產出的報告頁面在醫師點擊「範例病歷彈窗」時執行該腳本。`security.py:55-56` 的 CSP 允許 `'unsafe-inline'` 的 script，因此不會被阻擋。此問題需要惡意或損毀的匯入資料，故定為中。
- 建議方向（僅供參考，未實作）：改用 `data-*` 屬性加上事件委派，或以 `json.dumps` 產生 JavaScript 字串常值。
- 連結：https://github.com/hsuyungfeng/Elcinsurrence/blob/6ea9be627ecace63c7cefecb301b14429f7518ed/src/elc_audit_engine/unified_review_report.py#L682-L685

---

## 發現 6：低 — ZIP 解壓總量上限只檢查宣告大小，未檢查實際寫入位元組

- 位置：`src/elc_audit_engine/evidence_vault.py:223-225`（`declared_total` 以 `m.file_size` 加總）與 `233-234`（每個成員只以 `MAX_MEMBER_BYTES` 限制單檔）
- 說明：`MAX_ZIP_TOTAL_BYTES` 僅與 ZIP 標頭宣告的大小比較，宣告值可被竄改。實際解壓寫入時沒有累計位元組上限，因此 `MAX_ZIP_MEMBERS`（500）× `MAX_MEMBER_BYTES`（50 MB）＝ 約 25 GB 的寫入空間仍可能發生，遠超設計意圖的 200 MB。
- 失敗情境：已通過認證的呼叫端上傳一個壓縮比極高的 ZIP，成員宣告大小很小但實際解壓內容很大，造成磁碟耗盡。需要 API Key，故定為低。
- 連結：https://github.com/hsuyungfeng/Elcinsurrence/blob/6ea9be627ecace63c7cefecb301b14429f7518ed/src/elc_audit_engine/evidence_vault.py#L221-L234

---

## 未列入（已查證但不符合本次篩選條件）

- 既有問題（main 即存在，非本分支引入）：`api/routes/appeal.py:175` 使用未定義的 `order_name`（`NameError`），被同一函式的 `except Exception` 吞掉，導致 `generate_appeal_draft` 的 LLM 建議永遠為 None。`appeal.py:153` 在 main 的同位置即已存在相同程式碼。
- 已排除：`static/index.html:1625-1627` 以 innerHTML 寫入 `<code>${caseId}</code>`，但 case_id 為內容雜湊（`SAMP-…` 十六進位），無法由使用者控制，不可利用。
- 已排除：`api/routes/appeal.py` 與 `appeal_linkage.py` 中 `case_seq` 缺漏時預設為 `"1"`、`deduct_amount` 預設為 100。這些是作者刻意加入（commit `40b886e`），且只在輸入缺欄位時才會發生，不屬於「對任何輸入都錯」的問題。
- 已排除：`generators/appeal_xml.py` 的 `is_appealing` 預設為 True。`claimed_points` 缺漏時仍會以 422 拒絕，未造成錯誤輸出。

## 審查方法說明

- 以 `rtk proxy git diff` 取得完整 diff（一般 `git diff` 會被輸出過濾器截斷）。
- 所有發現皆回到工作目錄原始碼確認行號與呼叫路徑；發現 1、3、4 另核對前端程式碼與 AGENTs.md 原文。
- 未執行測試套件或 linter（依指示）。
- 未對 GitHub 發布任何內容。
