# Phase 12 Research: 影像佐證上傳與關聯驅動

## Executive Summary

Phase 12 的核心目標是補齊診所「佐證影像上傳」與「申復 XML / JSON 中 `p7` (申復檔案連結) 旗標動態驅動」的缺口。診所進行健保申復時，除申復文字外，常需附帶超音波 (sono)、X 光 (X-ray) 或術式處置照片。健保申復 XML 規格中，`p7` 欄位為 `Y`/`N` 旗標，代表是否透過 PACS/佐證通道另外提供影像檔案。目前系統的 `generators/appeal.py` 中的 `has_attachment` 仍為手動傳入之布林旗標；Phase 12 將建立專屬的佐證附件儲存區與關聯管理模組，使 `has_attachment` / `p7` 轉由「儲存區中是否存在實體佐證檔案」真實驅動。

**重要範圍邊界 (Scope Clarification)**：
依據 `.planning/intel/paper-scan-samples.md` 盤點與使用者裁示：佐證影像是給健保審查醫師閱讀的視覺證據，**不需要進行 OCR 或結構化欄位萃取**。工程複雜度集中在：檔案上傳/安全校驗/格式驗證/案件醫令流水號關聯/實體檔案驅動 `p7` 旗標/REST API與CLI介面。

---

## 1. Requirement & Scope Analysis (REQ-attachment-upload)

### 1.1 核心需求項目
1. **影像佐證接收與格式支援**：
   - 支援 PNG, JPEG (.jpg, .jpeg), HEIC (.heic, .heif), PDF 格式。
   - 上傳時需校驗檔案完整性與真實格式（防護偽裝副檔名與損毀檔案）。
2. **路徑安全與檔名關聯**：
   - 必須經由 `elc_audit_engine.safe_paths.safe_filename()` 校驗 `case_seq` (案件流水號) 與 `order_seq` (醫令流水號)。
   - 防範路徑穿越攻擊 (`P1-3` 防線)，嚴禁使用未校驗的外部檔名建立磁碟目錄。
3. **實體檔案真實驅動 `has_attachment` / `p7`**：
   - `generators/appeal.py` 的 `build_appeal_draft` 與 `render_appeal_json()` 中的 `p7_attachment` 欄位 (`Y`/`N`)，以及 `generators/appeal_xml.py` 產出的 XML `p7` 欄位，改由「是否存在對應案件與醫令之實體佐證檔案」真實決定。
   - 誠實降級：若無上傳佐證檔案，預設降級為 `N`，不捏造上傳狀態。
4. **API 與 CLI 雙介面**：
   - Flask API 端點：`POST /api/appeal/attachments/upload` 接收上傳檔；`GET /api/appeal/attachments/<case_seq>` 查詢附件。
   - CLI 輔助工具或模組 API：提供 command-line 或指令腳本直接匯入附件。

---

## 2. Current Architecture & Codebase Baseline

### 2.1 現有 `has_attachment` 流向盤點
- **`src/elc_audit_engine/generators/appeal.py`**:
  - `AppealDraft`: dataclass 包含 `has_attachment: bool = False`。
  - `build_appeal_draft()`: 入參 `has_attachment: bool = False`。
  - `render_appeal_json()`: 輸出 `"p7_attachment": "Y" if draft.has_attachment else "N"`。
- **`src/elc_audit_engine/generators/appeal_xml.py`**:
  - `draft_json_to_appeal_xml_fields()`: 映射 `"p7": appeal_json.get("p7_attachment")`。
- **`server.py`**:
  - `/api/appeal/generate`: 目前接收 `has_attachment=bool(data.get('has_attachment', False))`，預設為 `False`。
- **`src/elc_audit_engine/safe_paths.py`**:
  - `safe_filename(value, field_name)`: 已完成的白名單校驗器（支援 CJK、英數、`-`、`_`），非法字元拋出 `UnsafeIdentifierError`。

### 2.2 設定與依賴庫
- **`config/settings.py`**:
  - 目前定義了 `DATA_DIR`, `RECORDS_DIR`, `CASES_DB_PATH` 等。
  - 尚缺 `ATTACHMENTS_DIR` 設定（建議預設為 `os.path.join(DATA_DIR, "attachments")`）。
- **`pyproject.toml`**:
  - 已包含 `pillow-heif>=1.5.0`（支援 HEIC 影像讀取與轉換）。
  - `pypdf>=6.15.0` 已在 dev group 中。

---

## 3. Detailed Architecture & Design Proposal

### 3.1 儲存目錄結構與命名規範
定義根目錄 `ATTACHMENTS_DIR`（可透過環境變數 `ATTACHMENTS_DIR` 覆寫）：
```text
data/attachments/
└── <case_seq>/
    ├── meta.json                     # 附件詮釋資料 (選填/單一真實來源)
    ├── <order_seq>_<timestamp>_<uuid>.png
    ├── <order_seq>_<timestamp>_<uuid>.heic
    └── <order_seq>_<timestamp>_<uuid>.pdf
```
- **關聯維度**：
  - 案件維度：`case_seq` (必須)。
  - 醫令維度：`order_seq` (選填，若針對特定刪減醫令) 或 `order_code`。

### 3.2 新增 Attachment Store 模組 (`src/elc_audit_engine/attachment_store.py`)
建議提供以下強型別介面：
1. `save_attachment(case_seq: str, file_bytes: bytes, filename: str, order_seq: str | None = None, order_code: str | None = None) -> AttachmentRecord`
   - 使用 `safe_filename(case_seq)` 與 `safe_filename(order_seq)` 進行嚴格安全校驗。
   - 檢查副檔名與魔法位元 (Magic Bytes)：
     - PNG: `\x89PNG\r\n\x1a\n`
     - JPEG: `\xff\xd8\xff`
     - PDF: `%PDF-`
     - HEIC: 使用 `pillow_heif` / Pillow 嘗試開檔驗證。
   - 若檔案不符格式或損毀，拋出 `InvalidAttachmentError`。
   - 上傳檔案大小上限：單檔 10MB (`_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024`)。
2. `has_attachment(case_seq: str, order_seq: str | None = None) -> bool`
   - 檢查 `ATTACHMENTS_DIR/<case_seq>/` 目錄下是否存在有效附件。
   - 若指定 `order_seq`，先匹配該醫令；若未指定或無匹配，再檢查案件級附件。
3. `list_attachments(case_seq: str, order_seq: str | None = None) -> list[AttachmentRecord]`
4. `delete_attachment(case_seq: str, attachment_id: str) -> bool`

### 3.3 驅動 `has_attachment` / `p7` 邏輯改寫
1. **`generators/appeal.py`**:
   - `build_appeal_draft` 入參 `has_attachment: bool | None = None`。
   - 當 `has_attachment is None` 時，調用 `attachment_store.has_attachment(record.case_seq, record.order_seq)`。
   - 若未提供 `attachment_store` 或實體檔案不存在，誠實落為 `False` (`p7="N"`)。
2. **`server.py` (`/api/appeal/generate`)**:
   - 端點調用 `build_appeal_draft()` 時，自動查詢 `attachment_store.has_attachment(case_seq, order_seq)`，並傳入 `draft` 生成流程。
   - 前端無需手動勾選 `has_attachment`，完全由實體檔案上傳狀態決定！

### 3.4 Web API 端點設計 (`server.py`)
1. **`POST /api/appeal/attachments/upload`**:
   - `multipart/form-data`: `file`, `case_seq` (必填), `order_seq` (選填), `order_code` (選填)。
   - 審計記錄：留存上傳操作日誌（不含圖片內容與敏感 PHI 檔名）。
   - 回應：`{ "status": "success", "attachment": { "id": "...", "case_seq": "201", "order_seq": "1", "filename": "...", "created_at": "..." } }`
2. **`GET /api/appeal/attachments/<case_seq>`**:
   - 回應該案件已上傳的所有佐證附件清單。
3. **`DELETE /api/appeal/attachments/<case_seq>/<attachment_id>`**:
   - 刪除指定的佐證附件檔案，同步更新 `p7` 狀態。

---

## 4. Phase 14 Forward Compatibility & Integration

Phase 14 的目標為「審核軌跡＋病歷摘要＋申復理由＋影像佐證包列印 (PDF)」。
Phase 12 在設計附件儲存時，需考慮 Phase 14 的讀取與列印需求：
1. **圖檔轉換支援**：
   - Phase 14 將附件圖檔合成至 PDF 時，需將 HEIC 轉為 PNG/JPEG。
   - `attachment_store.py` 應提供 `get_attachment_image_as_png(case_seq, attachment_id)` 輔助函式，利用 `pillow_heif` 自動將 HEIC 解碼並轉為標準 PIL Image / PNG 位元流。
2. **PDF 頁面拆分**：
   - 若診所上傳的佐證本身即為多頁 PDF，Phase 14 可直接利用 `pdftoppm` 或 `pypdf` 將頁面嵌入佐證包。

---

## 5. Potential Risks & Mitigation Strategies

| 風險項目 | 潛在影響 | 因應與緩解策略 |
|---|---|---|
| **路徑穿越漏洞** | 惡意 `case_seq` 或檔名存取系統任意檔案 | 全路徑段強制通過 `safe_filename()` 白名單校驗 |
| **偽造/損毀檔** | 傳入非影像或損毀檔導致後續列印崩潰 | 上傳時透過 Magic Bytes + Pillow/pypdf 實測開檔驗證 |
| **HEIC 解碼相容性** | 部分 Linux 系統缺 C 擴充 | 使用 `pillow-heif` 純 Python/wheels 繫結，並於單元測試覆蓋 HEIC 驗證 |
| **孤立檔案 (Orphans)** | 案件刪除或重新匯入後舊附件殘留 | 提供案件附件清理 / 覆寫機制，或依據 `case_seq` 管理生命週期 |

---

## 6. Verification & Test Plan

1. **單元測試 (`tests/test_attachment_store.py`)**:
   - `test_save_attachment_valid_png_jpeg_pdf_heic`: 測試合法格式上傳與存檔。
   - `test_save_attachment_unsafe_path_rejected`: 測試傳入 `../etc/passwd` 等無效 `case_seq` 時拋出 `UnsafeIdentifierError`。
   - `test_save_attachment_invalid_format_rejected`: 測試傳入偽造副檔名或損毀檔案時被拒絕。
   - `test_has_attachment_dynamic_driver`: 測試無檔案回傳 `False`，上傳檔案後回傳 `True`。
2. **整合測試 (`tests/test_appeal_attachment_integration.py`)**:
   - 測試 `build_appeal_draft` -> `render_appeal_json` -> `build_appeal_xml` 在有附件與無附件時，`p7_attachment` / `p7` 分別正確呈現 `"Y"` 與 `"N"`。
3. **API 測試 (`tests/test_server_attachment_routes.py`)**:
   - 測試 `/api/appeal/attachments/upload` 成功上傳。
   - 測試 `/api/appeal/generate` 端點在有無上傳檔案情況下回傳之 JSON `p7_attachment` 旗標。

---
*Report generated by research subagent for parent agent action.*
