# Phase 9: HIS 服務化（剩餘範圍：端點接 CaseStore＋Package Builder）- Research

**Researched:** 2026-08-07
**Domain:** (1) Flask 端點與既有 SQLite 狀態機／檔案落盤的整合遷移；(2) 健保署申復 XML 序列化（Big5、固定標籤結構）
**Confidence:** HIGH（兩個子域皆有可程式化驗證的一手依據：現行程式碼可讀、官方規格文件可轉檔解析）

## Summary

本研究涵蓋 Phase 9 剩餘兩項 Success Criteria 的規劃基礎。

**端點接 CaseStore（09-03）**：現行 `server.py` 的四個匯入／查詢端點（`/api/sampling/import`、`/api/appeal/import`、`/api/sampling/cases`、`/api/appeal/cases`）繞過 `case_store` 子套件，直接用 `_save_cases_json`／`_load_latest_cases` 落盤裸 JSON 陣列到 `data/uploads/{kind}_{timestamp}.json`，且用全域可變模組變數 `_sampling_cases`／`_appeal_cases` 快取於記憶體。`CaseStore`（09-02 交付）已提供完整的 `create/get/transition/history/list_by_state/list_all/counts_by_state` API，但 `payload` 是不透明 JSON blob（`json.dumps(payload)`），**不需要**逐欄位映射到 SQL 欄位——只需決定「案件生命週期的哪個時間點呼叫 `CaseStore.create()`／`.transition()`」。核心技術決策已經很清楚：匯入時 `create()`（狀態=`imported`），若匯入成功且結構化完成則立即 `transition()` 到 `parsed`；審核／預審呼叫視為 `reviewing`→`reviewed`；申復產生視為 `appealed`；尚無「送出」端點對應 `submitted`（Phase 10 範圍或本 phase 需新增一個標記端點，取決於使用者裁示）。舊 `data/uploads/*.json` 檔案是**單次遷移**候選（伺服器啟動時掃描一次，逐筆 `CaseStore.create()`，用 `try/except DuplicateCaseError` 做冪等），不建議做成常駐雙寫機制。

**Package Builder（申復 XML，09-04）**：`officialdocument/電子申復文件格式/` 下的 `.doc` 檔案**可**用「LibreOffice headless 轉 .docx → pandoc 轉純文字」（沿用 Phase 2 `doc_converter.py` 手法）程式化解析，且已實測轉出的規格文本明確標示「(XML檔案格式)」與完整標籤表——`门诊申復上傳格式作業說明.doc` 甚至含逐行 XML 範例與根元素/區段/欄位標籤命名規則。XML 結構為 `<outpatient><tdata>...</tdata><ddata><dhead>...</dhead><dbody>...<pdata>...</pdata>...</dbody></ddata><edata>...</edata></outpatient>`，宣告 `<?xml version="1.0" encoding="Big5"?>`。這與 Phase 3 解析申報 XML 用的 `tdata/ddata/dhead/dbody/pdata` 標籤族完全對稱（同一套 t/d/p 前綴慣例），可視為「反向序列化」既有解析邏輯的鏡像實作。Python 標準庫 `xml.etree.ElementTree` 完全足以產出這個結構（無巢狀屬性、無 namespace、無 DTD 依賴），**不需要新依賴**。已知欄位缺口（p3/p4/p5 為 null）與規格文件記載的「若無則免填」（△符號）欄位語意一致——不是 bug，是規格允許的合法狀態。

**Primary recommendation:** 09-03 用「匯入即 create＋單次啟動遷移」的最小整合模式接線 CaseStore，不动既有回應 JSON 契約（前端相容）；09-04 用 `ElementTree` 手刻建構器（非 lxml/jinja2），輸出 Big5 編碼＋標籤依 D-14d／appeal.py 既有欄位對映，段落層級（tdata/ddata/pdata/edata）批次組裝，統扣段（edata）暫標記為 Phase 9 不含（本 phase 只有單一案件申復，非統扣彙整，可用最小 stub 或直接省略 edata 區段——需使用者確認）。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 匯入案件生命週期記錄（imported/parsed） | API/Backend（`server.py` 匯入端點） | Database/Storage（`CaseStore`） | 匯入是唯一「案件誕生」時刻，端點層決定何時建案；持久化細節封裝在 CaseStore |
| 案件狀態轉換（reviewing/reviewed/appealed） | API/Backend（`/api/sampling/audit`、`/api/appeal/generate`） | Database/Storage | 業務端點呼叫既有引擎後，額外呼叫 `CaseStore.transition()`；狀態機規則本身在 Database/Storage 層（`states.py`） |
| 既有 uploads JSON → CaseStore 遷移 | API/Backend（啟動期 one-shot 函式） | Database/Storage | 遷移邏輯是一次性程序，掛在 `_init_*` 啟動流程；不是常駐雙寫 |
| GET 案例清單回應 | API/Backend | Database/Storage（`CaseStore.list_all`） | 端點需把 `CaseRecord.payload` 攤平回既有前端契約（`_to_sampling_case` 等函式輸出格式不變） |
| 申復 XML 序列化 | API/Backend（新模組，非 Flask 路由本體） | — | 序列化是純資料轉換，不涉及網路請求；可獨立於 Flask 之外作為 `elc_audit_engine.generators` 或新 `package_builder` 子套件的職責 |
| XML 檔案編碼／命名（Big5、TOTFA.xml 慣例） | API/Backend（輸出組裝層） | CDN/Static（若未來需下載端點） | 官方規格對編碼與檔名有硬性規定，屬序列化層責任；HTTP 下載（若需要）是薄封裝 |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `xml.etree.ElementTree`（stdlib） | Python 3.12 內建 | 建構申復 XML 樹並序列化 | 零依賴（D2 原則）；結構單純（無 namespace/attribute-heavy schema），stdlib 完全勝任；專案既有 `ElementTree` 慣例可查（申報 XML 解析器可能已用，見下方驗證） |
| SQLite（stdlib `sqlite3`，經 `CaseStore`） | 既有 | 案件狀態持久化 | 09-02 已交付，本階段純接線，不新增資料層 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `codecs`（stdlib） | 內建 | Big5 編碼寫檔 | `ElementTree.write(..., encoding="big5")` 原生支援，不需額外套件 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `xml.etree.ElementTree` | `lxml` | lxml 效能更好、XSD 驗證更完整，但屬第三方依賴，違反 D2「零非必要依賴」；本案 XML 樹淺（4 層）且無 schema 驗證需求（官方沒提供 XSD 檔案，只有文字規格），無需 lxml |
| `ElementTree.write()` 內建序列化 | Jinja2 模板字串拼接 | 手刻字串在 CDATA／特殊字元轉義（`< > & ' "` 需轉全形，見規格表8）上容易出錯；`ElementTree` 的 `.text` 賦值＋內建序列化器可正確處理標準 XML escaping，但**全形轉換**（官方要求半形特殊符號→全形，非標準 XML escaping）仍需手動前處理字串 |
| Big5 手動 encode | 保留 UTF-8 內部運算，只在最終 `.write()` 呼叫指定 `encoding="big5"` | 建議走後者——與 Phase 3 申報 XML 解析器的 Big5 偵測／回退邏輯（`parsers/submission.py` 一類）呈鏡像對稱，內部一律 Python str（Unicode），僅在檔案 I/O 邊界轉碼 |

**Installation:** 無需新增（`xml.etree.ElementTree` 為 stdlib）。

**Version verification:**
```bash
python3 -c "import xml.etree.ElementTree as ET; print(ET.__name__)"
```
確認：Python 3.12（`pyproject.toml` `requires-python = ">=3.12"`）內建，無版本疑慮。

## Architecture Patterns

### System Architecture Diagram

```
09-03（端點接 CaseStore）資料流：

  HTTP POST /api/sampling/import
        │
        ▼
  [ingest.parse_sampling_csv / OCR pipeline]  (現行不變)
        │
        ▼
  cases: list[dict]  (現行 _to_sampling_case 契約不變)
        │
        ├──► CaseStore.create(case_id=f"SAMP-{idx:04d}", kind="sampling",
        │                       case_seq=rec.case_seq, order_code=rec.order_code,
        │                       payload=case_dict, actor=g.caller_id)
        │        │
        │        ▼
        │    SQLite: cases (state=imported) + case_transitions (NULL→imported)
        │
        └──► [既有] _save_cases_json（可選：過渡期並存，或替換為純 CaseStore 讀寫）
        │
        ▼
  HTTP 200 {"status": "success", "imported": N, ...}  (格式不變)

  ---

  HTTP GET /api/sampling/cases
        │
        ▼
  CaseStore.list_all(kind="sampling")  → tuple[CaseRecord, ...]
        │
        ▼
  [攤平] record.payload for record in records  → list[dict]（還原既有前端契約）
        │
        ▼
  HTTP 200 [...]  (與現行 _sampling_cases 回應格式一致，前端零改動)

  ---

  HTTP POST /api/sampling/audit  (現行呼叫 run_presubmission_check，不變)
        │
        ▼
  [新增] CaseStore.transition(case_id, "parsed") 或 "reviewing"→"reviewed"
         （視呼叫時機：audit 端點目前是無狀態逐筆判定 API，不含 case_id 概念
          ——需前端傳入 case_id 才能對應到既有案件，這是需使用者裁示的缺口）
        │
        ▼
  HTTP 200 {...}  (現行格式不變)


09-04（Package Builder）資料流：

  appeal_{流水號}.json (Phase 7 render_appeal_json 產出，含 p1-p9)
        │
        ▼
  [新模組] xml_builder.build_appeal_xml(draft: AppealDraft, header: dict, dhead: dict)
        │
        ├─ 組 <tdata> (t1-t39 總表，部分為加總欄位，需呼叫端提供或另計算)
        ├─ 組 <ddata><dhead>d1,d2</dhead><dbody>d3,d4...<pdata>p1-p9</pdata></dbody></ddata>
        └─ (統扣 <edata> 段：本 phase 案件非統扣性質，可能可省略——需確認)
        │
        ▼
  ElementTree.write(path, encoding="big5", xml_declaration=True)
        │
        ▼
  TOTFA.xml（依官方命名規則，含於 zip；zip 打包可能超出本 phase 範圍——見 Open Questions）
```

### Recommended Project Structure
```
src/elc_audit_engine/
├── case_store/              # 09-02 已交付，本階段不改動內部
│   ├── store.py
│   ├── states.py
│   └── db.py
├── generators/
│   ├── appeal.py            # 既有，不改動（AppealDraft/render_appeal_json 契約穩定）
│   └── appeal_xml.py        # 新增：09-04 XML 序列化器（純函式，輸入 AppealDraft/dict → XML 字串或寫檔）
server.py                    # 09-03：新增 CaseStore 呼叫點，不改變路由介面/回應格式
```

### Pattern 1: 匯入即建案（Create-on-Import）
**What:** 匯入端點（`/api/sampling/import`、`/api/appeal/import`）在成功解析出案件清單後，逐筆呼叫 `CaseStore.create()`，`case_id` 沿用現有 `f"SAMP-{idx:04d}"`／`f"APP-{idx:04d}"` 命名（`safe_filename()` 已相容此格式：純 ASCII 英數字連字號）。
**When to use:** 每次成功匯入（不含被拒收列）。
**Example:**
```python
# 沿用現行 _to_sampling_case 產出的 dict 結構作為 payload
from elc_audit_engine.case_store.store import CaseStore, DuplicateCaseError

_case_store = CaseStore()  # 沿用 config.settings.CASES_DB_PATH，模組層單例

def _persist_cases(kind: str, cases: list[dict], actor: str | None) -> None:
    for case in cases:
        try:
            _case_store.create(
                case_id=case["id"],       # e.g. "SAMP-0001"
                kind=kind,
                case_seq=case.get("case_seq"),
                order_code=case.get("order_code"),
                payload=case,
                actor=actor,
            )
        except DuplicateCaseError:
            # 重複匯入同一批次（如使用者重複上傳相同檔案）——
            # 依 P0-2/P1-1 同源原則，不得靜默覆寫；此處記錄但不中斷整批匯入。
            app.logger.warning("case already exists, skip: %s", case["id"])
```
**Source:** 衍生自現行 `server.py:_to_sampling_case`／`CaseStore.create` 簽名（`store.py:117`）。

### Pattern 2: 啟動期一次性遷移（One-Shot Migration on Boot）
**What:** 伺服器啟動時掃描 `data/uploads/*.json`，把既有裸 JSON 陣列逐筆匯入 `CaseStore`（僅在對應 case_id 尚不存在時），取代目前的 `_load_latest_cases()` 記憶體快取模式。
**When to use:** 一次性，於 `_init_api_keys(app)` 同層級的啟動流程呼叫；**不建議**做成每次請求都比對雙來源的常駐雙寫邏輯（徒增複雜度且容易出現「JSON 檔與 SQLite 不同步」的新故障模式）。
**Example:**
```python
def _migrate_legacy_uploads(store: CaseStore) -> None:
    """一次性遷移：data/uploads/*.json → CaseStore（冪等，重複執行安全）。"""
    for kind in ("sampling", "appeal"):
        cases = _load_latest_cases(kind)  # 沿用既有函式讀最新一份
        if not cases:
            continue
        for case in cases:
            try:
                store.create(case_id=case["id"], kind=kind, payload=case,
                              case_seq=case.get("case_seq"),
                              order_code=case.get("order_code"))
            except DuplicateCaseError:
                pass  # 已遷移過，冪等略過
```
**Source:** 衍生自現行 `_load_latest_cases`（`server.py:265`）＋ `CaseStore.create`。

### Pattern 3: XML 樹狀建構＋Big5 序列化
**What:** 用 `ElementTree.Element`／`SubElement` 依官方標籤命名（`t1`..`t39`、`d1`..`d7`、`p1`..`p9`）逐一組裝，最終以 `ET.ElementTree(root).write(path, encoding="big5", xml_declaration=True)` 輸出。
**When to use:** Package Builder 產出申復 XML 檔案時。
**Example:**
```python
import xml.etree.ElementTree as ET

def build_appeal_xml(tdata: dict, ddata_list: list[dict]) -> ET.Element:
    """組裝 <outpatient><tdata>...</tdata><ddata>...</ddata>...</outpatient>。

    tdata: {"t1": 醫事機構代碼, "t2": 費用年月, ...}（僅含有值欄位，
        依官方規格「無資料不需出現該標籤」，見上傳格式作業說明 p.5）。
    ddata_list: 每筆 {"dhead": {"d1":.., "d2":..}, "dbody": {"d3":.., ...},
        "pdata_list": [{"p1":.., "p2":.., ...}, ...]}。
    """
    root = ET.Element("outpatient")
    tdata_el = ET.SubElement(root, "tdata")
    for key, value in tdata.items():
        if value is None or value == "":
            continue  # 官方規格：無資料的欄位不輸出標籤，非填空字串
        ET.SubElement(tdata_el, key).text = str(value)

    for entry in ddata_list:
        ddata_el = ET.SubElement(root, "ddata")
        dhead_el = ET.SubElement(ddata_el, "dhead")
        for key, value in entry["dhead"].items():
            if value is None or value == "":
                continue
            ET.SubElement(dhead_el, key).text = str(value)
        dbody_el = ET.SubElement(ddata_el, "dbody")
        for key, value in entry.get("dbody", {}).items():
            if value is None or value == "":
                continue
            ET.SubElement(dbody_el, key).text = str(value)
        for pdata in entry.get("pdata_list", []):
            pdata_el = ET.SubElement(dbody_el, "pdata")
            for key, value in pdata.items():
                if value is None or value == "":
                    continue
                ET.SubElement(pdata_el, key).text = str(value)
    return root

def write_appeal_xml(root: ET.Element, path: str) -> None:
    """Big5 編碼寫出（官方共同宣告：<?xml version="1.0" encoding="Big5"?>）。"""
    tree = ET.ElementTree(root)
    ET.indent(tree, space="")  # 官方未強制排版，但保留可讀性；縮排不影響判讀
    tree.write(path, encoding="big5", xml_declaration=True)
```
**Source:** 標籤結構與屬性依「門診申復上傳格式作業說明.doc」轉檔文字（本次研究第一手轉檔），第 217-260 行【表2】【表3】；空值省略規則見第 155 行「為節省檔案儲存空間...建議申復資料XML內容不需要出現該標籤」。

### Anti-Patterns to Avoid
- **雙寫 JSON＋SQLite 常駐並存：** 遷移完成後仍保留 `_save_cases_json` 作為「真實來源」、CaseStore 只是附加記錄——會製造兩個可能不同步的資料源，違反「系統故障必須與業務結論可區分」的專案核心原則（任一寫入失敗，另一邊卻成功，狀態即刻矛盾）。遷移後應以 CaseStore 為單一事實來源。
- **在 XML escaping 上依賴 stdlib 而忽略官方全形替換規則：** `ElementTree` 會自動把 `<`/`&`/`>` 轉成標準 XML entity（`&lt;`/`&amp;`/`&gt;`），但官方規格（【表8】）要求**申復理由等文字內容**中若出現這 5 個半形特殊符號（`< > & ' "`），應**替換為全形**（`＜ ＞ ＆ ＇ ＂`）再寫入，而非用 entity escape。兩者是不同的處理路徑——若只靠 stdlib 的預設 escaping，產出的 XML 雖然「XML 合法」，但**不符合健保署的申復內容格式要求**（官方檢核可能視為內容格式錯誤而非 XML 格式錯誤，兩種退件原則不同，見上傳格式說明第 577-611 行）。需在填入 `.text` 前手動 `str.translate()` 或 `str.replace()` 這 5 個字元。
- **把核減輸入 18 欄格式誤用來建模 XML 輸出欄位：** 已在 D-14a/D-14d 踩過的坑（見 STATE.md）。`DeductionRecord`（輸入）與申復 XML 的 `d`/`p` 欄位**編號雖然相似但語意不同**——例如輸入的「欄 10 醫令序號」對應輸出的 `p1`，並非直接同名同位；映射需逐一比對（見下方 Don't Hand-Roll 表格）。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| `.doc` 文字擷取 | 自製二進位 `.doc` parser | `soffice --headless --convert-to docx` + `pandoc -t plain`（或沿用既有 `doc_converter.py` 手法） | Phase 2 已驗證此路徑穩定（32 份文件、1633 節點），本機已安裝 `soffice`（LibreOffice 24.2.7.2）與 `pandoc`，零新依賴 |
| XML escaping | 手刻字串取代 `<`/`>`/`&` | `xml.etree.ElementTree` 內建序列化 | stdlib 已正確處理標準 XML 特殊字元逸出，避免手刻正則替換漏邊界情況（如屬性值 vs 文字內容的不同轉義規則——本案無屬性，但仍建議用標準庫） |
| Big5 編碼寫檔 | 手動 `str.encode('big5')` 再寫 bytes | `ElementTree.write(path, encoding="big5")` | stdlib 原生支援指定編碼寫出＋自動產生對應的 `encoding="Big5"` 宣告字串，避免宣告與實際位元組編碼不一致的低級錯誤 |
| 案件狀態一致性（狀態＋歷史原子寫入） | server.py 端點內手刻兩次 SQL INSERT | `CaseStore.transition()`（已用 `with conn:` 交易保證原子性） | 09-02 已完整交付並測試（65 測試），重複造輪子會失去既有的原子性保證 |

**Key insight:** 本 phase 剩餘範圍的兩個子域都有**明確、可程式化驗證的官方依據**（CaseStore 已是既有程式碼；XML 規格已可轉檔讀出逐欄定義），不需要用猜測或訓練知識填補——所有欄位對映與結構決策都應該回頭核對已轉出的規格文字（見本文件「Code Examples」與 Sources）。

## Common Pitfalls

### Pitfall 1: `_sampling_cases`／`_appeal_cases` 全域可變狀態與 CaseStore 並存造成的競態
**What goes wrong:** 若只在匯入端點寫入 CaseStore，但 GET 端點仍讀取模組層全域變數 `_sampling_cases`，會出現「CaseStore 有資料但 GET 端點看不到」或反之的不一致（尤其多 worker 部署時全域變數不共享，SQLite 才是跨行程一致的來源）。
**Why it happens:** 09-02 刻意未動 server.py，全域變數機制原封不動保留至今；09-03 若只加 `CaseStore.create()` 呼叫而不同步改寫 GET 端點的讀取來源，會產生「寫兩處、讀一處」的部分遷移狀態。
**How to avoid:** GET 端點（`get_sampling_cases`／`get_appeal_cases`）改為呼叫 `CaseStore.list_all(kind=...)` 並攤平 `payload` 回傳，徹底移除 `_sampling_cases`／`_appeal_cases` 模組變數依賴（或至少不再作為真實來源，僅保留 demo fallback 邏輯判斷「是否已有真實匯入資料」可用 `counts_by_state` 或 `list_all` 是否為空來取代 `is not None` 判斷）。
**Warning signs:** 匯入後 GET 端點回傳與匯入時不同的資料；重啟後 GET 端點行為與重啟前不一致（因為全域變數重啟後會重新從 JSON load，但 CaseStore 早已持久化）。

### Pitfall 2: `case_id` 生成時機與 CaseStore 的 `create()` 冪等假設衝突
**What goes wrong:** 現行 `f"SAMP-{idx:04d}"` 的 `idx` 是**當次匯入批次內的序號**（`enumerate(result.records, start=1)`），每次重新匯入都會從 1 開始——若同一批案件被匯入兩次（使用者重複上傳），會產生**同 case_id 但內容可能不同**的衝突，觸發 `DuplicateCaseError`。
**Why it happens:** `_to_sampling_case`／`_to_appeal_case` 的 `id` 欄位設計初衷是「畫面顯示用序號」，不是「跨匯入批次全域唯一識別碼」。
**How to avoid:** 兩個選項需使用者裁示：(a) 保留 `SAMP-0001` 格式但拒絕重複匯入（`DuplicateCaseError` 直接讓該筆匯入失敗並回報使用者，符合「系統故障需可見」原則）；(b) 引入批次識別碼前綴（如 `SAMP-{batch_uuid}-0001`）讓每次匯入天生不衝突，但會讓 case_id 變長且前端顯示邏輯需調整。**建議選 (a)**：符合現行「匯入覆蓋既有清單」的產品邏輯（`_sampling_cases = cases` 是整批取代，非累加），故 CaseStore 端也應該「整批匯入前，先確認舊案件已妥善轉移狀態或明確允許覆蓋」——需在 PLAN 階段與使用者確認「重新匯入同一批案件」的期望行為。
**Warning signs:** 測試中對同一 fixture 匯入兩次會出現非預期的 500 錯誤。

### Pitfall 3: `/api/sampling/audit` 是無狀態逐筆判定 API，缺少 case_id 輸入
**What goes wrong:** 現行 `/api/sampling/audit` 端點的輸入是 `order_code`／`soap_text`／`record_no` 等原始欄位，**不含 case_id**——它原本設計成「輸入任意醫令即可判定」的通用工具端點，不強制綁定已匯入的案件。若要讓 audit 呼叫觸發 `imported→parsed→reviewing→reviewed` 狀態轉換，前端必須額外傳入 `case_id`，這是**契約變更**（新增必要或選填欄位），需明確規劃。
**Why it happens:** 09-01（認證）與現行 audit 端點是先於 CaseStore 存在而設計的，兩者原本互不相依。
**How to avoid:** 在 PLAN 中列為明確任務：`/api/sampling/audit` 與 `/api/appeal/generate` 新增**選填** `case_id` 參數——有提供則呼叫 `CaseStore.transition()`；未提供則維持現行無狀態行為（向後相容，不破壞既有前端呼叫）。狀態轉換失敗（如 `IllegalTransitionError`）不應阻斷業務判定結果的回傳（判定與狀態記錄是兩件事，判定失敗才是需要 503 的情境；狀態轉換失敗更適合記錄警告而非讓整個請求失敗——但這點需與使用者確認是否要嚴格阻斷）。
**Warning signs:** 前端沒有同步更新以傳遞 case_id，導致狀態機永遠停在 `imported`，`reviewing`/`reviewed` 狀態形同虛設。

### Pitfall 4: XML 全形特殊字元轉換遺漏
**What goes wrong:** 申復理由（`p8_reason1`／`p9_reason2`，源自 `appeal.py` 的 `draft.reason1`/`draft.reason2`）若包含英文引號、`&`、`<`、`>` 等半形符號，依官方規格（【表8】）**必須替換為全形**才符合申復內容格式要求，而非依賴 XML 標準 escaping。
**Why it happens:** 開發者直覺會認為「XML 函式庫已經處理特殊字元了」而略過官方這條**內容層級**（非 XML 語法層級）的格式要求。
**How to avoid:** 序列化前對即將填入 `<p8>`／`<p9>` 等文字欄位的字串做半形→全形替換（`< > & ' "` → `＜ ＞ ＆ ＇ ＂`），可寫成獨立的純函式（如 `_to_fullwidth_specials(text: str) -> str`）並加測試覆蓋 5 個字元的邊界案例。
**Warning signs:** 產出的 XML 語法正確可解析，但送交健保署系統後被判定「資料內容格式錯誤」退件（本機無法驗證，需人工比對官方規格或未來取得驗證管道）。

## Runtime State Inventory

> 本 phase 為服務層整合（非改名/重構/遷移既有系統），但 09-03 涉及「既有落盤資料 → 新持久層」的資料遷移，故仍需檢視。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `data/uploads/{sampling,appeal}_{timestamp}.json`——目前唯一的持久化案件資料，非資料庫格式；`data/db/cases.sqlite3`（09-02 已建立 schema，但目前**無任何寫入邏輯**呼叫它——空表） | 需一次性遷移程式（見 Pattern 2），且遷移後應決定是否保留舊 JSON 檔案作為 audit trail 或直接歸檔 |
| Live service config | 無外部服務設定（本 phase 純本機檔案／SQLite），不涉及 n8n／Datadog 等外部平台 | 無 |
| OS-registered state | 無 OS 層級註冊（無 systemd/launchd/排程任務） | 無 — 已驗證：本專案未見任何 OS 層級服務註冊機制 |
| Secrets/env vars | `ELC_API_KEYS`（09-01 既有，不受本 phase 影響）；`CASES_DB_PATH`（09-02 已定義於 `config/settings.py`，本 phase 沿用，不需新增） | 無新增 env var 需求；若新增申復 XML 輸出目錄設定，建議沿用 `OUTPUT_DIR` 或新增 `APPEAL_XML_OUTPUT_DIR`（需使用者裁示） |
| Build artifacts | 無 pip/npm 套件安裝異動（`xml.etree.ElementTree` 為 stdlib，不影響 `pyproject.toml`） | 無 |

## Common Pitfalls（承上，Package Builder 專屬教訓延伸）

（已併入上方 Pitfall 1-4，此處不重複。）

## Code Examples

### 讀取 `.doc` 規格文件（沿用 Phase 2 手法，驗證可行）
```bash
# Source: 本次研究實測（2026-08-07），沿用
# src/elc_audit_engine/rule_repository/docx_tree/doc_converter.py 的
# _build_convert_cmd() 命令列組裝邏輯
soffice \
  "-env:UserInstallation=file:///tmp/lo_profile" \
  --headless --norestore --nolockcheck \
  --convert-to docx \
  --outdir /tmp/out \
  "officialdocument/電子申復文件格式/門診申復上傳格式作業說明.doc"

pandoc /tmp/out/門診申復上傳格式作業說明.docx -t plain -o /tmp/upload.txt
```
**驗證結果：** 轉檔成功（exit 0），輸出 805 行純文字，含完整【表1】-【表9】與逐標籤範例 XML（見本文件 Sources 引用行號）。`.doc`（電子申復格式及填表說明門診.doc）轉出 486 行，含 4 段（門診申復總表段/門診申復清單段/門診申復醫令段/門診申復醫令統扣明細段）的完整欄位表（符號／欄位ID／長度／屬性／說明）。

### 官方 XML 結構骨架（逐字對照規格文件範例，第 640-804 行）
```xml
<?xml version="1.0" encoding="Big5"?>
<outpatient>
  <tdata>
    <t1>9999999999</t1>  <!-- 醫事機構代碼 -->
    <t2>10401</t2>       <!-- 費用年月（民國年月，5碼） -->
    <t3>4</t3>            <!-- 申報類別：4申復送核 5申復補報 -->
    <t4>1040101</t4>      <!-- 申報日期（民國7碼） -->
    <t5>1040101</t5>      <!-- 申復日期（民國7碼） -->
    <!-- t6-t37 為各類案件申復件數/點數加總，t38/t39 為總計 -->
  </tdata>
  <ddata>
    <dhead>
      <d1>01</d1>  <!-- 案件分類 -->
      <d2>1</d2>   <!-- 流水編號 -->
    </dhead>
    <dbody>
      <d3>0</d3>   <!-- 樣本註記 -->
      <d4>Y</d4>   <!-- 整件核減註記（若無則免填，不輸出標籤） -->
      <pdata>
        <p1>2</p1>       <!-- 醫令序號 -->
        <p2>11</p2>      <!-- 醫令代碼 -->
        <p3>180</p3>     <!-- 改支序號（若無免填） -->
        <p4>120.38</p4>  <!-- 成數受理（若無免填） -->
        <!-- p5數量受理/p6點數受理/p7申復檔案連結/p8申復理由一/p9申復理由二 -->
      </pdata>
    </dbody>
  </ddata>
  <!-- edata（門診申復醫令統扣明細段）：本 phase 案件是否需要此段待確認 -->
</outpatient>
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `data/uploads/*.json` 裸檔＋模組全域變數快取 | `CaseStore`（SQLite＋顯式狀態機） | 09-02（已交付但未接線） | 09-03 需完成「舊機制→新機制」的切換，本研究文件即為該切換的依據 |
| `appeal_{流水號}.json`（Phase 7 內部契約） | + 申復 XML（健保署對外格式） | 本 phase（09-04） | JSON 是內部/審閱用契約，不變；XML 是新增的「最終上傳格式」輸出層，兩者並存（JSON 供醫師審閱，XML 供上傳） |

**Deprecated/outdated:**
- 無明確棄用項目——`_save_cases_json`／`_load_latest_cases` 遷移完成後應**移除**（而非棄用保留），因為雙路徑並存本身就是風險（見 Pitfall 1）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `edata`（申復醫令統扣明細段）在本 phase 範圍內可省略，因為目前案件皆為單筆醫令申復而非統扣類案件（案件分類含 `0` 統扣類才需要 edata，見規格【表2】備註「統扣案件」） | Architecture Patterns / Code Examples | 若使用者實際案件涉及統扣類（案件分類為 `0`），則本 phase 未涵蓋此段會導致 XML 結構不完整，健保署驗證會退件（見「XSD驗證檢核」段落：標籤放置區段錯誤） |
| A2 | `tdata` 的加總欄位（`t6`-`t37`、`t38`/`t39`）由呼叫端（Package Builder 使用者）提供或由簡單加總函式計算，本研究未實作該加總邏輯的精確業務規則（案件分類→對應哪個 t 欄位加總、西醫一般 vs 專案的判斷邏輯） | Summary / Code Examples | 若加總邏輯有誤，會導致「與清單平衡檢查」失敗（規格文件多處註記「2. 與清單平衡檢查」），屬健保署退件風險；此為規則細節，建議 PLAN 階段規劃獨立任務並輔以官方問答集交叉確認 |
| A3 | 案件狀態機的 `submitted` 狀態轉換（`appealed→submitted`）尚無對應端點——本 phase 假設「送出」是人工或 Phase 10（VPN／實機串接）範圍的動作，09-03 不需新增觸發 `submitted` 的端點 | Architecture Patterns | 若使用者期望 09-03 涵蓋「標記已送出」的端點（即使實際上傳仍是手動／未來 Phase 10 做），會遺漏一個小但明確的 API 缺口 |
| A4 | `case_id` 重複匯入時應拒絕（`DuplicateCaseError` 直接失敗）而非允許覆蓋 | Common Pitfalls / Pitfall 2 | 若使用者期望「重新匯入」應該覆蓋舊案件（例如訂正錯誤資料後重傳），則此假設會讓合理的業務操作變成錯誤；需使用者在 discuss-phase 或 PLAN 階段明確裁示 |

**風險摘要：** A1／A2 屬於「規格文件已提供答案但需要業務規則細節確認」的類型（非缺乏文件，而是規則複雜需要仔細拆解，建議獨立任務處理，不與 A3/A4 混在同一個 PLAN 任務）；A3／A4 屬於「需要使用者裁示的產品行為決策」。

## Open Questions

1. **`edata`（申復醫令統扣段）是否在本 phase 範圍內？**
   - What we know: 規格明確定義此段的欄位（案件分類/流水編號/醫令序號/醫令代碼/核減代碼/申復成數/申復數量/申復點數/申復檔案連結/申復理由一二），且與 `pdata` 段高度重疊（欄位語意相同，只是屬於「統扣案件」的彙總表示）。
   - What's unclear: 目前 `appeal.py` 的 `AppealDraft`／`DeductionRecord` 資料模型未見「統扣」相關欄位（`case_class` 若為特定值代表統扣，需回頭核對 D-14d 核減明細欄位定義中是否有此線索）。
   - Recommendation: PLAN 階段先以「單一醫令申復」（僅 tdata+ddata+pdata，不含 edata）為 MVP 範圍，若使用者確認實際案件含統扣類型，再追加 edata 序列化任務。

2. **`tdata` 加總欄位（t6-t39）如何計算？**
   - What we know: 規格文件明確列出每個 t 欄位對應「哪些案件分類」的件數/點數加總（如 t6=西醫一般案件申復件數，對應案件分類 `01`）。
   - What's unclear: 本專案目前的案件分類體系（`case_class`，D-14d 欄 5）實際會出現哪些值，需要與規格對照表（西醫一般/專案/洗腎/結核病/牙醫/中醫/預防保健/慢性病/居家照護/精神疾病社區復健/統扣）建立完整映射。
   - Recommendation: 建議先支援「單一案件、單一醫令」的最小申復 XML（`tdata` 大部分加總欄位可能為 0 或省略，因為「無資料則免填」），完整多案件批次彙整留待有真實批次申復需求時再擴充。

3. **Big5 編碼在含有生僻字或特殊符號的病歷資料下是否會編碼失敗？**
   - What we know: Phase 3 申報 XML 解析器已處理過 Big5 編碼偵測（`03-CONTEXT.md` 提及 Big5 偵測＋回退邏輯），代表輸入端已有處理生僻字的經驗。
   - What's unclear: `ElementTree.write(..., encoding="big5")` 遇到 Big5 無法表示的字元（如部分罕見人名用字）時的預設行為是拋 `UnicodeEncodeError` 還是靜默替換——需實測確認，並決定是否需要 `errors="xmlcharrefreplace"` 或類似降級策略。
   - Recommendation: PLAN 階段納入一個明確的測試案例：含至少一個 Big5 可能無法編碼字元的申復理由文字，驗證序列化行為（fail-fast 拋錯優於靜默替換，符合本專案一貫的誠實降級原則）。

4. **前端／使用者如何觸發 XML 產出與下載？**
   - What we know: `appeal.py` 的 `write_appeal()` 現行輸出到 `output_dir`（檔案系統），沒有對應的 Flask 下載端點。
   - What's unclear: 本 phase 的「Package Builder」是否包含一個新 API 端點（如 `POST /api/appeal/export-xml` 或類似），還是純粹是背景批次腳本（`scripts/` 底下）產出檔案供人工上傳。
   - Recommendation: 需在 discuss-phase 或 PLAN 階段確認：若需要 API 端點，需額外考慮認證（沿用 09-01 既有機制）、輸出檔案的安全路徑（沿用 `safe_paths.safe_filename`）與 zip 打包（官方規定 xml 需以 zip 包裹上傳，`TOTFA.zip` 內僅含 `TOTFA.xml`）。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `soffice`（LibreOffice headless） | 讀取 `.doc` 規格文件（研究階段已用；若 PLAN 決定把規格解析自動化為程式一部分則實作階段也需要） | ✓ | 24.2.7.2 | 若日後環境缺失，規格文件可人工轉檔一次後把純文字快取進 repo（不建議把 `.doc` 解析放進執行期熱路徑，一次性轉檔已足夠） |
| `pandoc` | `.docx` → 純文字二次轉換 | ✓ | 已驗證可執行（本次研究實測 exit 0） | 同上；`.docx` 亦可用 `python-docx`（既有依賴）直接讀取，不一定要靠 pandoc |
| `xml.etree.ElementTree` | 申復 XML 序列化（09-04 執行期核心依賴） | ✓ | Python 3.12 stdlib | 無需 fallback（stdlib 保證存在） |
| SQLite（`sqlite3` stdlib） | `CaseStore`（09-03 執行期核心依賴） | ✓ | Python 3.12 stdlib | 無需 fallback |

**Missing dependencies with no fallback:** 無。

**Missing dependencies with fallback:** 無（`.doc` 解析非執行期熱路徑依賴，僅規劃/開發階段一次性使用）。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x（`pyproject.toml` `[dependency-groups.dev]`） |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]`（`testpaths = ["tests"]`） |
| Quick run command | `./.venv/bin/python -m pytest tests/test_case_store.py tests/test_case_states.py -x -q`（既有基礎，09-03 會新增 `test_server_case_integration.py` 一類） |
| Full suite command | `./.venv/bin/python -m pytest -q`（現行基線 356 collected / 354 passed / 2 skipped） |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| Phase9-SC3-a | 匯入端點呼叫 `CaseStore.create()`，重複匯入同案件回報衝突而非靜默覆寫 | integration | `pytest tests/test_server_case_store_integration.py -k import -x` | ❌ Wave 0（需新建） |
| Phase9-SC3-b | GET 案例端點改讀 `CaseStore.list_all()`，回應格式與現行前端契約相容 | integration | `pytest tests/test_server_case_store_integration.py -k get_cases -x` | ❌ Wave 0 |
| Phase9-SC3-c | 舊 `data/uploads/*.json` 啟動期一次性遷移，冪等（重複執行不報錯不重複建案） | unit/integration | `pytest tests/test_server_case_store_integration.py -k migration -x` | ❌ Wave 0 |
| Phase9-SC4-a | `build_appeal_xml()` 依 `AppealDraft`/D-14d 欄位產出符合官方標籤結構的 `ElementTree` | unit | `pytest tests/test_appeal_xml.py -k build_appeal_xml -x` | ❌ Wave 0 |
| Phase9-SC4-b | 特殊字元（`< > & ' "`）在申復理由文字中正確轉為全形 | unit | `pytest tests/test_appeal_xml.py -k fullwidth -x` | ❌ Wave 0 |
| Phase9-SC4-c | Big5 編碼寫檔成功（含中文姓名/理由文字），輸出檔案可用 Big5 讀回驗證內容一致 | unit | `pytest tests/test_appeal_xml.py -k big5_roundtrip -x` | ❌ Wave 0 |
| Phase9-SC4-d | 無資料欄位（如 p3/p4/p5 為 None）不輸出對應標籤（符合官方「免填不出現標籤」規則） | unit | `pytest tests/test_appeal_xml.py -k omit_empty -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** 對應子模組的 quick run（`test_appeal_xml.py` 或 `test_server_case_store_integration.py` 單檔）
- **Per wave merge:** 全套件（`pytest -q`），確保 356+ 基線持續全綠，且新增測試數量與 PLAN 任務對應
- **Phase gate:** 全套件綠燈＋（若可行）人工以官方規格文件的範例值手動核對至少一份產出 XML 的欄位對映正確性

### Wave 0 Gaps
- [ ] `tests/test_server_case_store_integration.py` — 涵蓋 Phase9-SC3-a/b/c，需 fixture 模擬既有 `data/uploads/*.json` 與 CaseStore 雙態
- [ ] `tests/test_appeal_xml.py` — 涵蓋 Phase9-SC4-a/b/c/d
- [ ] Big5 roundtrip 測試需要 fixture：含中文姓名／理由的 `AppealDraft` 樣本（可沿用既有 `tests/fixtures/` 內 appeal 相關 fixture 延伸）
- [ ] 框架安裝：無需新增（pytest 已就緒）

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | 是（延續 09-01） | `require_api_key`／`before_request` 既有機制，本階段新增端點若有的話（如 XML export API）需納入 `_AUTH_EXEMPT_ENDPOINTS` 排除清單審查，預設受保護 |
| V3 Session Management | 否 | 無 session（API key 服務間認證，非使用者登入） |
| V4 Access Control | 部分適用 | 案件層級存取目前未區分「哪個呼叫方可存取哪個案件」（`g.caller_id` 僅用於審計，未做細粒度授權）；本 phase 範圍不含此需求，但序列化 PHI 資料（XML 含病患相關欄位）的端點若新增，仍需 API key 認證作為最低防線 |
| V5 Input Validation | 是 | 沿用既有 `_clean_str`／`_opt_int` 校驗模式；XML 序列化新增輸入（`case_id` 等）需用既有 `safe_filename()` 校驗，不可自行放寬白名單 |
| V6 Cryptography | 否 | 本階段不涉及加解密（Big5 編碼非加密） |

### Known Threat Patterns for {stack}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| XML 外部實體注入（XXE） | Tampering/Information Disclosure | 本 phase 是**輸出**（序列化，非解析外部 XML 輸入），XXE 風險極低；但若未來新增「讀取上傳的 XML 驗證回覆檔案」功能，`ElementTree.parse()` 需停用外部實體解析（`ElementTree` 預設已不解析外部 DTD，但仍建議明確使用 `defusedxml` 或核實 stdlib 版本行為，不在本 phase 範圍內） |
| 路徑穿越（case_id / file_stem 組檔名） | Tampering | 沿用既有 `safe_paths.safe_filename()`（`write_appeal()` 已用；XML 輸出路徑須比照辦理） |
| PHI 洩漏（審計日誌/錯誤訊息夾帶病患資料） | Information Disclosure | 沿用 09-01 既有原則：`_record_access_audit` 不記 request body；新增的遷移／XML 序列化日誌訊息（如 `app.logger.warning`）不得包含 SOAP／病患姓名等 PHI 欄位，僅記 case_id／狀態轉換等識別碼層級資訊 |
| 重複匯入造成狀態機混淆被利用（拒絕服務/資料混淆） | Tampering/DoS | `DuplicateCaseError` 明確拋出而非靜默處理，避免攻擊者/誤操作利用「重複匯入覆蓋」手法竄改既有案件狀態 |

## Sources

### Primary (HIGH confidence)
- `/home/hsu/Desktop/Elcinsurrence/server.py`（全文讀取，2026-08-07）— 現行七端點與匯入/落盤邏輯
- `/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/case_store/{store,states,db}.py`（全文讀取）— CaseStore API 簽名與交易保證
- `/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/generators/appeal.py`（全文讀取）— `AppealDraft`／`render_appeal_json` 契約，p1-p9 欄位定義
- `/home/hsu/Desktop/Elcinsurrence/src/elc_audit_engine/parsers/models.py`（全文讀取）— `DeductionRecord` 18 欄定義（D-14d）
- `officialdocument/電子申復文件格式/門診申復上傳格式作業說明.doc` — 本次研究以 `soffice --headless --convert-to docx` + `pandoc -t plain` 轉檔讀出全文（805 行），含 XML 共同宣告、根元素語法、欄位結構示意、完整範例 XML（第 640-804 行）、特殊字元轉換規則（【表8】第 545-559 行）、檔名命名規則（【表4】第 280-302 行）
- `officialdocument/電子申復文件格式/電子申復格式及填表說明門診.doc` — 同法轉檔讀出全文（486 行），含門診申復總表段（39 欄）／申復清單段（d1-d7）／申復醫令段（p1-p9）／申復醫令統扣明細段（欄1-11）逐欄定義（符號/長度/屬性/說明）
- Bash 實測（2026-08-07）：`which soffice pandoc pdftotext` 全部可用；`python3 -c "import xml.etree.ElementTree"` 成功

### Secondary (MEDIUM confidence)
- `.planning/STATE.md`（全文讀取）— D-14a/D-14d 教訓、P0-2/P1-1/P1-3/P1-5 同源原則、Phase 9 進度紀錄
- `.planning/phases/09-his-servicing/09-CONTEXT.md`（全文讀取）— Phase 9 決策脈絡、canonical_refs
- `.planning/ROADMAP.md`（全文讀取）— Phase 9 Success Criteria 原文

### Tertiary (LOW confidence)
- 無（本次研究未依賴未經驗證的 WebSearch 來源；官方規格文件已可直接程式化讀取，屬一手依據）

## Metadata

**Confidence breakdown:**
- Standard Stack（`xml.etree.ElementTree` 足夠）: HIGH — stdlib 能力已知，且已用 `python3 -c` 實測 import 成功
- Architecture（CaseStore 整合模式）: HIGH — CaseStore 完整原始碼已讀取，介面穩定（09-02 已測試交付）
- XML 結構規格: HIGH — 官方文件已用本機工具鏈完整轉檔並逐行讀出，非訓練知識推測
- Pitfalls: MEDIUM-HIGH — 前 3 項基於現行程式碼直接觀察（HIGH），第 4 項（全形轉換規則）基於官方文件明文（HIGH）但未經健保署實際驗證管道確認（本機無法測試上傳，Phase 10 阻塞範圍）
- 業務規則細節（tdata 加總、edata 是否需要）: MEDIUM — 規格文件有答案，但需要與實際案件資料分類體系交叉核對，已列入 Open Questions/Assumptions

**Research date:** 2026-08-07
**Valid until:** 30 天（官方規格文件版本日期為 104.02.11，穩定；CaseStore 為本專案內部程式碼，隨程式演進可能變動，故此研究對 09-03 部分的有效期應以「CaseStore 介面未變」為前提）
