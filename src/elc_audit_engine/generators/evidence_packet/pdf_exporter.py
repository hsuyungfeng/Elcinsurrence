import os
import tempfile

from pypdf import PdfReader, PdfWriter

from elc_audit_engine.generators._soffice import convert_to_pdf

def convert_docx_and_merge_pdfs(
    docx_bytes: bytes,
    output_pdf_path: str,
    pdf_attachments: list[str],
    *,
    soffice_timeout: int = 120,
) -> list[str]:
    """DOCX → PDF（LibreOffice headless），再依序附加 PDF 附件，原子寫到 output_pdf_path。

    附件逐檔合併：單一附件無法讀取（加密、損毀）時略過並回報 warning，
    不讓整包失敗（A-WR-08）。warning 只含檔名，不含伺服器路徑。

    Returns:
        warnings 清單。

    Raises:
        SofficeConvertError: 主文件轉檔失敗。
    """
    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="elc_evidence_pkt_") as tmp:
        tmp_docx = os.path.join(tmp, "packet.docx")
        with open(tmp_docx, "wb") as f:
            f.write(docx_bytes)
        main_pdf_path = convert_to_pdf(
            tmp_docx, os.path.join(tmp, "packet.pdf"), timeout=soffice_timeout
        )

        writer = PdfWriter()
        for page in PdfReader(main_pdf_path).pages:
            writer.add_page(page)

        for pdf_att in pdf_attachments:
            name = os.path.basename(pdf_att)
            if not os.path.isfile(pdf_att):
                warnings.append(f"PDF 附件【{name}】不存在，未併入")
                continue
            try:
                reader = PdfReader(pdf_att)
                if reader.is_encrypted:
                    raise ValueError("encrypted")
                pages = list(reader.pages)
            except Exception as exc:  # noqa: BLE001 - 單一附件失敗不阻斷整包
                warnings.append(f"PDF 附件【{name}】無法讀取（{type(exc).__name__}），未併入")
                continue
            for page in pages:
                writer.add_page(page)

        dest_dir = os.path.dirname(os.path.abspath(output_pdf_path))
        os.makedirs(dest_dir, exist_ok=True)
        fd, staging = tempfile.mkstemp(dir=dest_dir, prefix=".pdf_", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as out_f:
                writer.write(out_f)
            os.replace(staging, output_pdf_path)
        except BaseException:
            if os.path.exists(staging):
                os.remove(staging)
            raise
    return warnings
