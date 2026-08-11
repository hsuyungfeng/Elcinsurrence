# Phase 13: 核減明細原格式列印 - Pattern Map

**Mapped:** 2026-08-11
**Files analyzed:** 10 (8 created / 2 modified)
**Analogs found:** 10 / 10

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/elc_audit_engine/generators/deduction_print/__init__.py` (新增) | component (render/write 輸出通道) | transform + file-I/O | `src/elc_audit_engine/generators/appeal_print/__init__.py` (`render_appeal_print` / `write_appeal_print`) | exact |
| `src/elc_audit_engine/generators/deduction_print/field_mapping.py` (新增) | component (欄位映射與降級) | transform | `src/elc_audit_engine/generators/appeal_print/field_mapping.py` (`build_rows` / `build_header`) | exact |
| `src/elc_audit_engine/generators/deduction_print/odt_fill.py` (新增) | component (ET 動態列注入＋zip 重打包) | transform + file-I/O | `src/elc_audit_engine/generators/appeal_print/odt_fill.py` (`fill_template` / `set_cell_text`) | role-match (靜態列 15 列 vs 動態列 `table-row` 複製) |
| `src/elc_audit_engine/generators/deduction_print/template.py` (新增) | component/utility (基準模板載入與 sha256 驗證) | transform + file-I/O | `src/elc_audit_engine/generators/appeal_print/template.py` (`verify_template_hash` / `_load_expected_sha256`) | exact |
| `officialdocument/電子申復文件格式/RCPI2012R01_核減明細表_print_base.odt` & `.sha256` (新增) | data (版控資產) | file-I/O | `officialdocument/電子申復文件格式/30396_*_print_base.odt` & `.sha256` | exact |
| `scripts/build_deduction_print.py` (新增) | controller (CLI 入口) | batch + file-I/O | `scripts/build_appeal_print.py` | exact |
| `tests/test_deduction_print.py` (新增) | test | N/A | `tests/test_appeal_print.py` | exact |
| `src/elc_audit_engine/generators/__init__.py` (修改) | component (包導出) | transform | `src/elc_audit_engine/generators/__init__.py` 自身 | exact |
| `server.py` (修改) | controller (API 端點) | request/response + file-I/O | `server.py` (`POST /api/cases/{case_id}/appeal-print` / `write_appeal_print`) | exact |
| `tests/conftest.py` (修改) | test (fixtures) | N/A | `tests/conftest.py` 自身 (`facility_config`, `requires_soffice`) | exact |

---

## Pattern Assignments

### 1. `src/elc_audit_engine/generators/deduction_print/__init__.py` (component, transform + file-I/O)

**Analog:** `src/elc_audit_engine/generators/appeal_print/__init__.py`

**Existing Pattern Excerpt (`appeal_print/__init__.py` lines 59-198):**
```python
def render_appeal_print(
    payload: dict,
    facility: dict,
    *,
    template_odt_path: str,
    submission: dict | None = None,
) -> tuple[bytes, list[str]]:
    header = build_header(facility, payload, submission)
    rows, warnings = build_rows(payload, facility, submission=submission)
    pages = paginate(rows)

    with tempfile.TemporaryDirectory(prefix="elc_appeal_print_") as tmp:
        filled_path = os.path.join(tmp, "filled.odt")
        fill_template(template_odt_path, header, pages, filled_path)
        with open(filled_path, "rb") as f:
            return f.read(), warnings

def write_appeal_print(
    output_dir: str | os.PathLike[str],
    file_stem: str,
    payload: dict,
    facility: dict,
    *,
    template_odt_path: str,
    submission: dict | None = None,
    soffice_timeout: int = 120,
) -> tuple[str, list[str]]:
    stem = safe_filename(file_stem, "file_stem")
    os.makedirs(output_dir, exist_ok=True)
    pdf_path = os.path.join(os.fspath(output_dir), f"申復清單_{stem}.pdf")

    verify_template_hash(template_odt_path, _load_expected_sha256(template_odt_path))

    filled_odt_bytes, warnings = render_appeal_print(
        payload, facility, template_odt_path=template_odt_path, submission=submission
    )

    with tempfile.TemporaryDirectory(prefix="elc_appeal_convert_") as tmp:
        filled_path = os.path.join(tmp, f"申復清單_{stem}.odt")
        with open(filled_path, "wb") as f:
            f.write(filled_odt_bytes)

        profile_dir = os.path.join(tmp, "lo_profile")
        os.makedirs(profile_dir, exist_ok=True)
        result = subprocess.run(
            [
                "soffice",
                f"-env:UserInstallation={Path(profile_dir).as_uri()}",
                "--headless",
                "--norestore",
                "--nolockcheck",
                "--convert-to", "pdf",
                "--outdir", os.fspath(output_dir),
                filled_path,
            ],
            capture_output=True,
            timeout=soffice_timeout,
        )
    return pdf_path, warnings
```

**Adaptation for Phase 13:**
- Public entry points: `render_deduction_print(...)` and `write_deduction_print(...)`.
- Accepts `records: list[DeductionRecord | dict]`, `facility: dict`, `submission: dict | None`.
- PDF output filename pattern: `核減明細_{stem}.pdf`.
- Temporary directory usage (`tempfile.TemporaryDirectory(prefix="elc_deduction_print_")`) for zero disk pollution.
- `soffice --headless` isolated execution with `-env:UserInstallation`.

---

### 2. `src/elc_audit_engine/generators/deduction_print/field_mapping.py` (component, transform)

**Analog:** `src/elc_audit_engine/generators/appeal_print/field_mapping.py`

**Existing Pattern Excerpt (`appeal_print/field_mapping.py` lines 70-96):**
```python
def _str_or_empty(value: Any) -> str:
    if value is None or value == "":
        return ""
    return str(value)

def _fmt_roc_date_iso(iso: str) -> str:
    parts = iso.split("-")
    if len(parts) != 3:
        return iso
    year, month, day = parts
    if not (year.isdigit() and month.isdigit() and day.isdigit()):
        return iso
    return f"{int(year) - 1911}年{int(month)}月{int(day)}日"
```

**Adaptation for Phase 13:**
- Exports `build_deduction_header(...)` and `build_deduction_rows(...)`.
- Maps 18 fields of `DeductionRecord` to `RCPI2012R01` print table columns:
  - Header: 機構代碼, 機構名稱, 費用年月 (YYYYMM → 民國年月), 申請申報日期, 抽審件數, 核減件數, 總核減點數.
  - Rows (12 columns per row): 序號 (`seq`), 案件分類/病歷號 (`case_class` / `chart_no`), 就醫日期 (`visit_date`), 身分證號/出生日期 (`id_number` 遮罩 / `birth_date`), 姓名 (`patient_name` - join from submission or missing), 醫令序/代碼 (`order_seq` / `order_code`), 醫令名稱 (`order_name`), 申報點數/數量 (`claimed_points` / `total_qty`), 不予核銷金額/核減點數 (`non_reimbursed_amount`), 核減代碼及說明 (`appeal_item_code` - `appeal_item_desc`), 追扣原因 (`deduction_reason`), 院所說明 (`institution_note`).
- Honest degradation: missing `patient_name` or `order_name` fills `""` and appends to `warnings: list[str]`.
- PHI Masking Discipline: `id_number` always prints masked value (`A123****`), never attempt unmasking.

---

### 3. `src/elc_audit_engine/generators/deduction_print/odt_fill.py` (component, transform + file-I/O)

**Analog:** `src/elc_audit_engine/generators/appeal_print/odt_fill.py`

**Existing Pattern Excerpt (`appeal_print/odt_fill.py` lines 120-147, 320-345):**
```python
def set_cell_text(cell: ET.Element, value: str) -> None:
    p = cell.find(_P)
    if p is None:
        p = ET.SubElement(cell, _P)
    for child in list(p):
        p.remove(child)
    p.text = value

def _register_namespaces(root_el_text: str) -> None:
    for m in re.finditer(r'xmlns(?::([A-Za-z0-9_]+))?="([^"]+)"', root_el_text):
        ET.register_namespace(m.group(1) or "", m.group(2))

# zip repack pattern:
with zipfile.ZipFile(output_odt_path, "w", zipfile.ZIP_DEFLATED) as zout:
    zout.writestr("mimetype", _MIMETYPE, compress_type=zipfile.ZIP_STORED)
    for info in infos:
        if info.filename == "mimetype":
            continue
        if info.filename == "content.xml":
            zout.writestr("content.xml", serialized)
        else:
            zout.writestr(info.filename, zin.read(info.filename))
```

**Adaptation for Phase 13 (Dynamic Row Duplication):**
- Unlike Phase 11's static 15-row table, Phase 13 requires **dynamic row expansion**:
  - Locate prototype row in ODT table (`table-row`).
  - Deepcopy prototype row (`copy.deepcopy(row_prototype)`) for each record row.
  - Write text nodes via `set_cell_text(cell, val)` (XML safe escaping via `p.text = val`).
  - Repack ODT container using standard `zipfile` pattern (`mimetype` first with `ZIP_STORED`).

---

### 4. `src/elc_audit_engine/generators/deduction_print/template.py` (component/utility, transform + file-I/O)

**Analog:** `src/elc_audit_engine/generators/appeal_print/template.py`

**Existing Pattern Excerpt (`appeal_print/template.py` lines 98-120):**
```python
def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
```

**Adaptation for Phase 13:**
- Base template: `officialdocument/電子申復文件格式/RCPI2012R01_核減明細表_print_base.odt`.
- Sidecar checksum: `RCPI2012R01_核減明細表_print_base.sha256`.
- Provides `verify_template_hash(template_path, expected_sha256)` and `_load_expected_sha256(template_path)`.

---

### 5. `scripts/build_deduction_print.py` (controller, batch + file-I/O)

**Analog:** `scripts/build_appeal_print.py`

**Existing Pattern Excerpt (`scripts/build_appeal_print.py` lines 30-48, 160-185):**
```python
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from elc_audit_engine.generators import write_appeal_print
from elc_audit_engine.safe_paths import safe_filename

def main(argv: list[str] | None = None) -> int:
    ...
    pdf_path, warnings = write_deduction_print(
        output_dir=output_dir,
        file_stem=file_stem,
        records=records,
        facility=facility,
        template_odt_path=PRINT_BASE_ODT,
    )
    print(f"成功生成核減明細 PDF：{pdf_path}")
    for w in warnings:
        print(f"警告：{w}", file=sys.stderr)
    return 0
```

**Adaptation for Phase 13:**
- Supports CLI flags `--csv <path>` or `--case-id <id>` or positional args `<deduction_csv_or_json> [output_pdf_path]`.
- Invokes `write_deduction_print(...)`.
- Outputs path on success; prints warnings to stderr/stdout.

---

### 6. `server.py` (controller, request/response + file-I/O)

**Analog:** `server.py` (Phase 11 appeal print endpoint)

**Adaptation for Phase 13:**
- Adds endpoint `POST /api/deduction/print` (or `GET /api/cases/{case_id}/deduction-print`).
- Validates request payload, fetches deduction records and facility info, calls `write_deduction_print`.
- Emits audit log entry.
- Returns JSON `{ "pdf_url": "/output/...", "warnings": [...] }`.

---

### 7. `tests/test_deduction_print.py` & `tests/conftest.py` (test)

**Analog:** `tests/test_appeal_print.py` and `tests/conftest.py`

**Adaptation for Phase 13:**
- Test matrix:
  - `-k mapping`: Field conversion pure function tests (`build_deduction_header`, `build_deduction_rows`, warnings for missing fields).
  - `-k odt`: ElementTree XML row injection and ODT packaging tests.
  - `-k e2e`: Full `write_deduction_print` call converting ODT to PDF via `soffice --headless` (guarded by `requires_soffice`), verifying page count and text layer with `pypdf`.
  - `-k security`: Path traversal rejection (`safe_filename`), XML escaping verification (`<>&`), PHI mask checking.
