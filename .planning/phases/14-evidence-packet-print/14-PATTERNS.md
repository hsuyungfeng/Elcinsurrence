# Phase 14 Pattern Mapping: 審核軌跡＋病歷摘要＋申復理由＋影像佐證包列印 (Evidence Packet Print)

## 1. Overview & File Inventory

This document maps all files to be created or modified for Phase 14 to their closest existing analogs in the codebase. It extracts concrete code patterns, safety mechanisms, exception handling, and data flow patterns to ensure zero-friction implementation.

### Files to be Created:
1. `src/elc_audit_engine/generators/evidence_packet/__init__.py` - Public API facade (`render_evidence_packet`, `write_evidence_packet`)
2. `src/elc_audit_engine/generators/evidence_packet/builder.py` - DOCX builder for Cover, Audit Trail, Record Summary, Appeal Draft, and Appendices
3. `src/elc_audit_engine/generators/evidence_packet/image_processor.py` - Pillow / `pillow_heif` image loader, EXIF transpose, & A4 autoscaling
4. `src/elc_audit_engine/generators/evidence_packet/pdf_exporter.py` - Headless `soffice` DOCX->PDF converter & `pypdf` page concatenator
5. `scripts/build_evidence_packet.py` - One-shot CLI tool for evidence packet generation
6. `tests/test_evidence_packet_builder.py` - Unit tests for DOCX construction, image scaling, & error callout boxes
7. `tests/test_evidence_packet_pdf.py` - End-to-end integration tests for `soffice` conversion & `pypdf` concatenation

### Files to be Modified:
8. `src/elc_audit_engine/generators/__init__.py` - Expose `render_evidence_packet` & `write_evidence_packet` at the package level
9. `server.py` - Register `POST /api/appeal/evidence-packet/print` API endpoint & auth exemption list

---

## 2. File-by-File Pattern Mapping

### File 1: `src/elc_audit_engine/generators/evidence_packet/__init__.py`
- **Role**: Package Entry Point & Public API Facade
- **Data Flow**: Accepts raw inputs (`case_seq`, payload, facility dict, optional options) -> delegates DOCX construction to `builder.py` -> delegates PDF conversion and page merging to `pdf_exporter.py` -> returns `(bytes, warnings)` or `(pdf_path, warnings)`.
- **Closest Analog**: `src/elc_audit_engine/generators/appeal_print/__init__.py`
- **Concrete Code Pattern Excerpts**:
  ```python
  from __future__ import annotations
  import os
  import tempfile

  from elc_audit_engine.safe_paths import safe_filename

  __all__ = ["render_evidence_packet", "write_evidence_packet"]

  def render_evidence_packet(
      payload: dict,
      facility: dict,
      *,
      tracking: dict | None = None,
      timeline: PatientTimeline | None = None,
      attachments: list[dict] | None = None,
  ) -> tuple[bytes, list[str]]:
      """Pure function rendering filled Evidence Packet DOCX bytes and warnings. No side effects."""
      if not isinstance(payload, dict):
          raise TypeError(f"payload 必須為 dict，收到 {type(payload).__name__}")
      if not isinstance(facility, dict):
          raise TypeError(f"facility 必須為 dict，收到 {type(facility).__name__}")

      # Scaffolding DOCX doc using builder.py
      # ...
  ```

---

### File 2: `src/elc_audit_engine/generators/evidence_packet/builder.py`
- **Role**: Structured DOCX Scaffolding & Section Builder
- **Data Flow**: Takes structured inputs (Cover info, tracking entries, medical timeline, 4-part appeal draft, image records) -> uses `python-docx` to format section titles, styled tables, badges, callout boxes -> returns populated `docx.Document` object.
- **Closest Analogs**:
  - `src/elc_audit_engine/generators/appeal.py` (structured draft sections & defensive fallback `_fmt`)
  - `src/elc_audit_engine/reinforcement_report.py` (support badges & timeline formatting)
- **Concrete Code Pattern Excerpts**:
  ```python
  from docx import Document
  from docx.shared import Centimeters, Pt, RGBColor
  from docx.enum.text import WD_ALIGN_PARAGRAPH

  def _fmt(value) -> str:
      """Defensive display formatter converting None/empty to em-dash placeholder."""
      if value is None or value == "":
          return "—"
      return str(value)

  def build_evidence_packet_docx(
      cover_info: dict,
      tracking_data: dict,
      timeline_data: dict,
      appeal_draft: dict,
      attachment_records: list,
  ) -> tuple[Document, list[str]]:
      doc = Document()
      warnings = []

      # A4 Page Setup (2.54cm margins)
      sections = doc.sections
      for section in sections:
          section.top_margin = Centimeters(2.54)
          section.bottom_margin = Centimeters(2.54)
          section.left_margin = Centimeters(2.54)
          section.right_margin = Centimeters(2.54)

      # Section 1: Cover Page
      doc.add_heading("申復佐證包", level=0)
      # ... Table creation & formatting ...

      # Red callout box on attachment failure pattern
      def _add_warning_callout(doc: Document, text: str):
          tbl = doc.add_table(rows=1, cols=1)
          cell = tbl.cell(0, 0)
          p = cell.paragraphs[0]
          run = p.add_run(f"⚠ {text}")
          run.font.color.rgb = RGBColor(180, 0, 0)

      return doc, warnings
  ```

---

### File 3: `src/elc_audit_engine/generators/evidence_packet/image_processor.py`
- **Role**: Image Loading, EXIF Transpose & A4 Autoscaling
- **Data Flow**: Image file path or byte stream -> `pillow_heif` register -> Pillow `Image.open` -> `ImageOps.exif_transpose` -> scale dimensions to fit max printable area (16.0cm width x 22.0cm height) -> output PNG/JPEG `io.BytesIO` stream.
- **Closest Analog**: `src/elc_audit_engine/attachment_store.py` (lines 40-83 image validation & HEIC registration)
- **Concrete Code Pattern Excerpts**:
  ```python
  import io
  from PIL import Image, ImageOps
  import pillow_heif

  pillow_heif.register_heif_opener()

  MAX_WIDTH_CM = 16.0
  MAX_HEIGHT_CM = 22.0

  def process_and_scale_image(file_path: str) -> tuple[io.BytesIO, float, float]:
      """Loads, transposes EXIF orientation, and calculates scaled width in cm.

      Returns:
          (BytesIO png stream, scaled_width_cm, scaled_height_cm)
      Raises:
          Exception if image is corrupted or unsupported format.
      """
      with Image.open(file_path) as img:
          img = ImageOps.exif_transpose(img)
          orig_w, orig_h = img.size
          aspect = orig_w / orig_h
          max_aspect = MAX_WIDTH_CM / MAX_HEIGHT_CM

          if aspect > max_aspect:
              new_w = MAX_WIDTH_CM
              new_h = MAX_WIDTH_CM / aspect
          else:
              new_h = MAX_HEIGHT_CM
              new_w = MAX_HEIGHT_CM * aspect

          buf = io.BytesIO()
          img.convert("RGB").save(buf, format="JPEG", quality=85)
          buf.seek(0)
          return buf, new_w, new_h
  ```

---

### File 4: `src/elc_audit_engine/generators/evidence_packet/pdf_exporter.py`
- **Role**: Headless DOCX->PDF Converter & PDF Page Merger
- **Data Flow**: DOCX file path -> `soffice` headless conversion -> `main_packet.pdf` -> `pypdf.PdfWriter` appends `main_packet.pdf` + PDF attachment pages -> outputs `final_pdf_path`.
- **Closest Analogs**:
  - `src/elc_audit_engine/generators/appeal_print/__init__.py` (`write_appeal_print` lines 157-197 soffice process invocation)
  - `src/elc_audit_engine/attachment_store.py` (`pypdf.PdfReader` lines 63-71)
- **Concrete Code Pattern Excerpts**:
  ```python
  import os
  import subprocess
  import tempfile
  from pathlib import Path
  from pypdf import PdfReader, PdfWriter

  def convert_docx_and_merge_pdfs(
      docx_bytes: bytes,
      output_pdf_path: str,
      pdf_attachments: list[str],
      *,
      soffice_timeout: int = 120,
  ) -> None:
      with tempfile.TemporaryDirectory(prefix="elc_evidence_pkt_") as tmp:
          tmp_docx = os.path.join(tmp, "packet.docx")
          with open(tmp_docx, "wb") as f:
              f.write(docx_bytes)

          profile_dir = os.path.join(tmp, "lo_profile")
          os.makedirs(profile_dir, exist_ok=True)

          cmd = [
              "soffice",
              f"-env:UserInstallation={Path(profile_dir).as_uri()}",
              "--headless",
              "--norestore",
              "--nolockcheck",
              "--convert-to",
              "pdf",
              "--outdir",
              tmp,
              tmp_docx,
          ]
          res = subprocess.run(cmd, capture_output=True, timeout=soffice_timeout)
          if res.returncode != 0:
              raise RuntimeError(f"soffice conversion failed: {res.stderr.decode('utf-8', errors='ignore')}")

          main_pdf_path = os.path.join(tmp, "packet.pdf")
          writer = PdfWriter()
          for page in PdfReader(main_pdf_path).pages:
              writer.add_page(page)

          for pdf_att in pdf_attachments:
              if os.path.isfile(pdf_att):
                  for page in PdfReader(pdf_att).pages:
                      writer.add_page(page)

          os.makedirs(os.path.dirname(output_pdf_path), exist_ok=True)
          writer.write(output_pdf_path)
  ```

---

### File 5: `scripts/build_evidence_packet.py`
- **Role**: One-Shot CLI Script Entrypoint
- **Data Flow**: CLI arguments -> path safety checks (`safe_filename` & `os.pardir` check) -> loads case payloads & attachments -> calls `write_evidence_packet` -> outputs result and warnings.
- **Closest Analog**: `scripts/build_appeal_print.py`
- **Concrete Code Pattern Excerpts**:
  ```python
  from __future__ import annotations
  import json
  import os
  import sys
  from pathlib import Path

  _PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
  if _PROJECT_ROOT not in sys.path:
      sys.path.insert(0, _PROJECT_ROOT)

  from elc_audit_engine.safe_paths import UnsafeIdentifierError, safe_filename
  from elc_audit_engine.generators.evidence_packet import write_evidence_packet
  from config import settings

  def main(argv: list[str] | None = None) -> int:
      if argv is None:
          argv = sys.argv[1:]

      # Path traversal defense pattern (UAT-07b)
      if len(argv) > 1 and os.pardir in argv[1].split(os.sep):
          print("錯誤：輸出路徑含路徑穿越成分", file=sys.stderr)
          return 1

      # ... Arg parsing, calling write_evidence_packet, error handling ...
      return 0
  ```

---

### File 6: `server.py`
- **Role**: Flask API Endpoint Route
- **Data Flow**: `POST /api/appeal/evidence-packet/print` -> validates JSON request -> fetches `CaseStore` case payload & `attachment_store` attachments -> generates Evidence Packet PDF -> returns `{status: "success", pdf_url: ..., warnings: [...]}`.
- **Closest Analog**: `server.py` lines 1062-1119 (`generate_deduction_print`)
- **Concrete Code Pattern Excerpts**:
  ```python
  @app.route('/api/appeal/evidence-packet/print', methods=['POST'])
  def generate_evidence_packet_print():
      """生成佐證包完整 PDF (Phase 14)"""
      data = request.json or {}
      if not isinstance(data, dict):
          raise ApiError("請求主體必須為 JSON 物件")

      case_id = _clean_str(data, 'case_id', required=True)
      safe_case = safe_filename(case_id, "case_id")

      # ... call write_evidence_packet ...
      return jsonify({
          "status": "success",
          "pdf_url": f"/output/{os.path.basename(pdf_path)}",
          "warnings": warnings,
      })
  ```

---

### File 7: `src/elc_audit_engine/generators/__init__.py`
- **Role**: Subsystem Re-Export Module
- **Data Flow**: Import `render_evidence_packet` & `write_evidence_packet` from `.evidence_packet` -> append to `__all__`.
- **Closest Analog**: Existing `src/elc_audit_engine/generators/__init__.py`
- **Concrete Code Pattern Excerpts**:
  ```python
  from .evidence_packet import render_evidence_packet, write_evidence_packet

  __all__ = [
      ...
      "render_evidence_packet",
      "write_evidence_packet",
  ]
  ```

---

### Files 8 & 9: `tests/test_evidence_packet_builder.py` & `tests/test_evidence_packet_pdf.py`
- **Role**: Unit & Integration Test Suites
- **Data Flow**: Test fixtures with mock tracking, timeline, appeal draft, valid/corrupt JPEGs/HEICs/PDFs -> verify DOCX structure, red warning callout box presence, and end-to-end PDF page count.
- **Closest Analog**: `tests/test_deduction_print.py`
- **Concrete Code Pattern Excerpts**:
  ```python
  import pytest
  from elc_audit_engine.rule_repository.docx_tree.doc_converter import soffice_is_functional

  requires_soffice = pytest.mark.skipif(
      not soffice_is_functional(),
      reason="soffice not functional"
  )

  @requires_soffice
  def test_evidence_packet_pdf_e2e(tmp_path):
      # Assert PDF file created and pages merged properly
      pass
  ```
