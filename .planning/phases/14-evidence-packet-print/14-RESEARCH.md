# Phase 14 Research: 審核軌跡＋病歷摘要＋申復理由＋影像佐證包列印 (Evidence Packet Print)

## Executive Summary

Phase 14 is the final output puzzle piece of Milestone v1.1 ("紙本→數位化整合三項輸出"). Its core objective is to synthesize four distinct system outputs—Audit Trail (`tracking.json`), Medical Record Summary (`reinforcement_report.py`), 4-Part Appeal Draft (`appeal.py` / `AppealDraft`), and Uploaded Image/PDF Attachments (`attachment_store.py`)—into a unified, printable, multi-page PDF "Evidence Packet" (`申復佐證包_{case_seq}.pdf`).

This document provides the full technical research and design contract needed to plan and execute Phase 14 with zero ambiguity.

---

## 1. Requirement & Success Criteria Mapping

### Target Requirement
- **Requirement ID**: `REQ-evidence-packet-print`
- **Scope**: Milestone v1.1 Phase 14

### Success Criteria & Verification Strategy

| # | Criteria Requirement | Implementation & Technical Mechanism | Verification Method |
|---|---|---|---|
| 1 | 產出包含摘要封面、審核軌跡與決策歷史、申復理由全文、以及多頁佐證影像圖表附錄的完整 PDF 包。 | Build styled DOCX via `python-docx` merging Cover + Audit Trail + Medical Summary + 4-Part Appeal Draft + Image Appendix, then convert via `soffice` and merge PDF attachments via `pypdf`. | End-to-end PDF generation test checking section layout and page counts (`pypdf.PdfReader`). |
| 2 | 圖片自動縮放排版適配 A4 頁面，損毀或格式不符影像自動註記並降級跳過。 | `Pillow` + `pillow_heif` auto-rotate EXIF orientation, scale to A4 printable area (max 16cm x 22cm). Exception handler catches corrupted files, populates `warnings`, and renders a red callout box in DOCX without crashing. | Unit test passing corrupt JPEG/HEIC/PDF files; verify PDF generates with red warning callout and `warnings` list populated. |
| 3 | 支援單一 CLI 指令或 API 端點一鍵生成案件完整佐證包。 | CLI `scripts/build_evidence_packet.py` + Flask endpoint `POST /api/appeal/evidence-packet/print` calling `write_evidence_packet()`. | Integration test verifying CLI execution and API endpoint response (200 OK + PDF binary/path). |

---

## 2. Input Data Sources & Subsystem Integration

Phase 14 synthesizes inputs from four core subsystems:

```text
┌───────────────────────────────────────────────────────────────────────────┐
│                          Input Subsystems                                 │
├───────────────────┬───────────────────┬───────────────────┬───────────────┤
│  Phase 6 Tracking │ Phase 4 & 6 Report│ Phase 7 Appeal    │ Phase 12 Store│
│  (tracking.json)  │ (reinforcement.py)│ (AppealDraft/json)│(attachments)  │
└─────────┬─────────┴─────────┬─────────┴─────────┬─────────┴───────┬───────┘
          │                   │                   │                 │
          ▼                   ▼                   ▼                 ▼
┌───────────────────────────────────────────────────────────────────────────┐
│             Phase 14 Evidence Packet Builder (builder.py)                 │
│                                                                           │
│  1. Cover Page & Case Summary (院所/案件/核減點數/申復點數/附件統計)        │
│  2. Audit Trail & Review History (reviewed_at, entries 狀態對照表)          │
│  3. Medical Record Summary (半年病史時間軸 + 支持度徽章 + SOAP 引文)        │
│  4. 4-Part Appeal Draft Full Text (①案情摘要 ②醫療必要性 ③規則依據 ④病歷佐證)  │
│  5. Evidence Image Appendices (Pillow/pillow_heif 縮放適配 A4 影像)         │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │ (python-docx)
                                      ▼
                           temporary DOCX file
                                      │ (soffice --convert-to pdf)
                                      ▼
                              main_packet.pdf
                                      │
                                      ├─ (If PDF attachments exist: pypdf.PdfWriter merge)
                                      ▼
                        申復佐證包_{case_seq}.pdf
```

### Data Integration Breakdown

1. **Cover & Case Summary Section**:
   - Patient Info: `case_class`, `case_seq`, `case_record_no`, `visit_date`, `fee_year_month`.
   - Clinic Info: `facility` dict (`code`, `name`, `doctor_name`).
   - Overview Metrics: Denied order count, total non-reimbursed points, total claimed appeal points, total attachment files count.
2. **Audit Trail & Decision History Section**:
   - Source: `render_tracking()` / `tracking.json`.
   - Fields: `reviewed_at`, `entries` (order_code, status [採用/編輯後採用/略過/標記不符事實/未審核], narrative_text, edited_text, rule_location).
3. **Medical Record Summary Section**:
   - Source: `reinforcement_report.py` / `PatientTimeline`.
   - Fields: 6-month history metrics (visits, labs, exams, imaging), support level badges (`✅ 充分`, `⚠️ 薄弱`, `❌ 裸奔`, `⏳ 待判定`, `❓ 查無規則`), SOAP comparison snippets.
4. **Appeal Draft & Reasons Section**:
   - Source: `appeal.py` (`AppealDraft` / `appeal.json`).
   - Fields: 4 sections (`① 案情摘要`, `② 醫療必要性`, `③ 規則依據`, `④ 病歷佐證`), `p6_points`, `p7_attachment`, `p8_reason1`, `p9_reason2`.
5. **Evidence Attachments Appendix Section**:
   - Source: `attachment_store.py` (`list_attachments(case_seq)`).
   - Fields: Attachment records (`filename`, `file_path`, `mime_type`, `order_seq`, `order_code`, `created_at`).

---

## 3. PDF Technical Pipeline Architecture

### Selected Technology Stack
- **Document Scaffolding**: `python-docx` (already in `pyproject.toml`, handles styled tables, paragraphs, A4 margins, headers/footers, callout boxes).
- **Image Processing**: `Pillow` + `pillow_heif` (already in `pyproject.toml`, handles PNG, JPEG, HEIC/HEIF reading, EXIF rotation, aspect-ratio scaling).
- **PDF Conversion**: `soffice` (LibreOffice headless CLI, proven in Phase 11 & Phase 13).
- **PDF Concatenation**: `pypdf` (already in `dependency-groups.dev`, merges multi-page attachment PDFs).

### Image Processing & Resizing Algorithm

For each image attachment (`image/jpeg`, `image/png`, `image/heic`):
1. **Load Image**: Use `Pillow` (`Image.open()`). For HEIC/HEIF files, register `pillow_heif.register_heif_opener()` during startup.
2. **Auto-Rotate EXIF**: Apply `ImageOps.exif_transpose(img)` to correct sideways/upside-down camera photos (common in clinic mobile scans).
3. **Calculate Scaled Dimensions**:
   - A4 printable area: Width = 16.0 cm (~6.3 inches), Height = 22.0 cm (~8.6 inches).
   - If `orig_w / orig_h > max_w / max_h`, fit by width (`new_w = max_w`, `new_h = max_w / aspect`).
   - Otherwise, fit by height (`new_h = max_h`, `new_w = max_h * aspect`).
4. **Insert into DOCX**: Convert image to PNG/JPEG stream in `io.BytesIO()`, call `doc.add_picture(stream, width=Centimeters(new_w))`.
5. **Error Handling**: Wrap in `try...except Exception as exc:`. On error:
   - Append warning string to `warnings: list[str]`.
   - Insert red-bordered callout box in DOCX: `⚠ 附件檔【filename】載入失敗（原因: {exc}），已降級跳過。`

### PDF Attachment Merging Algorithm

For PDF attachments (`application/pdf`):
1. Validate PDF header magic bytes and page count using `pypdf.PdfReader`.
2. In the main DOCX document, insert an Appendix placeholder paragraph:
   `附件 {X}: {filename} (PDF 格式，共 {N} 頁，頁面已拼合至本檔末端)`
3. After `soffice` converts DOCX to `main_packet.pdf`, execute PDF merger:
   ```python
   writer = PdfWriter()
   for page in PdfReader(main_packet_pdf_path).pages:
       writer.add_page(page)
   for pdf_att_path in pdf_attachments:
       for page in PdfReader(pdf_att_path).pages:
           writer.add_page(page)
   writer.write(final_pdf_path)
   ```

---

## 4. Defensive & Security Principles

1. **Path Traversal Defense (P1-3 / T-11-04)**:
   - Validate `case_seq`, `file_stem`, `order_seq`, and output directories using `safe_filename()`.
   - Reject any paths containing `os.pardir` or path traversal components.
2. **PHI Privacy Safeguards (D2)**:
   - 100% local execution. Zero network calls or external SaaS API calls.
3. **Failure Isolation (P1-1)**:
   - Missing attachments, corrupted image files, or unreviewed tracking entries MUST NOT crash the packet generation process.
   - Clean warnings returned in `(pdf_path, warnings)` output tuple.
4. **Temporary Workspace Hygiene**:
   - Intermediate `.docx` files and headless `soffice` profiles must be placed inside `tempfile.TemporaryDirectory()` and cleaned up immediately upon completion.

---

## 5. Subsystem Package Structure

```text
src/elc_audit_engine/generators/evidence_packet/
├── __init__.py           # Public API: render_evidence_packet(), write_evidence_packet()
├── builder.py            # DOCX Builder (Cover, Tracking, Record Summary, Appeal Draft, Appendices)
├── image_processor.py    # Pillow/pillow_heif image loader, EXIF transpose & A4 scaler
└── pdf_exporter.py       # soffice DOCX->PDF converter + pypdf page concatenator

scripts/
└── build_evidence_packet.py  # One-shot CLI script for generating Evidence Packet PDF

server.py
└── POST /api/appeal/evidence-packet/print  # Flask API endpoint
```

---

## 6. Recommended Execution Strategy (Wave Breakdown)

### Plan 14-01: Evidence Packet DOCX Builder & Image Processor
- Deliver `builder.py` and `image_processor.py`.
- Implement section generators: Cover Page, Audit Trail table, Medical Record summary, 4-part Appeal Draft, Image Appendices.
- Implement image scaling, EXIF auto-rotation, and corrupted file error callout boxes.
- Unit tests in `tests/test_evidence_packet_builder.py` (verify DOCX document structure with mock data and sample images).

### Plan 14-02: PDF Exporter, PDF Concatenator & CLI Tool
- Deliver `pdf_exporter.py`, `__init__.py`, and `scripts/build_evidence_packet.py`.
- Implement `render_evidence_packet` & `write_evidence_packet`.
- Wire `soffice` headless conversion and `pypdf` PDF attachment concatenation.
- Add CLI options `--case-seq`, `--output-dir`, `--facility-config`.
- Integration tests in `tests/test_evidence_packet_pdf.py` (verify end-to-end PDF generation, page count, and warning handling).

### Plan 14-03: Flask API Route Wiring & Verification
- Wire `POST /api/appeal/evidence-packet/print` in `server.py`.
- Connect route to `CaseStore` and `attachment_store`.
- Audit logging integration (`record_access()`).
- Verify against real sample data (`data/sampleimage/` / sample cases).

---

## 7. Next Steps for Planning

The team can now proceed to run `/gsd-plan-phase 14` with full clarity on the architecture, technical stack, file locations, error handling contracts, and plan breakdown.
