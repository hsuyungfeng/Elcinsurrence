# Phase 13 Research: 核減明細原格式列印 (Deduction Detail Original Format Print)

**Phase Goal:** 依 `DeductionRecord` 18 欄資產（或 `DeductionParseResult` / `CaseStore` 核減案件）還原健保署「門診醫療給付抽查核減明細表」（RCPI2012R01 逐案清單 / RCPI2001R01 統計計算式）之實體紙本列印格式（PDF），與 Phase 11 (`appeal_print.py`) 之「聲復清單」雙軸並存。
**Requirements Covered:** REQ-deduction-print

---

## 1. Executive Summary & Core Answer

### What do I need to know to PLAN this phase well?

1. **雙軸並存語義 (Dual-Axis Parallelism)**:
   - **Phase 11 (`appeal_print.py`)** 處理的是**診所送交健保署的「申復清單」**（3 頁官方三聯單，診所爭取補付點數）。
   - **Phase 13 (`deduction_print.py`)** 處理的是**健保署核下之「核減明細表」**（RCPI2012R01 逐案清單／RCPI2001R01 統計計算表），供診所實體對帳、紙本留底與院內審查。
2. **核心標的版面 (Target Document)**:
   - 健保局官方核減明細包含多種子表，最核心且診所對帳必備的是 **RCPI2012R01 逐案核減明細表 (Case-by-Case Deduction Detail Table)**，表頭包含院所基本資訊與抽審/核減點數統計，主體為多列逐案/逐醫令核減明細網格。
3. **技術架構沿用 Phase 11 (Pattern Reuse)**:
   - 沿用 Phase 11 驗證成功的 `soffice --headless` + `.odt` 模板 XML 注入（`xml.etree.ElementTree` + stdlib `zipfile`）工具鏈。
   - 不引入任何新的重量級 Python PDF/繪圖套件（如 `weasyprint` 或 `reportlab`），保持 zero extra binary dependencies 與個資離線安全 (D2)。
4. **動態列擴充 (Dynamic Row Expansion in ODF XML)**:
   - 申復清單 (Phase 11) 為固定 3 聯／每頁 15 列的靜態單頁版面；而核減明細 (Phase 13) 為**動態列數**（一案多筆核減醫令或一次列印整批核減案）。
   - 需在 `odt_fill.py` 實現 ODT `table-row` 樣板複製與動態節點注入，並適當分頁。
5. **誠實降級與警示 (Honest Degradation)**:
   - 當欄位資料缺失（例如單純匯入 CSV 檔缺少申報 XML 補強之 `patient_name` 病患姓名或 `order_name` 醫令名稱）時，誠實列印印出（留空或印出遮罩字號）並回傳 warnings 清單，不阻斷 PDF 生成。

---

## 2. Background & Official Paper Form Analysis

參考 `.planning/intel/paper-scan-samples.md` 之真實紙本掃描樣本分析：

### 官方核減明細三種樣式
- **RCPI2012R01 / RCP12013R01 門診醫療給付抽查核減明細表 (逐案清單)**：
  - 表頭：機構名稱、醫事機構代碼、費用年月、抽審件數、核減件數、總核減點數。
  - 主表欄位：
    1. `序號` (Row Seq)
    2. `案件分類/病歷號` (Case Class `case_class` / Chart No)
    3. `就醫日期` (`visit_date` YYYYMMDD)
    4. `身分證號/出生年月日` (`id_number` 遮罩 4 碼 / `birth_date` YYYYMMDD)
    5. `姓名` (`patient_name` 來自 join 或 `id_number`)
    6. `醫令序/代碼` (`order_seq` / `order_code`)
    7. `醫令名稱` (`order_name`)
    8. `申報點數/數量` (`claimed_points` / `total_qty`)
    9. `不予核銷金額/核減點數` (`non_reimbursed_amount` / `split_amount`)
    10. `核減代碼及說明` (`appeal_item_code` - `appeal_item_desc`)
    11. `追扣原因` (`deduction_reason` 欄 16)
    12. `院所說明` (`institution_note` 欄 18)
- **RCPI2001R01 回推核減點數計算表 (統計計算式版型)**：
  - 含有母體點數、抽樣點數、核減率、回推倍數與最終回推核減點數之計算公式卡片。可作為頁首或表頭摘要區。
- **RCPI2021R01 門診醫療給付費用審查結果總表 (機構總表)**：
  - 機構級別統計摘要。

Phase 13 之 Core Deliverable 鎖定為 **RCPI2012R01 逐案核減明細表（含頁首 RCPI2001R01/2021R01 統計摘要卡）**。

---

## 3. Data Source & Model Mapping

### 18 欄 `DeductionRecord` 來源對應表 (`src/elc_audit_engine/parsers/models.py`)

| 核減明細表欄位 | 資料來源 (`DeductionRecord` / `facility` / `submission`) | 缺欄降級與 Warning 處理 |
| --- | --- | --- |
| 醫事機構代碼 | `facility["institution_code"]` or `DeductionRecord.institution_code` | 缺席 → 帶出 warning `缺機構代碼` |
| 醫療院所名稱 | `facility["facility_name"]` | 缺席 → 帶出 warning `缺院所名稱` |
| 費用年月 | `DeductionRecord.fee_year_month` | 格式 YYYYMM |
| 申請申報日期 | `DeductionRecord.submit_date` | 格式 YYYYMMDD |
| 案件分類 / 流水號 | `DeductionRecord.case_class` / `case_seq` | 照印 |
| 就醫日期 | `DeductionRecord.visit_date` | 格式 YYYYMMDD |
| 出生日期 | `DeductionRecord.birth_date` | 格式 YYYYMMDD (PHI) |
| 身分證號 | `DeductionRecord.id_number` | 健保署已遮罩後 4 碼 (PHI)，照印遮罩值 |
| 姓名 | `submission.patient_name` (d49) | 若未 join 申報 XML → 留空 + warning `缺病患姓名` |
| 醫令序 / 醫令代碼 | `DeductionRecord.order_seq` / `order_code` | 照印 |
| 不予核銷金額 (核減點數) | `DeductionRecord.non_reimbursed_amount` | 數字照印 (int) |
| 核減代碼及說明 | `DeductionRecord.appeal_item_code` - `appeal_item_desc` | `欄17` 拆分結果 |
| 追扣原因 | `DeductionRecord.deduction_reason` | `欄16` 自由中文 |
| 院所說明 | `DeductionRecord.institution_note` | `欄18` 自由中文 |

---

## 4. Architecture & Technical Blueprint

### 子套件結構 (`src/elc_audit_engine/generators/deduction_print/`)

```text
src/elc_audit_engine/generators/deduction_print/
├── __init__.py               # render_deduction_print, write_deduction_print 公開介面
├── field_mapping.py          # 純函式：組裝表頭、組裝動態列、記錄 warnings
├── odt_fill.py               # ElementTree 解析 content.xml, table-row 樣板複製與寫入, zip 重打包
└── template.py               # 基準模板加載與 SHA256 完整性校驗
```

### ODT 樣板與動態擴充策略 (Template & Dynamic Row Pattern)

1. **基準模板檔案**:
   - `officialdocument/電子申復文件格式/RCPI2012R01_核減明細表_print_base.odt`
   - 配套 sidecar: `RCPI2012R01_核減明細表_print_base.sha256`
   - 入 git 版控，與 Phase 11 之 `30396_*_print_base.odt` 同等處置。
2. **Dynamic XML Row Duplication (`odt_fill.py`)**:
   - 在 `content.xml` 中，定位主資料表 (Table)。
   - 提取prototype `table-row` 節點 (`copy.deepcopy(row_prototype)`)。
   - 對每筆 `DeductionRecord` 生成一列 `table-row` 並以 `set_cell_text(cell, text)` 安全寫入。
   - 保持 XML 結構合法性與 ODF Table Style 完整。

---

## 5. Security & Privacy Discipline

1. **T-13-01 XML 安全轉義**:
   - 所有寫入 XML 單元格之文本必須通過 `p.text = val` 寫入，利用 `ElementTree` 自動轉義 `<, >, &, "`，嚴禁字串插值 (String Interpolation)。
2. **T-13-02 PHI 遮罩防護**:
   - `id_number` 恆列印遮罩值 (如 `A123****`)，嚴禁嘗試還原完整字號。
3. **T-13-03 路徑穿越防護**:
   - 所有輸出檔名 stem 必須經由 `safe_filename()` 校驗 (P1-3 / T-11-04)。
4. **T-13-04 暫存與產物隔離**:
   - 渲染過程中間檔產出於 `tempfile.TemporaryDirectory()`，正式 PDF 寫入 `data/output/`（已 gitignore）。

---

## 6. Entry Points (CLI & API)

1. **CLI 指令 (`scripts/build_deduction_print.py`)**:
   - 輸入：`--csv <path>` 或 `--case-id <id>`
   - 輸出：`data/output/核減明細_{stem}.pdf`，並於 stdout 印出警示清單。
2. **Flask API 端點 (`server.py`)**:
   - `POST /api/deduction/print` 或 `GET /api/cases/{case_id}/deduction-print`
   - 回傳包含 PDF 下載路徑與 `warnings` 之 JSON。

---

## 7. Plan & Wave Breakdown

建議 Phase 13 劃分為 **3 個 Phase Plans**：

- **Plan 13-01 (Wave 1: Template & Field Mapping)**:
  - 製作 official ODT 基準模板 `RCPI2012R01_核減明細表_print_base.odt` + `.sha256`。
  - 實作 `field_mapping.py` (`build_deduction_header`, `build_deduction_rows`) 與單元測試。
- **Plan 13-02 (Wave 2: ODT Filling & PDF Rendering Engine)**:
  - 實作 `odt_fill.py`（支持 ElementTree 複製 `table-row` 節點與寫入）。
  - 實作 `template.py`（sha256 驗證）與 `__init__.py` (`render_deduction_print`, `write_deduction_print`)。
  - 實作 `soffice` PDF 轉檔整合測試與 `pypdf` 頁數/文字層斷言 (`test_deduction_print.py`)。
- **Plan 13-03 (Wave 3: CLI & API Servicing)**:
  - 實作 `scripts/build_deduction_print.py` CLI 工具。
  - 於 `server.py` 接線 `POST /api/deduction/print` 端點與 Audit Log。
  - 補齊 E2E 整合測試。
