"""媒體攝入層 — CSV／PDF／影像的型別偵測與文字提取。

一律使用**本機系統工具**（pdftotext / pdftoppm / tesseract），不呼叫任何
雲端 OCR／文件 API —— D2 紅線：清單與病歷個資不出本機。

管道：
- CSV   → 不做文字提取，由各 parser（sampling.py / parsers.deduction）直接讀檔
- PDF   → pdftotext 提取文字層；輸出過少（掃描型 PDF，無文字層）→
           pdftoppm 渲染每頁 PNG → tesseract OCR
- 影像  → tesseract OCR（chi_tra+eng）

錯誤語意：本模組只拋 MediaExtractError（輸入/工具故障），不拋業務結論。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# pdftotext 輸出少於此字數視為掃描型 PDF（無文字層，需走 OCR）。
_TEXT_PDF_MIN_CHARS = 40

# tesseract 可讀的影像副檔名（leptonica 支援集）。
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}

# OCR 語言：台灣健保清單以繁體中文為主，混英文代碼。
OCR_LANG = "chi_tra+eng"


class MediaExtractError(Exception):
    """媒體無法讀取／系統工具缺失／OCR 失敗（輸入故障語意）。"""


def detect_media_type(filename: str) -> str:
    """依副檔名回傳 ``csv`` / ``pdf`` / ``image``；不支援則拋 MediaExtractError。

    Args:
        filename: 上傳檔名（僅副檔名有意義）。
    """
    ext = Path(filename).suffix.lower()
    if ext == ".csv":
        return "csv"
    if ext == ".pdf":
        return "pdf"
    if ext in _IMAGE_EXTS:
        return "image"
    raise MediaExtractError(
        f"不支援的檔案類型: {ext or '(無副檔名)'}（支援 CSV / PDF / JPEG 等影像）"
    )


def _run(tool: str, args: list[str]) -> subprocess.CompletedProcess:
    """執行系統工具；缺失或逾時皆轉為 MediaExtractError。"""
    try:
        return subprocess.run(
            [tool, *args],
            capture_output=True,
            timeout=120,
            check=False,
        )
    except FileNotFoundError as exc:
        raise MediaExtractError(
            f"系統工具 {tool} 不存在，無法處理此檔案"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaExtractError(f"{tool} 處理逾時（120 秒）") from exc


def extract_pdf_text(path: str, min_chars: int = _TEXT_PDF_MIN_CHARS) -> str:
    """pdftotext -layout 提取 PDF 文字層；輸出過少（掃描型）回傳空字串。"""
    proc = _run("pdftotext", ["-layout", str(path), "-"])
    text = proc.stdout.decode("utf-8", errors="replace")
    return text if len(text.strip()) >= min_chars else ""


def render_pdf_pages(path: str, out_dir: str, dpi: int = 200) -> list[str]:
    """pdftoppm 渲染 PDF 每頁為 PNG；回傳圖片路徑（依頁序）。"""
    prefix = os.path.join(out_dir, "page")
    proc = _run("pdftoppm", ["-png", "-r", str(dpi), str(path), prefix])
    if proc.returncode != 0:
        raise MediaExtractError(
            "pdftoppm 渲染失敗: "
            + proc.stderr.decode("utf-8", errors="replace")[:200]
        )
    pages = sorted(Path(out_dir).glob("page-*.png"))
    if not pages:
        raise MediaExtractError("pdftoppm 未產出任何頁面影像")
    return [str(p) for p in pages]


def ocr_image(path: str, lang: str = OCR_LANG) -> str:
    """tesseract OCR 單張影像 → 純文字（psm 6：假設統一文字區塊）。"""
    proc = _run("tesseract", [str(path), "stdout", "-l", lang, "--psm", "6"])
    if proc.returncode != 0:
        # 錯誤細節只進 stderr（由上層 log），對外回覆不帶工具內部訊息。
        raise MediaExtractError(
            "tesseract 辨識失敗：影像無法讀取或格式不支援"
        )
    return proc.stdout.decode("utf-8", errors="replace")


def extract_text(path: str, *, media_type: str | None = None) -> tuple[str, str]:
    """依型別提取全部文字；回傳 (文字, 實際使用的工具)。

    - pdf：pdftotext；掃描型 → pdftoppm + tesseract
    - image：tesseract
    - csv：不提取（回 ``("", "")``），由各 parser 自行讀檔

    Raises:
        MediaExtractError: 型別不支援／工具缺失／OCR 無結果。
    """
    media_type = media_type or detect_media_type(path)
    if media_type == "pdf":
        text = extract_pdf_text(path)
        if text:
            return text, "pdftotext"
        out_dir = tempfile.mkdtemp(prefix="elc_pdf_ocr_")
        try:
            pages = render_pdf_pages(path, out_dir)
            parts = [ocr_image(p) for p in pages]
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
        joined = "\n".join(parts)
        if not joined.strip():
            raise MediaExtractError("PDF 無文字層且 OCR 無結果，無法提取內容")
        return joined, "pdftoppm+tesseract"
    if media_type == "image":
        text = ocr_image(path)
        if not text.strip():
            raise MediaExtractError("OCR 無結果，影像可能空白或格式不支援")
        return text, "tesseract"
    return "", ""
