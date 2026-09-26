---
phase: whole-codebase-A-api-store-generators
reviewed: 2026-09-26T08:47:58Z
depth: deep
files_reviewed: 33
files_reviewed_list:
  - server.py
  - src/elc_audit_engine/auth.py
  - src/elc_audit_engine/audit_log.py
  - src/elc_audit_engine/attachment_store.py
  - src/elc_audit_engine/safe_paths.py
  - src/elc_audit_engine/prompt_safety.py
  - src/elc_audit_engine/pipeline.py
  - src/elc_audit_engine/case_store/db.py
  - src/elc_audit_engine/case_store/states.py
  - src/elc_audit_engine/case_store/store.py
  - src/elc_audit_engine/generators/appeal.py
  - src/elc_audit_engine/generators/appeal_xml.py
  - src/elc_audit_engine/generators/reinforcement_report.py
  - src/elc_audit_engine/generators/tracking.py
  - src/elc_audit_engine/generators/appeal_print/__init__.py
  - src/elc_audit_engine/generators/appeal_print/case_to_submission.py
  - src/elc_audit_engine/generators/appeal_print/field_mapping.py
  - src/elc_audit_engine/generators/appeal_print/odt_fill.py
  - src/elc_audit_engine/generators/appeal_print/template.py
  - src/elc_audit_engine/generators/deduction_print/__init__.py
  - src/elc_audit_engine/generators/deduction_print/field_mapping.py
  - src/elc_audit_engine/generators/deduction_print/odt_fill.py
  - src/elc_audit_engine/generators/deduction_print/template.py
  - src/elc_audit_engine/generators/evidence_packet/__init__.py
  - src/elc_audit_engine/generators/evidence_packet/builder.py
  - src/elc_audit_engine/generators/evidence_packet/image_processor.py
  - src/elc_audit_engine/generators/evidence_packet/pdf_exporter.py
  - scripts/build_appeal_print.py
  - scripts/build_appeal_xml.py
  - scripts/build_deduction_print.py
  - scripts/build_evidence_packet.py
  - scripts/replay_gold_standard.py
  - .gitignore
findings:
  critical: 11
  warning: 14
  info: 7
  total: 32
status: issues_found
---

# 全碼庫審查報告 A：API／CaseStore／產生器

**審查時間：** 2026-09-26T08:47:58Z
**深度：** deep（含跨模組呼叫鏈追蹤：server → case_store / attachment_store → generators → soffice）
**審查檔案數：** 33
**狀態：** issues_found

> 註：本機 `.venv` 為空（未安裝相依套件），故未能實際執行；以下結論均由逐行讀碼與呼叫鏈追蹤得出，每項皆附行號。

## 摘要

整體程式碼的「防禦性註解」寫得相當完整（safe_filename 校驗後拒絕、審計日誌禁止 PHI、ET 文字節點防 XML 注入等），但**註解所宣稱的保證和實際接線之間有多處斷裂**。最嚴重的問題集中在四個面向：

1. **認證形同虛設**：所有業務端點（包含 DELETE 與回傳 PHI 的 GET）都列在 `_AUTH_EXEMPT_ENDPOINTS`，因此 fail-fast 的 API key 機制實際上不保護任何病歷資料；檔案啟動區塊的註解卻寫成「一律需帶 X-API-Key」。
2. **識別碼碰撞（case_id／case_seq）**：`SAMP-0001`／`APP-0001` 每次匯入都從 1 重新編號，第二次匯入的案件全部被 CaseStore 以「重複」拒收，但 API 仍回 success。附件以 `case_seq` 為全域唯一鍵，而流水號每個費用年月都會重複（CSV 缺值時更退回 `str(idx)`），會把 A 病患的佐證影像併入 B 病患的佐證包，也會讓 p7 被誤判為 Y。這和 3f7f097 修的是同一類問題，而且範圍更大。
3. **產出物契約不一致**：佐證包拿「匯入 payload」當申復草稿，所以第 4 節永遠是空的，審核軌跡則永遠是 None。核減明細列印讀取的 facility／payload 鍵名全都對不上。兩個列印端點回傳的 `/output/...` URL 沒有對應路由。
4. **狀態機語意**：LLM 判定失敗時，案件仍被推進到 `reviewed`，直接違反專案自訂的 P1-1 原則（「系統故障不可偽裝成業務結論」）。轉換也不是原子操作，且沒有併發保護。

## Critical Issues

### CR-01：業務端點全面免認證，API key 機制實際不保護任何 PHI（含 DELETE、CSRF、DNS rebinding 面）

**檔案：** `server.py:85-97`、`server.py:160-186`、`server.py:1188-1189`
**問題：** `_AUTH_EXEMPT_ENDPOINTS` 納入全部 11 個業務端點（`get_sampling_cases` 回傳患者姓名／SOAP、`delete_appeal_attachment` 可刪除佐證、`import_appeal_cases` 會回傳 OCR 文字預覽 500 字）。結果是：
- 啟動時強制要求 `ELC_API_KEYS`（fail-fast），卻沒有任何端點需要它，只給人「有認證」的錯覺。
- `__main__` 註解（1188-1189）寫「除 / 與 /api/health 外一律需帶 X-API-Key」，與事實相反，會誤導維運人員把服務以 `ELC_SERVER_HOST=0.0.0.0` 對外開放。
- 即使綁在 127.0.0.1：multipart 表單 POST 屬 simple request，任何網頁都能對 `/api/appeal/import`、`/api/appeal/attachments/upload` 發起 CSRF。服務也沒有 Host header 檢查，DNS rebinding 可以讀取 `GET /api/sampling/cases` 的全部 PHI。
**修正：**
```python
# server.py：業務端點移出豁免清單，僅保留真正無 PHI 的端點
_AUTH_EXEMPT_ENDPOINTS = _AUDIT_EXEMPT_ENDPOINTS  # index/health/static
# 若前端頁面需呼叫 API：改由反向代理注入 key，或另設 session/CSRF token；
# 並加 Host 白名單防 DNS rebinding：
_ALLOWED_HOSTS = {h.strip() for h in os.getenv("ELC_ALLOWED_HOSTS", "127.0.0.1:5000,localhost:5000").split(",")}
@app.before_request
def _check_host():
    if request.host not in _ALLOWED_HOSTS:
        return jsonify({"status": "error", "message": "invalid host"}), 400
```
若「HIS 對接免認證」確實是使用者的裁示，至少應以環境旗標（如 `ELC_AUTH_MODE=open`）明示開啟，並在啟動時記錄 WARNING，同時修正 1188 行的錯誤註解。

### CR-02：case_id 每次匯入從 0001 重新編號，第二次匯入的案件被全數靜默拒收

**檔案：** `server.py:379`、`server.py:407`、`server.py:325-347`、`server.py:709-722`、`server.py:967-980`
**問題：** `_to_sampling_case`／`_to_appeal_case` 以 `f"SAMP-{idx:04d}"`／`f"APP-{idx:04d}"` 產生 id，其中 idx 來自 `enumerate(..., start=1)`。第二份 CSV 的 id 與第一份完全相同，`_persist_cases` 會把它們全部歸入 `conflicts`，但回應仍是 `status: success, imported: N`。`GET /api/*/cases` 改讀 CaseStore 後，看到的仍是**舊批次**的患者資料，醫師可能據此對錯誤的病患做預審或申復。啟動時的 `_migrate_legacy_uploads` 也會以同樣方式把最新 JSON 全部略過。
**修正：** 改用全域唯一 id，並讓碰撞在 API 層可見：
```python
batch = datetime.now().strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:6]
"id": f"SAMP-{batch}-{idx:04d}",
...
if conflicts:
    return jsonify({... "status": "partial", "case_store_conflicts": conflicts}), 409
```
更理想的做法是以業務自然鍵（`fee_year_month + case_class + case_seq + order_seq`）組成 id，讓重複匯入同一份核減檔時具冪等性。

### CR-03：附件以 case_seq 為全域唯一鍵，跨病患混入佐證包、誤設 p7=Y（與 3f7f097 同類，範圍更大）

**檔案：** `server.py:408`、`server.py:986-1005`、`server.py:1145-1156`、`src/elc_audit_engine/attachment_store.py:96-108`、`src/elc_audit_engine/generators/appeal.py:357-359`、`src/elc_audit_engine/generators/evidence_packet/__init__.py:68-70`
**問題：**
- 健保流水號（d2）只在單一費用年月、單一案件分類內唯一，跨月份必定重複；`_to_*_case` 在 CSV 缺值時更會退回 `str(idx)`（"1"、"2"…），不同批次必然撞號。
- `ATTACHMENTS_DIR/<case_seq>/` 不分費用年月、案件分類，也不分 sampling／appeal。
- `generate_evidence_packet_print` 以 `case.case_seq` 列出附件，會把另一位病患的影像或 PDF 合併進本案佐證包，屬 PHI 外洩到錯誤文件。
- `build_appeal_draft` 在未帶 `has_attachment` 時以 `record.case_seq` 查附件，別的案件有附件就會讓本案 p7 變成 `Y`。
- 佐證包檔名 `申復佐證包_{case_seq}.pdf` 也會互相覆寫。
**修正：** 附件主鍵改為 CaseStore 的 `case_id`（全域唯一），或至少使用複合鍵：
```python
# attachment_store：目錄 = <ATTACHMENTS_DIR>/<case_id>/ ，上傳端點改收 case_id 並驗證存在
case = _case_store.get(safe_filename(case_id, "case_id"))   # 404 if missing
rec = attachment_store.save_attachment(case_key=case.case_id, ...)
# 佐證包檔名亦改用 case_id
```
`_to_*_case` 不應以 `str(idx)` 捏造流水號，缺值時應保留 None 並拒絕建立附件。

### CR-04：佐證包的核心內容永遠缺失（草稿段空白、審核軌跡恆為 None、病史段誤稱「無就醫紀錄」）

**檔案：** `server.py:1161-1168`、`src/elc_audit_engine/generators/evidence_packet/__init__.py:28-50`、`src/elc_audit_engine/generators/evidence_packet/builder.py:140-159`
**問題：**
- `write_evidence_packet(..., case.payload, ...)` 傳入的是 `_to_appeal_case` 的**匯入 payload**，其中沒有 `sections`／`orders`，所以第 4 節「Appeal Draft」恆為空。`/api/appeal/generate` 產出的草稿也從未寫回 CaseStore。
- `tracking=case.history if hasattr(case, "history") else None`：`CaseRecord` 沒有 `history` 屬性（`history` 是 `CaseStore` 的方法，回傳型別是 `tuple[TransitionRecord]`，不是 builder 預期的 `{"entries": [...]}`），因此恆為 None。
- `timeline=None` 讓第 3 節印出「無就醫紀錄」。這是把「未查詢」寫成「病患沒有就醫紀錄」，違反誠實降級原則。
**修正：**
```python
# /api/appeal/generate 成功後把 draft 落入 CaseStore（新增 update_payload 或 artifacts 表）
_case_store.attach_artifact(case_id, "appeal_draft", payload)
# 佐證包端點：
draft = _case_store.get_artifact(safe_case, "appeal_draft")
if draft is None:
    raise ApiError("本案尚未生成申復草稿，無法產出佐證包", status=409)
tracking = {"entries": [asdict(t) for t in _case_store.history(safe_case)]}
# builder：timeline_data 為 None 時印「病史未查詢（來源未設定）」而非「無就醫紀錄」
```

### CR-05：兩個列印端點回傳的 `pdf_url` 無對應路由，永遠 404

**檔案：** `server.py:1114`、`server.py:1172`
**問題：** 兩端點回傳 `/output/<檔名>.pdf`，但 server 沒有任何 `/output` 路由（`static_folder='static'`）。API 的唯一產出不可取得。
**修正：** 新增受認證保護的下載端點，並驗證檔名：
```python
@app.route('/api/output/<name>', methods=['GET'])
def download_output(name):
    if not re.fullmatch(r"(核減明細|申復佐證包)_[A-Za-z0-9_\-一-鿿]+\.pdf", name):
        raise ApiError("invalid", 404)
    return send_from_directory(settings.OUTPUT_DIR, name, as_attachment=True)
```
（此端點不可加入 `_AUTH_EXEMPT_ENDPOINTS`。）

### CR-06：核減明細列印欄位契約全面錯位，官方表單印出空院所名稱與 0 點總額

**檔案：** `src/elc_audit_engine/generators/deduction_print/field_mapping.py:147-153`、`:163`、`:171`、`:190`；`server.py:1076-1080`
**問題：**
- `facility.get("institution_code")`、`facility.get("facility_name")`：`config/facility.json` 與 `REQUIRED_FACILITY_FIELDS` 的鍵名是 `code`／`name`，所以「醫療院所名稱」恆為空。
- 經 `case_id` 路徑時，records 是 `_to_appeal_case` payload，金額鍵是 `deduct_amount` 而不是 `non_reimbursed_amount`。「不予核銷金額」會空白、總核減點數為 0；`case_class`、`chart_no`、`birth_date` 等鍵也都不存在。
- `r.get("case_class", "") + r.get("case_seq", "")`：鍵存在但值為 None 時會拋 TypeError（client 傳 `null` 即可觸發）。字串直接串接也會讓 "1"+"23" 與 "12"+"3" 被當成同一件。
- `int(r.get("non_reimbursed_amount", 0) or 0)` 遇到非數字字串會拋 ValueError。
**修正：**
```python
"機構代碼": _str_or_empty(facility.get("code") or first.get("institution_code")),
"醫療院所名稱": _str_or_empty(facility.get("name")),
"核減件數": str(len({(r.get("case_class") or "", r.get("case_seq") or "") for r in records if r.get("case_class") or r.get("case_seq")})),
"總核減點數": str(sum(_to_int(r.get("non_reimbursed_amount", r.get("deduct_amount"))) for r in records)),
```
server 端應把 payload 轉成 DeductionRecord 形狀（比照 `case_to_submission.py` 建立標準轉換層），並以 schema 驗證 client 傳入的 `records`（必須是 dict、數值欄位必須是 int）。

### CR-07：`data/attachments/`（PHI 影像／PDF）未列入 .gitignore

**檔案：** `.gitignore`（全檔）；`config/settings.py` 的 `ATTACHMENTS_DIR = data/attachments`
**問題：** `.gitignore` 已排除 `data/uploads/`、`data/output/*`、`data/samples/`、`data/phi/` 等，唯獨漏掉 Phase 12 新增的 `data/attachments/`（含病患 X 光、檢驗報告 PDF 與 `meta.json`）。一次 `git add -A` 就會把 PHI 推入版控，違反 D2／P0-3。
**修正：**
```gitignore
# 佐證附件（PHI 影像/PDF，Phase 12）
data/attachments/
```
並以 `git log --all -- data/attachments` 確認歷史中沒有已提交的內容。

### CR-08：`errorhandler(Exception)` 吞掉 HTTPException，404／405／413／415／400 全部變成 500

**檔案：** `server.py:237-241`（連帶 `server.py:180-182` 的註解）
**問題：** Flask 的通用 `Exception` handler 也會攔截 `werkzeug.exceptions.HTTPException`。後果如下：
- 未知路由（探測流量）一律回 500，且每次都 `logger.exception` 印出堆疊，淹沒日誌。
- `request.json` 在 Content-Type 錯誤（415）或 JSON 語法錯誤（400）時回 500，HIS 端無法區分「自己送錯」和「伺服器故障」，違反 P0-2「故障與業務結論可區分」的原則。
- 180 行的註解「交給 Flask 內建處理」與實際行為不符。
**修正：**
```python
from werkzeug.exceptions import HTTPException

@app.errorhandler(HTTPException)
def _handle_http(exc: HTTPException):
    return jsonify({"status": "error", "message": exc.description}), exc.code

@app.errorhandler(Exception)
def _handle_unexpected(exc):
    if isinstance(exc, HTTPException):
        return _handle_http(exc)
    ...
```

### CR-09：狀態機語意錯誤：LLM 失敗仍推進 `reviewed`；三段轉換非原子；未檢查 kind；草稿驗證失敗仍 `appealed`

**檔案：** `server.py:578-589`、`server.py:881-886`、`src/elc_audit_engine/case_store/states.py:48-51`
**問題：**
- `audit_sampling_case` 在 `oj.support_level is None`（判定服務異常）時，仍執行 parsed→reviewing→reviewed，把系統故障記錄成「已完成預審」，直接違反 P1-1。轉換也發生在 `if not judgments: raise ApiError(...)` **之前**，所以回 400 的請求仍會讓案件變成 reviewed。
- 三次 `transition` 是三個獨立交易，中途任一步失敗就會卡在 parsed 或 reviewing，而且只記 warning、不回報給呼叫端。
- 沒有檢查 `case.kind`：appeal 案件的 case_id 可以被送進 sampling 預審；sampling 案件也可以經 `/api/appeal/generate` 從 reviewed 推進到 appealed。這和 states.py:48-50 註解宣稱的「sampling 不觸發該呼叫」不符，該保證只是呼叫慣例，沒有任何強制。
- `generate_appeal_draft` 在 `draft.validation_errors` 非空（例如申覆卻未填點數、點數超過上界）時，仍把案件推進到 `appealed`。
- 重複預審同一案件時一定會拋 `IllegalTransitionError`（reviewed→parsed 不合法），且被靜默吞掉。
**修正：**
```python
case = _case_store.get(case_id)            # 404 if missing
if case.kind != "sampling":
    raise ApiError("case_id 不是抽樣預審案件", 409)
if oj.support_level is None and oj.rule_found:
    _case_store.transition(case_id, "failed", reason="LLM 判定服務異常", actor=actor)
else:
    _case_store.advance(case_id, ["parsed", "reviewing", "reviewed"], actor=actor)  # 新增：單一交易多步轉換
```
appeal 端點應在 `draft.validation_errors` 為空時才轉入 `appealed`，並把狀態轉換結果放進回應（`state_transition: ok|skipped|failed`）。

### CR-10：附件 `meta.json` 讀-改-寫無鎖、非原子，損毀時直接覆寫成單筆（資料遺失）

**檔案：** `src/elc_audit_engine/attachment_store.py:130-141`、`:171-175`、`:195-217`
**問題：**
- 兩個併發上傳（同一 case_seq）各自讀到舊清單、各自 append 後寫回，後寫的會蓋掉先寫的紀錄。實體檔還在，但 `list_attachments` 看不到，形成孤兒檔（lost update）。
- `open(meta_path, "w")` 不是原子寫入，崩潰時會留下半截 JSON。下次上傳走到 `except Exception: meta_list = []`，會把整份索引覆寫成只剩一筆，所有既有附件從索引中消失。
- `list_attachments` 遇到損毀也回 `[]`，佐證包會在沒有任何警告的情況下缺少附件。
- `AttachmentRecord(**item)` 遇到多餘或缺少的鍵會拋 TypeError（500）。
**修正：** 附件索引改存入 CaseStore 的 SQLite（新增 `attachments` 表，以交易保證一致性）；若要維持 JSON，至少應以 `fcntl.flock` 加鎖、寫入 `meta.json.tmp` 後 `os.replace`，損毀時 fail-fast 拋錯，不可重設成 `[]`。

### CR-11：`build_deduction_print.py --csv` 把檔案內容 bytes 當路徑傳入，功能必定失敗

**檔案：** `scripts/build_deduction_print.py:56-58`
**問題：** `parse_deduction_file(f.read())`：函式簽名是 `parse_deduction_file(path)`，內部會 `open(path, "rb")`。傳入 bytes 時 Python 會把整份 CSV 內容當成檔名，結果一律是 OSError→DeductionFileError，使用者只會看到「解析 CSV 失敗」。`vars(r)` 也會把 `raw` tuple 一起帶進 records。
**修正：**
```python
res = parse_deduction_file(args.csv)
records = [{k: v for k, v in asdict(r).items() if k != "raw"} for r in res.records]
```

## Warnings

### WR-01：`CaseStore.transition`／`create` 存在 TOCTOU 競態

**檔案：** `src/elc_audit_engine/case_store/store.py:218-247`、`:145-176`
**問題：** `transition` 先用另一條連線 `get()` 讀取目前狀態，再在新交易中做 `UPDATE ... WHERE case_id=?`，沒有條件式比對。兩個併發請求可能都以同一個 `from_state` 通過驗證，產生不一致的歷史（例如兩列 imported→appealed）。`create` 的 SELECT 在 Python sqlite3 預設的 deferred 模式下不會開啟寫鎖，併發時 INSERT 會拋 `sqlite3.IntegrityError`（而非 `DuplicateCaseError`），從 `_persist_cases` 穿透造成 500，匯入只完成一半。
**修正：**
```python
cur = conn.execute("UPDATE cases SET state=?, updated_at=?, failure_reason=? WHERE case_id=? AND state=?",
                   (to_state, now, new_failure_reason, case_id, current.state))
if cur.rowcount != 1:
    raise IllegalTransitionError(current.state, to_state, allowed_targets(current.state))  # 或 ConcurrentModificationError
# create：捕捉 sqlite3.IntegrityError → DuplicateCaseError；連線設 isolation_level=None 並 BEGIN IMMEDIATE
```

### WR-02：內部錯誤細節（stderr、路徑、hash）回傳給未認證的呼叫端

**檔案：** `server.py:1111-1112`、`server.py:1169-1170`、`server.py:719`、`server.py:977`、`src/elc_audit_engine/generators/deduction_print/__init__.py:77`、`src/elc_audit_engine/generators/evidence_packet/pdf_exporter.py:260`、`src/elc_audit_engine/generators/deduction_print/template.py:384`
**問題：** `raise ApiError(f"產生 PDF 失敗: {exc}")` 會把 LibreOffice stderr、TemporaryDirectory 路徑、`Template hash mismatch. Expected ..., got ...`、`safe_filename` 的原值等直接回給前端。`saved_to` 也回傳伺服器上的絕對或相對路徑。這些都違反 `ApiError` docstring 所寫的「訊息不含內部細節」與 P0-1。
**修正：** `app.logger.exception(...)` 寫入日誌，對外只回固定訊息，例如 `ApiError("產生 PDF 失敗，請聯繫系統管理員", 500)`；移除 `saved_to`，或只回傳檔名。

### WR-03：`UnsafeIdentifierError` 在多處未被捕捉，合法業務輸入會觸發 500

**檔案：** `src/elc_audit_engine/attachment_store.py:178`、`:189`；`src/elc_audit_engine/generators/appeal.py:359`；`server.py:1133`、`server.py:1054`
**問題：** `list_attachments` 的 `safe_filename(order_seq)`、`delete_attachment` 的 `safe_filename(case_seq)`、`generate_evidence_packet_print` 的 `safe_filename(case_id)` 都可能拋 `UnsafeIdentifierError`（ValueError）→ 500。`/api/appeal/generate` 在未帶 `has_attachment` 且該 case 目錄存在時，會經 `has_attachment→list_attachments` 對 `order_seq`（任意 ≤200 字元字串，例如含空白或 `.`）拋錯，整支申復草稿端點因此回 500。
**修正：** server 加上 `@app.errorhandler(UnsafeIdentifierError)` 回 400；`has_attachment` 內以 try 包住整段並回 False。

### WR-04：缺少請求大小上限，且列印端點的輸入未驗證

**檔案：** `server.py:69`、`server.py:997`、`server.py:1071-1075`
**問題：** 沒有設定 `app.config["MAX_CONTENT_LENGTH"]`，multipart 與 JSON 請求大小都沒有上限。附件上傳端點用 `file.read()` 一次把整個檔案讀進記憶體後才檢查 10MB。`/api/deduction/print` 的 `records` 接受任意長度、任意元素型別的 list（非 dict 元素會觸發 AttributeError，數十萬列會讓 soffice 長時間佔用 CPU）。
**修正：**
```python
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024
if not all(isinstance(r, dict) for r in payload_records) or len(payload_records) > 500:
    raise ApiError("records 格式不合法或超過 500 筆")
```
附件改用 `file.stream.read(_MAX_ATTACHMENT_BYTES + 1)` 讀取。

### WR-05：`has_attachment` 未驗證型別，字串 "false" 會被當成 True，p7 輸出 Y

**檔案：** `server.py:878`
**問題：** `data.get('has_attachment')` 直接傳入 `build_appeal_draft`，`"Y" if draft.has_attachment else "N"` 會把 `"false"`、`"N"`、`0.0` 以外的任何值視為真。申復 XML 的 p7 會被錯誤標示為有附件，健保署查無附件時可能以此駁回。
**修正：** 比照 `is_appealing`：`if 'has_attachment' in data and not isinstance(data['has_attachment'], bool): raise ApiError(...)`。

### WR-06：soffice 轉檔直接輸出到共用 OUTPUT_DIR，可能回傳過期 PDF 或其他請求的 PDF

**檔案：** `src/elc_audit_engine/generators/appeal_print/__init__.py:166-196`、`src/elc_audit_engine/generators/deduction_print/__init__.py:54-79`
**問題：**
- `--outdir output_dir` 直接寫入正式目錄。`appeal_print` 以 `os.path.isfile(pdf_path)` 判斷成功，但若上次同名 PDF 仍在，而 soffice 失敗時仍回 returncode 0（soffice 常見行為），就會回傳**過期的 PDF**。
- `deduction_print` 完全不檢查輸出檔是否存在，也沒有處理 `subprocess.TimeoutExpired`。
- 同一 case_id 的併發請求（stem 相同）會互相覆寫。
**修正：** 一律輸出到 `tmp`，確認檔案存在且大小 > 0 之後，再 `os.replace(tmp_pdf, pdf_path)`（evidence_packet 的 pdf_exporter 已經採用 tmp 輸出，應統一成同一個 helper）。另外把三處重複的 soffice 呼叫抽成 `generators/_soffice.py`。

### WR-07：XML 1.0 不允許的控制字元沒有過濾，申復 XML／ODT 會產出無效 XML

**檔案：** `src/elc_audit_engine/generators/appeal_xml.py:43-52`、`src/elc_audit_engine/generators/appeal_print/odt_fill.py:418-430`、`:603-609`、`src/elc_audit_engine/generators/deduction_print/odt_fill.py:238-245`
**問題：** `ET` 會轉義 `<>&`，但不會拒絕 `\x00-\x08\x0b\x0c\x0e-\x1f`。核減 CSV 的「追扣原因」或「院所說明」若夾帶這些字元（Big5／Excel 匯出很常見），產出的 XML 會被健保署上傳端拒收，ODT 則讓 soffice 失敗。odt_fill 所稱的「序列化預檢」其實抓不到這類錯誤。
**修正：**
```python
_XML_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
def _xml_safe(v: str) -> str:
    return _XML_ILLEGAL.sub("", v)
```
在 `_add_fields` 與 `set_cell_text` 統一套用，並把被移除的欄位名記入 warnings。

### WR-08：佐證包把 PDF 附件送進 PIL，在正式文件中印出「載入失敗」錯誤框

**檔案：** `src/elc_audit_engine/generators/evidence_packet/builder.py:166-184`、`src/elc_audit_engine/generators/evidence_packet/__init__.py:80-88`
**問題：** builder 對所有附件（含 `application/pdf`）呼叫 `process_and_scale_image`，PIL 無法開啟 PDF，於是在送審文件中插入紅字「附件檔【...】載入失敗: cannot identify image file '<完整路徑>'」。實際上這些 PDF 之後會被 `pdf_exporter` 附加到文件尾端，錯誤框是誤報，還洩漏伺服器路徑。`record.get("filename", os.path.basename(file_path))` 會先求值 default，`file_path` 為 None 時直接拋 TypeError。加密的 PDF 附件也會讓 `PdfReader` 拋錯，導致整包失敗。
**修正：** builder 依 mime_type 分流，PDF 只列出「見附錄 PDF 第 N 頁起」；錯誤訊息不含路徑；`filename = record.get("filename") or (os.path.basename(file_path) if file_path else "未知")`；PDF 合併時逐檔 try，失敗記入 warnings。

### WR-09：`run_case_pipeline` 同一流水號多筆醫令時仍可能互相覆寫

**檔案：** `src/elc_audit_engine/pipeline.py:242-250`
**問題：** (1) 若 `appeal_options["file_stem"]` 有值，所有 records 都會用同一個 stem，最後只剩一份。(2) 同一 case_seq 下出現兩筆相同 order_code（不同 order_seq，實務上常見，例如同一醫令開兩次）時，第 2、3 筆都會得到 `{case_seq}_{order_code}`，後者覆寫前者。docstring 宣稱「C7 保底」，實際上保不住。
**修正：** `file_stem = f"{case_seq}_{record.order_seq or seen[case_seq]}"`（以醫令序或遞增序號區分），忽略或拒絕在多筆情況下傳入的共用 `file_stem`。

### WR-10：p8/p9 由四段文字無分隔直接串接，段落邊界與標題全數遺失

**檔案：** `src/elc_audit_engine/generators/appeal.py:390`；`src/elc_audit_engine/generators/appeal_print/field_mapping.py:187-192`
**問題：** `"".join(s.text for s in sections)` 讓「①案情摘要」的最後一句直接黏到「②醫療必要性」的第一句，送進健保署的申復理由沒有任何段落標示。ODT 的 `p.text` 中的 `\n` 在 ODF 會被壓縮成空白，紙本清單的理由欄也因此變成一整段。字數統計（`total_chars`）不含分隔符，加入分隔符後需要一起納入計算。
**修正：** `reason_full = "\n".join(f"{s.title}：{s.text}" for s in sections)`，並以這個字串重新計算字數與裁剪；ODT 端以 `text:line-break` 元素表示換行。

### WR-11：PHI 快照無限期保留於 data/uploads，與「PHI 最小化」註解矛盾；同秒匯入互相覆寫

**檔案：** `server.py:297-304`、`server.py:709-711`、`server.py:967-969`
**問題：** 原始上傳檔會即時刪除（註解寫「PHI 最小化」），但解析後的完整 PHI（姓名、SOAP、身分證遮罩號）以 JSON 形式永久存放在 `data/uploads/{kind}_{ts}.json`，與 CaseStore 重複儲存。時間戳只精確到秒，同一秒兩次匯入會互相覆寫。CaseStore 已成為單一真實來源，這份快照只剩下遷移用途。
**修正：** 遷移完成後停止寫出快照（或加上保存期限清理），檔名改用 `uuid`。

### WR-12：`list_all(limit=1000)` 靜默截斷；GET 清單不含狀態

**檔案：** `src/elc_audit_engine/case_store/store.py:323-338`、`server.py:498-500`、`server.py:735-737`
**問題：** 超過 1000 件後，較新的案件（ORDER BY created_at ASC）不會出現在清單中，前端也不會收到任何提示。回傳的只有 `payload`，不含 `state`／`failure_reason`，前端無法得知哪些案件已預審、哪些失敗。
**修正：** 支援分頁參數（`?offset=&limit=`）並回傳 `total`，每筆附上 `state`、`failure_reason`、`case_id`。

### WR-13：核減明細模板缺 sha256 sidecar 時靜默跳過完整性校驗

**檔案：** `src/elc_audit_engine/generators/deduction_print/template.py:369-374`
**問題：** appeal_print 對 `*_print_base.odt` 缺少 sidecar 時會拒絕執行（T-11-06），deduction_print 卻直接回 None 並跳過校驗。兩者對同一威脅的處理不一致，刪掉 `.sha256` 就能繞過竄改偵測。
**修正：** 共用 appeal_print 的 `_load_expected_sha256`（`_print_base.odt` 缺 sidecar 時拋錯），並刪除重複的 `verify_template_hash` 實作。

### WR-14：ODT 注入的模板定位缺少防呆，且修改 ElementTree 全域命名空間表

**檔案：** `src/elc_audit_engine/generators/appeal_print/odt_fill.py:540`、`:564-566`、`src/elc_audit_engine/generators/deduction_print/odt_fill.py:260`
**問題：** `re.search(...).group(0)` 找不到根元素時會拋 AttributeError，不是自訂的 FillError。`children[head_pos - 1]` 在 head_pos=0 時會取到最後一個元素（負索引），造成錯位複製。`ET.register_namespace` 修改的是 process 全域登錄表，多執行緒下兩種模板的前綴可能互相污染。
**修正：** 以 `m = re.search(...); if m is None: raise AppealPrintFillError(...)` 處理找不到的情況；檢查 `0 < head_pos < len(children)-1`；命名空間只在模組載入時用固定 ODF 前綴註冊一次。

## Info

### IN-01：`build_appeal_draft` 的 docstring 被放在程式碼之後，已失效

**檔案：** `src/elc_audit_engine/generators/appeal.py:357-376`
**問題：** `if has_attachment is None: ...` 寫在 docstring 之前，三引號字串因此變成無作用的表達式，`help()` 和 IDE 都看不到文件。函式內 import `attachment_store` 也讓號稱「純組裝層」的模組帶有 I/O 副作用。
**修正：** 把 docstring 移回函式第一行；把附件查詢移到呼叫端（server／pipeline），以參數傳入。

### IN-02：死碼與未使用的匯入

**檔案：** `server.py:266-267`、`:319-320`、`:644`、`:710`、`:920`、`:968`（`_sampling_cases`／`_appeal_cases` 只寫不讀）；`server.py:1089`、`:1143`（函式內重複 `from config import settings`，遮蔽模組層名稱）；`scripts/build_evidence_packet.py:151`、`:160`（`safe_filename` 未使用、`--case-seq` 參數解析後未使用）；`src/elc_audit_engine/case_store/db.py:66`（`_ALLOWED_TABLES` 未使用）；`src/elc_audit_engine/generators/reinforcement_report.py:206-210`（`_timeline_summary` 未使用）。
**修正：** 移除上述死碼；`--case-seq` 若要保留，應用來覆寫或驗證 payload 的 case_seq。

### IN-03：佐證包 cover_info 大部分沒被使用，且預設值屬於捏造

**檔案：** `src/elc_audit_engine/generators/evidence_packet/__init__.py:34-44`、`builder.py:131-136`
**問題：** `case_class` 預設 `"01"`，違反「缺值不捏造」原則。`total_*` 統計和 `facility` 都已計算，builder 卻沒有使用，封面缺少院所名稱與核減點數。`sum(order.get("deduct_amount", 0) ...)` 遇到 None 會拋 TypeError。
**修正：** 預設值改為 None；builder 封面應實際渲染院所與統計欄位；加總時以 `or 0` 處理 None。

### IN-04：server.py 1193 行且 import 即產生副作用

**檔案：** `server.py:124`、`:319-322`、`:372`
**問題：** 模組 import 時就會載入 API key、初始化 SQLite、執行遷移、讀取 JSON 快照，測試與 CLI 無法在不觸發這些副作用的情況下匯入。路由、驗證、轉換邏輯（`_to_*_case`）和示範資料全部混在同一個檔案。
**修正：** 見文末「改善建議」第 1 點（app factory＋blueprint）。

### IN-05：`write_evidence_packet` 的路徑穿越檢查無效且位置錯誤

**檔案：** `src/elc_audit_engine/generators/evidence_packet/__init__.py:72-74`
**問題：** `output_dir` 永遠來自 settings 或 CLI，這項檢查在計算 `output_pdf_path` **之後**才執行，也擋不住絕對路徑，只是形式上的防線。
**修正：** 移除這項檢查；若要限制，應以 `os.path.realpath` 與允許的根目錄比對。

### IN-06：`replay_gold_standard.py` 錯誤訊息把 URL 寫死

**檔案：** `scripts/replay_gold_standard.py:37-41`
**問題：** 訊息寫死 `localhost:8080`，實際檢查的是 `LLAMA_CPP_BASE_URL`。
**修正：** 改為 `f"llama.cpp server 未在 {LLAMA_CPP_BASE_URL} 啟動"`。

### IN-07：`build_appeal_xml.py` 未加入專案根路徑

**檔案：** `scripts/build_appeal_xml.py:13-19`
**問題：** 其他腳本都會插入 `_PROJECT_ROOT`，唯獨這支沒有。直接以 `python scripts/build_appeal_xml.py` 執行時，若 `config` 模組被間接匯入就會失敗，行為不一致。
**修正：** 比照 `build_appeal_print.py:30-32` 補上 sys.path 設定。

---

## 改善建議（結構性，依優先序）

1. **拆分 server.py 並改用 app factory**：`create_app(config)`，依 `sampling`／`appeal`／`attachments`／`print` 拆成 4 個 blueprint，把 `_to_*_case` 移到 `ingest/case_mapping.py`，示範資料移到 fixture。這樣 import 不再帶副作用，也能對各 blueprint 個別套用認證政策（修正 CR-01 時不必大改）。
2. **建立單一「案件識別」模型**：以 CaseStore 的 `case_id`（全域唯一，包含批次或自然鍵）作為所有下游的主鍵，包括附件目錄、輸出檔名、佐證包、p7 判定。`case_seq` 只當顯示與 XML 欄位值，**永遠不當查詢鍵**。這一步可以一次解決 CR-02、CR-03，以及 3f7f097 那一類反覆出現的 case_id／case_seq 混淆。
3. **CaseStore 擴充為 artifacts／attachments 的唯一真實來源**：新增 `attachments` 與 `artifacts`（appeal_draft、tracking）表，所有寫入走 SQLite 交易；`transition` 改成條件式 UPDATE，並提供多步 `advance()`。可修正 CR-04、CR-09、CR-10、WR-01。
4. **統一產出管線**：抽出共用的 `generators/_odf.py`（命名空間、`set_cell_text`、控制字元過濾、zip 重打包、模板 hash 校驗）與 `generators/_soffice.py`（tmp 輸出、原子搬移、逾時與錯誤脫敏），消除 appeal_print／deduction_print／evidence_packet 三份重複實作（WR-06、WR-07、WR-13、WR-14）。
5. **欄位契約以型別固定**：用 TypedDict 或 dataclass 定義「CaseStore appeal payload」、「deduction print record」、「evidence packet input」，並在 server 邊界以 schema 驗證（WR-04、WR-05），避免 CR-06 那類鍵名漂移。
6. **補上缺漏的回歸測試**：第二次匯入的碰撞、跨案件 case_seq 附件隔離、HTTPException 狀態碼、LLM 失敗時狀態轉入 failed、佐證包內容包含草稿段落、`/output` 下載，以及 `.gitignore` 涵蓋 `data/attachments`（可用 `git check-ignore` 測試）。

---

_審查時間：2026-09-26T08:47:58Z_
_審查者：Claude (gsd-code-reviewer)_
_深度：deep_
