# Phase 11: 紙本申復清單列印 - Pattern Map

**Mapped:** 2026-08-08
**Files analyzed:** 10（7 新增／3 修改）
**Analogs found:** 8 / 10

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/elc_audit_engine/generators/appeal_print/__init__.py`（新增；`render_appeal_print`＋`write_appeal_print`） | component（render 輸出通道） | transform + file-I/O | `src/elc_audit_engine/generators/appeal.py`（`render_appeal_markdown`／`write_appeal`） | exact |
| `src/elc_audit_engine/generators/appeal_print/field_mapping.py`（新增） | component（欄位映射） | transform | `src/elc_audit_engine/generators/appeal_xml.py`（`draft_json_to_appeal_xml_fields`） | exact |
| `src/elc_audit_engine/generators/appeal_print/odt_fill.py`（新增） | component（ET 注入＋zip 重打包） | transform + file-I/O | `src/elc_audit_engine/generators/appeal_xml.py`（`build_appeal_xml`／`write_appeal_xml` 的 ET 建構模式） | role-match |
| `src/elc_audit_engine/generators/appeal_print/template.py`（新增，可選一次性「布局壓縮基準模板」產生器） | utility（one-shot build） | batch + file-I/O | `src/elc_audit_engine/rule_repository/scripts/build_docx_trees.py` | role-match |
| `config/facility.json`（新增） | config | CRUD（load） | `config/llama_config.json` | exact |
| `config/settings.py`（修改：`FACILITY_CONFIG_PATH`＋`load_facility_config()`） | config（loader） | transform（import-time 設定＋載入函式） | `config/settings.py` 自身（`LLAMA_CONFIG_PATH`＋`load_llama_config()`） | exact |
| `scripts/build_appeal_print.py`（新增） | controller（CLI 入口） | batch + file-I/O | `scripts/build_appeal_xml.py` | exact |
| `tests/test_appeal_print.py`（新增） | test | N/A | `tests/test_appeal.py`＋`tests/test_appeal_xml.py`＋`tests/test_doc_converter.py` | exact |
| `tests/conftest.py`（修改：`requires_soffice`／`facility_config`／`sample_appeal_draft` fixture） | test（fixture） | N/A | `tests/conftest.py` 自身（`tmp_rule_db_path`）＋`tests/test_doc_converter.py`（`requires_soffice`） | exact |
| `officialdocument/電子申復文件格式/*_print_base.odt`（新增：壓縮基準模板資產，由 template.py 產出並 git 入庫） | data（版控資產） | file-I/O | `officialdocument/電子申復文件格式/30396_*.odt`（既有 git-tracked 官方模板） | role-match |

> 路徑註記：RESEARCH「Recommended Project Structure」以 `appeal_print.py` + `field_mapping.py` + `odt_fill.py`（+ 可選 `template.py`）建議 **package 結構**；planner 亦可折衷為單一模組 `appeal_print.py`。本 map 按 RESEARCH 建議的 package 結構分類，下述 `__init__.py` 的內容模式在單模組合併時套用於同一檔案。

## Pattern Assignments

### `src/elc_audit_engine/generators/appeal_print/__init__.py`（component, transform + file-I/O）

**Analog:** `src/elc_audit_engine/generators/appeal.py`

**渲染純函式模式**（lines 418-477，`render_appeal_markdown`：純字串組裝、無 I/O、None→「—」佔位）：
```python
def _fmt(value) -> str:
    """顯示用格式化：None/空字串 → 佔位符。"""
    if value is None or value == "":
        return "—"
    return str(value)

def render_appeal_markdown(draft: AppealDraft) -> str:
    """渲染申復草稿 Markdown（醫師審閱版，C7）。"""
    lines = ["# 申復理由草稿", ""]
    lines.append(
        f"- 案件分類：{_fmt(draft.case_class)}｜流水號：{_fmt(draft.case_seq)}"
    )
    ...
    return "\n".join(lines)
```

**輸出通道薄包裝模式**（lines 518-550，`write_appeal`：safe_filename 校驗 → makedirs → 寫檔 → 回傳路徑 tuple）：
```python
    # P1-3：stem 進檔名，未校驗會造成寫入型路徑穿越。校驗組合後的結果——
    # `{case_seq}_{order_seq}` 的底線在白名單內，合法組合不受影響。
    stem = safe_filename(file_stem or (case_seq or "unknown"), "file_stem/case_seq")
    os.makedirs(output_dir, exist_ok=True)
    md_path = os.path.join(output_dir, f"申復草稿_{stem}.md")
    json_path = os.path.join(output_dir, f"appeal_{stem}.json")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_appeal_markdown(draft))
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(render_appeal_json(draft))

    return md_path, json_path
```

**包導出模式**（`src/elc_audit_engine/generators/__init__.py` lines 16-44）：從子模組 `from .appeal import (...)` 匯入並維護 `__all__`。本 phase 新 API（`render_appeal_print`／`write_appeal_print`／`build_appeal_print_base` 等）應加入 `generators/__init__.py` 的匯入與 `__all__`（planner 列入修改項）。

**應用規則：**
- `render_appeal_print(...)` 是純函式（不吃 config/環境變數、不做 I/O），回傳產出的 filled ODT 路徑或 PDF 路徑；`write_appeal_print(output_dir, case_seq, draft, facility, ...)` 是薄包裝（safe_filename 校驗 + makedirs + 呼叫 odt_fill + 呼叫 soffice），回傳 `(pdf_path,)`。
- 檔名沿用一案一檔案慣例：`申復清單_{stem}.pdf`（`{stem}` = `{case_seq}_{order_seq}` 可覆寫）。

---

### `src/elc_audit_engine/generators/appeal_print/field_mapping.py`（component, transform）

**Analog:** `src/elc_audit_engine/generators/appeal_xml.py`

**欄位映射純函式模式**（lines 121-149，`draft_json_to_appeal_xml_fields`：把 render JSON dict 逐欄轉成官方格式 dict，None 值保留）：
```python
def draft_json_to_appeal_xml_fields(appeal_json: dict) -> tuple[dict, list[dict]]:
    """將 render_appeal_json() 產出的 JSON dict 轉換為 build_appeal_xml() 的入參。"""
    tdata = {
        "t2": appeal_json.get("fee_year_month"),
    }
    pdata = {
        "p1": appeal_json.get("p1_order_seq") or appeal_json.get("order_seq"),
        ...
        "p9": appeal_json.get("p9_reason2"),
    }
    dhead = {
        "d1": appeal_json.get("case_class"),
        "d2": appeal_json.get("case_seq"),
    }
    entry = {"dhead": dhead, "dbody": {}, "pdata_list": [pdata]}
    return tdata, [entry]
```

**應用規則：**
- 本模組的職責：官方 15 欄明細 row dict ← `AppealDraft`／`DeductionRecord`／`SubmissionCase`／facility config 的**逐欄來源對應**（RESEARCH Open Q#2 的欄位缺口：身份證字號/姓名/傷病名稱/數量/金額的 join 或誠實留空在此層決定）。
- 缺欄位時**不得憑空填**——回傳 `""` 或 None，由 render 層留白，並可累計 warning（誠實降級哲學，appeal.py `_fmt` None→「—」與 `build_necessity` None→「病歷缺席」是同一哲學的既有範例）。
- 含分頁決定純函式：`paginate(order_rows, per_page=15) -> list[list[row]]`（RESEARCH A3：每頁 15 行；**不實作**此函式者勿手寫分頁邏輯於 render 層）。

---

### `src/elc_audit_engine/generators/appeal_print/odt_fill.py`（component, transform + file-I/O）

**Analog（部分）:** `src/elc_audit_engine/generators/appeal_xml.py` 的 ET 建構＋序列化模式；**ODT content.xml 注入本身無直接 analog** → 採 RESEARCH「Code Examples」1/2 為基準。

**ET 建構與「None 不輸出」模式**（`appeal_xml.py` lines 43-52）：
```python
def _add_fields(parent: ET.Element, fields: dict[str, object]) -> None:
    """將 fields 逐鍵新增為 parent 的子元素。規則：值為 None 或空字串，跳過不輸出標籤。"""
    for key, val in fields.items():
        if val is None or val == "":
            continue
        child = ET.SubElement(parent, key)
        child.text = str(val)
```

**ET 序列化寫檔＋fail-fast 錯誤語意**（`appeal_xml.py` lines 97-118，`write_appeal_xml`）：先 `ET.tostring(root, encoding="unicode")` 預檢 → 不可編碼時 raise 自訂錯誤（含碼位、不含全文）→ `os.makedirs` → `tree.write(...)`。本 phase 的 `write_filled_odt()` 應套同一結構（預檢 zip 結構 → makedirs → 寫檔），自訂錯誤類比 `AppealXmlEncodingError`（見 Shared Patterns）。

**ODT 注入核心（RESEARCH Code Example 1，spike 實測成功，無 analog 以研究為準）**：
```python
import xml.etree.ElementTree as ET
import re

# 註冊根元素上全部命名空間（22 個前綴）
raw = open("content.xml", encoding="utf-8").read()
root_el = re.search(r"<office:document-content[^>]*>", raw).group(0)
for m in re.finditer(r'xmlns:([A-Za-z0-9_]+)="([^"]+)"', root_el):
    ET.register_namespace(m.group(1), m.group(2))
for m in re.finditer(r'xmlns="([^"]+)"', root_el):
    ET.register_namespace("", m.group(1))

tree = ET.parse("content.xml")
root = tree.getroot()
body = root.find("office:body/office:text")  # 需以 {uri}tag 完整寫法
tables = body.findall("table:table")

def set_cell_text(cell, value: str) -> None:
    p = cell.find("text:p")
    if p is None:
        p = ET.SubElement(cell, "text:p")
    for span in p.findall("text:span"):  # 清掉舊的 span 殘留
        p.remove(span)
    p.text = value                       # ET 自動轉義 < & >（安全）
```

**ODT 重打包（RESEARCH Code Example 2，mimetype 首條目不壓縮）**：
```python
import zipfile
with zipfile.ZipFile("filled.odt", "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("mimetype", b"application/vnd.oasis.opendocument.text",
               compress_type=zipfile.ZIP_STORED)   # 首條目不壓縮
    z.write("META-INF/manifest.xml", "META-INF/manifest.xml")
    z.write("meta.xml", "meta.xml"); z.write("settings.xml", "settings.xml")
    z.write("styles.xml", "styles.xml")
    z.writestr("content.xml", ET.tostring(root, encoding="UTF-8",
                                          xml_declaration=True))
```

**soffice 轉 PDF（RESEARCH Code Example 3，比照 doc_converter.py 慣例）**：
```python
import subprocess, os
profile_dir = os.path.join(output_dir, ".lo_profile")
os.makedirs(profile_dir, exist_ok=True)
result = subprocess.run(
    ["soffice", f"-env:UserInstallation={Path(profile_dir).as_uri()}",
     "--headless", "--norestore", "--nolockcheck",
     "--convert-to", "pdf", "--outdir", output_dir, filled_odt],
    capture_output=True, timeout=120)
# returncode != 0 → 拋錯；輸出檔不存在 → 拋錯（比照 convert_doc_files）
```

**應用規則（重要紀律）：**
- 全部欄位值**一律經 ET 文本節點寫入（`p.text = value`），嚴禁字串插值**（Security：ODF/XML 注入）。
- 分頁（D-06）：醫令 >15 行時複製聯組結構、`text:soft-page-break` 分隔、頁數欄遞增、合計/說明僅末頁（RESEARCH Pattern 3 為準）。
- 模板 hash 校驗（A5）：生成前比對基準模板 sha256 與入庫值，竄改即 fail-fast。

---

### `src/elc_audit_engine/generators/appeal_print/template.py`（utility, batch + file-I/O，可選）

**Analog:** `src/elc_audit_engine/rule_repository/scripts/build_docx_trees.py`

**一次性建置腳本模式**（lines 25-37）：讀 config 設定 → 執行建置 → makedirs → 寫出資產 → 列印摘要：
```python
def main() -> None:
    staging_dir = os.path.join(settings.DATA_DIR, "converted_docx")
    trees = tree_builder.build_all_trees(settings.RULE_SOURCE_DIR, staging_dir)

    os.makedirs(settings.DB_DIR, exist_ok=True)
    output_path = os.path.join(settings.DB_DIR, "docx_trees.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(trees, f, ensure_ascii=False, indent=2)
    ...
    print(f"wrote {output_path}")

if __name__ == "__main__":
    main()
```

**應用規則：** 本模組一次性把官方 `.odt`（`30396_1_...odt` 或 `30396_3_...odt`）壓縮成 `*_print_base.odt` 入庫（RESEARCH Pitfall 1：官方 ODT 直接轉 PDF＝9 頁，需縮邊距/刪空段/固定列高才達每聯一頁；壓縮參數以官方 PDF `30396_4` 為 Golden 迭代收斂）。產物為版控資產，生成後**不於每次 render 重複調參**。

---

### `config/facility.json`（config, CRUD-load）

**Analog:** `config/llama_config.json`

**既有 JSON config 資產模式**（`config/llama_config.json` 全檔）：純 JSON 物件、UTF-8、無註解，供 `settings.load_llama_config()` 讀取。本 phase 的 `facility.json` 存放院所層固定欄位（代號字碼／名稱／地址／負責醫師等，D-04），結構為單一院所物件（或院所代碼→資料的 dict）。

---

### `config/settings.py`（修改, config-loader）

**Analog:** `config/settings.py` 自身

**環境變數可覆寫路徑模式**（lines 16-19）：
```python
LLAMA_CONFIG_PATH = os.getenv(
    "LLAMA_CONFIG_PATH", os.path.join(PROJECT_ROOT, "config/llama_config.json")
)
```

**fail-fast 載入函式模式**（lines 28-39，`load_llama_config`）：
```python
def load_llama_config() -> dict:
    """讀取 llama.cpp server 連線設定（config/llama_config.json）。
    缺檔時明確拋出 FileNotFoundError（fail-fast），避免下游 phase
    在設定未就緒的情況下產生難以追查的執行期錯誤。"""
    if not os.path.isfile(LLAMA_CONFIG_PATH):
        raise FileNotFoundError(
            f"llama.cpp config file not found at expected path: {LLAMA_CONFIG_PATH}"
        )
    with open(LLAMA_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)
```

**應用規則（RESEARCH Open Q#7 定案）：** 新增 `FACILITY_CONFIG_PATH = os.getenv("FACILITY_CONFIG_PATH", os.path.join(PROJECT_ROOT, "config/facility.json"))` 與 `load_facility_config() -> dict`，比照上述兩段逐字複製改寫；可加欄位白名單/必填欄位檢查（缺必填欄 fail-fast，比照 `load_llama_config` 的哲學）。

---

### `scripts/build_appeal_print.py`（controller, batch + file-I/O）

**Analog:** `scripts/build_appeal_xml.py`（幾乎逐行可複製）

**CLI 入口模式**（lines 26-78，`main()`：argv 校驗 → 錯誤印 stderr + return 1 → 成功印出路徑 + return 0）：
```python
def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv or len(argv) > 2:
        print("用法: python scripts/build_appeal_print.py <appeal_json_path> [output_pdf_path]", file=sys.stderr)
        return 1
    input_path = argv[0]
    if not os.path.exists(input_path):
        print(f"錯誤：找不到檔案 '{input_path}'", file=sys.stderr)
        return 1
    ...
    if len(argv) == 2:
        output_path = argv[1]
    else:
        p = Path(input_path)
        try:
            safe_stem = safe_filename(p.stem, "output_stem")
        except UnsafeIdentifierError as exc:
            print(f"錯誤：不安全的檔名 '{p.stem}': {exc}", file=sys.stderr)
            return 1
        output_path = str(p.parent / f"{safe_stem}.pdf")
    ...
    print(f"已成功輸出申復清單 PDF：{output_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

**應用規則：** 讀 `appeal_{流水號}.json`（Phase 7 產物）＋ `load_facility_config()` → 呼叫 `generators` 的 render/write → 列印結果。錯誤類別逐一 catch 並以人話印 stderr（比照 build_appeal_xml.py 的 `except AppealXmlEncodingError / OSError / json.JSONDecodeError` 分層）。不觸碰 `server.py`（RESEARCH Open Q#6：CLI 先行）。

---

### `tests/test_appeal_print.py`（test）

**Analogs:** `tests/test_appeal.py`（fixture 構造＋命名測試）＋ `tests/test_appeal_xml.py`（XML 斷言＋CLI 測試）＋ `tests/test_doc_converter.py`（soffice skip）

**測試資料構造器模式**（`test_appeal.py` lines 35-58 `_record(**overrides)` 與 lines 147-154 `_draft(**kwargs)`）：以 dict 基底＋`**overrides` 組合 `DeductionRecord`／`build_appeal_draft(...)`，各測試只覆寫差異欄位。本 phase 需 `_facility(**overrides)`（dict→facility 資料）與 `_draft()`（呼叫 `build_appeal_draft`，再套用 RESEARCH 列出的缺欄位來源策略）。

**soffice 依賴 skip 模式**（`test_doc_converter.py` lines 17-20，Module-level skipif）：
```python
requires_soffice = pytest.mark.skipif(
    not soffice_is_functional(),
    reason="soffice headless conversion unavailable (real-conversion probe failed) — .doc conversion tests need it",
)
```

**CLI 端到端測試模式**（`test_appeal_xml.py` lines 118-140）：`from scripts.build_appeal_xml import main` 直接以 `main([...])` 呼叫、斷言 return code 與輸出檔存在；`lines 143-149` 斷言缺參數/缺檔 return 1。

**XML 產出斷言模式**（`test_appeal_xml.py` lines 26-48）：`ET.fromstring` 解析產出、`root.find("ddata/dbody/pdata")` 斷言節點存在與 text。

**安全測試模式**（`test_appeal.py` lines 464-478）：`pytest.raises(UnsafeIdentifierError)` + 斷言外部目錄未被寫入（檔名穿越）。

**套用於本 phase 的測試矩陣（RESEARCH Validation Architecture）：**
- `-k mapping`：欄位組裝純函式（官方欄 ← 資料來源對應、缺欄誠實降級）
- `-k odt`：content.xml 注入（不觸 soffice，`ET` 解析產出 XML 斷言院所/案件/醫令/分頁/頁數欄/合計僅末頁）
- `-k e2e`（`@requires_soffice`）：soffice 轉 PDF → `pypdf` 斷言頁數＝3×N、關鍵文本（代號字碼/院所名稱/案件分類/流水號/醫令代碼）
- `-k copies`：三聯版式差異（第二聯含核定欄、第一/三聯無；系統不填）
- `-k security`：`<script>`/`&` 不破壞 ODT、檔名穿越被拒
- `-k config`：facility.json 缺檔 fail-fast、env 覆寫路徑

---

### `tests/conftest.py`（修改, test-fixture）

**Analog:** `tests/conftest.py` 自身＋`tests/test_doc_converter.py`

**既有 fixture 模式**（`conftest.py` lines 20-28，`tmp_rule_db_path`：以 `tmp_path` 回傳字串路徑，避免寫入正式 data/db）：
```python
@pytest.fixture
def tmp_rule_db_path(tmp_path) -> str:
    """回傳一個尚未建立的暫存 SQLite DB 路徑（str），供規則庫測試使用。..."""
    return str(tmp_path / "test_rules.sqlite3")
```

**需新增的 fixture（RESEARCH Wave 0）：**
- `requires_soffice`（module-level skipif，直接搬 `test_doc_converter.py` lines 17-20 的定義；`soffice_is_functional()` import 自 `elc_audit_engine.rule_repository.docx_tree.doc_converter`）
- `facility_config`：以 `monkeypatch` 覆寫 `settings.FACILITY_CONFIG_PATH` 指向 tmp_path 的測試用 facility.json（比照 `test_config.py` lines 25-29 的 monkeypatch 缺檔測試）
- `sample_appeal_draft()`：構造 `AppealDraft` 的共用 factory（比照 `test_appeal.py` `_draft()`）

---

### `officialdocument/電子申復文件格式/*_print_base.odt`（data, file-I/O）

**Analog:** `officialdocument/電子申復文件格式/30396_*.odt`

**版控資產模式：** 官方 ODT 範本現已 git-tracked（RESEARCH A5 VERIFIED），本 phase 的壓縮基準模板（`*_print_base.odt`）同樣**入 git**——它是 layout 參數固化後的資產，非每次生成時動態產出。生成前 sha256 校驗（A5）確保未被竄改。

## Shared Patterns

### 輸出檔名安全（P1-3）
**Source:** `src/elc_audit_engine/safe_paths.py`（lines 32-58）+ `generators/appeal.py` `write_appeal`（lines 540-543）
**Apply to:** `appeal_print/__init__.py`（`write_appeal_print`）、`scripts/build_appeal_print.py`
```python
stem = safe_filename(file_stem or (case_seq or "unknown"), "file_stem/case_seq")
os.makedirs(output_dir, exist_ok=True)
md_path = os.path.join(output_dir, f"申復草稿_{stem}.md")
```
「校驗後拒絕」而非「清洗取代」——非法識別碼一律 `UnsafeIdentifierError`，檔案不得寫出 output_dir。

### PHI 安全錯誤訊息
**Source:** `src/elc_audit_engine/generators/appeal_xml.py`（lines 25-30、106-111）
**Apply to:** `appeal_print/odt_fill.py`（自訂錯誤類比 `AppealXmlEncodingError`）、`appeal_print/field_mapping.py`、`scripts/build_appeal_print.py`
```python
class AppealXmlEncodingError(ValueError):
    """Big5 無法編碼時拋出此例外（包含欄位脈絡與字元碼位，不包含 PHI 全文）。"""
    def __init__(self, message: str, field_name: str | None = None):
        super().__init__(message)
        self.field_name = field_name
```
錯誤訊息只記欄位名/失敗階段/碼位，**不記欄位值全文**（ASVS V9）。

### 一案一檔案輸出慣例
**Source:** `generators/appeal.py` `write_appeal`（C7 命名）、`generators/reinforcement_report.py` `write_report`（Phase 6）
**Apply to:** `appeal_print/__init__.py`
一個案件一個 PDF（`申復清單_{stem}.pdf`），不設計批次輸出格式；`file_stem` 參數供同案多筆醫令避免覆寫（Security 威脅「輸出檔覆寫」的既有解）。

### 誠實降級哲學（貫穿全專案）
**Source:** `generators/appeal.py`（`_fmt` None→「—」lines 106-110、`build_necessity` None→「病歷缺席」lines 142-143、`_build_rule_basis` 查無規則→提示 lines 169-175）
**Apply to:** `appeal_print/field_mapping.py`（身份證字號/姓名/傷病名稱/數量/金額等 AppealDraft 缺欄位：join 不到就留空＋警告，**不猜測補全**；遮罩 id_number 照印或留空，不得重建完整字號）

### Config fail-fast
**Source:** `config/settings.py` `load_llama_config`（lines 28-39）+ `tests/test_config.py`（lines 25-29 monkeypatch 缺檔測試）
**Apply to:** `config/settings.py` `load_facility_config`、`tests/test_appeal_print.py -k config`
缺檔/缺必填欄位立刻 `FileNotFoundError`/`ValueError`，不在 render 階段以空值靜默產生看似正常的 PDF。

### gitignore 紀律（P0-3）
**Source:** `.gitignore` lines 29-31（`data/output/*` + `!data/output/.gitkeep`）
**Apply to:** 所有輸出（PDF/暫存 filled .odt）一律寫入 `data/output/`；測試輸出走 pytest `tmp_path`。**基準模板 `*_print_base.odt` 是唯一例外**——入 git（`officialdocument/` 未 ignore）。

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `src/elc_audit_engine/generators/appeal_print/odt_fill.py`（content.xml 注入＋ODF zip 重打包部分） | component | transform + file-I/O | 全 codebase 無 ODT/ODF 容器操作先例（docx 走 python-docx、申復 XML 是自建 ET 樹非模板注入）——以 RESEARCH「Code Examples」1/2（spike 實測）為準：22 命名空間註冊、`set_cell_text` ET 文本節點、mimetype 首條目 `ZIP_STORED` |
| `src/elc_audit_engine/generators/appeal_print/template.py`（ODT 版面壓縮部分） | utility | batch | 無既有版面壓縮 analog（docx 轉換只有格式轉換、無 layout 收斂）——以 RESEARCH Pitfall 1 與 Open Q#3 的實驗參數（固定列高/字號/邊距）為起點迭代 |

## Metadata

**Analog search scope:** `src/elc_audit_engine/`（generators、safe_paths、rule_repository/docx_tree）、`config/`、`scripts/`、`tests/`、`.gitignore`、`pyproject.toml`、`officialdocument/電子申復文件格式/`
**Files scanned:** 15（appeal.py、appeal_xml.py、reinforcement_report.py、generators/__init__.py、doc_converter.py、build_docx_trees.py、safe_paths.py、settings.py、llama_config.json、build_appeal_xml.py、conftest.py、test_appeal.py、test_appeal_xml.py、test_doc_converter.py、test_config.py）
**Pattern extraction date:** 2026-08-08
