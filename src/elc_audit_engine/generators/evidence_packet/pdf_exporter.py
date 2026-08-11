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
    """
    Converts DOCX bytes to PDF via LibreOffice headless and appends PDF attachments.
    Saves to output_pdf_path.
    """
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
        if not os.path.exists(main_pdf_path):
            raise RuntimeError(f"soffice conversion failed: expected output file {main_pdf_path} not found.")

        writer = PdfWriter()
        for page in PdfReader(main_pdf_path).pages:
            writer.add_page(page)

        for pdf_att in pdf_attachments:
            if os.path.isfile(pdf_att):
                for page in PdfReader(pdf_att).pages:
                    writer.add_page(page)

        os.makedirs(os.path.dirname(os.path.abspath(output_pdf_path)), exist_ok=True)
        with open(output_pdf_path, "wb") as out_f:
            writer.write(out_f)
