"""
Phase 13-02: ODT 填充與 PDF 渲染引擎入口
"""
from __future__ import annotations

import os
import tempfile

from elc_audit_engine.generators._soffice import convert_to_pdf
from elc_audit_engine.safe_paths import safe_filename
from .field_mapping import build_deduction_header, build_deduction_rows
from .odt_fill import fill_template
from .template import verify_template_hash, _load_expected_sha256

def render_deduction_print(
    records: list[dict],
    facility: dict,
    *,
    template_odt_path: str,
    submission: dict | None = None,
) -> tuple[bytes, list[str]]:
    """將核減資料注入 ODT 並回傳位元組內容與警告。"""
    header = build_deduction_header(records, facility)
    rows, warnings = build_deduction_rows(records, submission=submission)
    
    with tempfile.TemporaryDirectory(prefix="elc_deduction_print_") as tmp:
        filled_path = os.path.join(tmp, "filled.odt")
        fill_template(template_odt_path, header, rows, filled_path)
        with open(filled_path, "rb") as f:
            return f.read(), warnings

def write_deduction_print(
    output_dir: str | os.PathLike[str],
    file_stem: str,
    records: list[dict],
    facility: dict,
    *,
    template_odt_path: str,
    submission: dict | None = None,
    soffice_timeout: int = 120,
) -> tuple[str, list[str]]:
    """將核減明細渲染為 PDF 並寫入檔案系統，防禦 T-13-03 / T-13-04。"""
    stem = safe_filename(file_stem, "file_stem")
    os.makedirs(output_dir, exist_ok=True)
    pdf_path = os.path.join(os.fspath(output_dir), f"核減明細_{stem}.pdf")

    verify_template_hash(template_odt_path, _load_expected_sha256(template_odt_path))

    filled_odt_bytes, warnings = render_deduction_print(
        records, facility, template_odt_path=template_odt_path, submission=submission
    )

    with tempfile.TemporaryDirectory(prefix="elc_deduction_convert_") as tmp:
        filled_path = os.path.join(tmp, f"核減明細_{stem}.odt")
        with open(filled_path, "wb") as f:
            f.write(filled_odt_bytes)
        # 私有暫存目錄轉檔＋驗證輸出＋原子替換（A-WR-06）
        convert_to_pdf(filled_path, pdf_path, timeout=soffice_timeout)

    return pdf_path, warnings
