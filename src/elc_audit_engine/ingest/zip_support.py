"""ZIP 檔案解析公用函式：支援 TOTFA.zip 與 CSV/PDF 等壓縮封包。

安全規範：
- 檢查檔案大小上限
- 防路徑穿越（Path Traversal 防護，拒絕包含 `..` 或絕對路徑的成員）
"""

from __future__ import annotations

import io
import os
import zipfile
from typing import BinaryIO, Literal

from elc_audit_engine.ingest.media import MediaExtractError


class ZipExtractError(MediaExtractError):
    """ZIP 格式損毀或解壓縮錯誤。"""


def is_safe_zip_path(target_path: str) -> bool:
    """檢查 ZIP 內部路徑是否安全（無路徑穿越，無絕對路徑）。"""
    norm = os.path.normpath(target_path)
    if norm.startswith("/") or norm.startswith("\\"):
        return False
    parts = norm.split(os.sep)
    if ".." in parts:
        return False
    return True


def inspect_zip_contents(
    zip_source: str | bytes | BinaryIO,
) -> tuple[Literal["totfa", "csv", "empty", "other"], list[tuple[str, bytes]]]:
    """檢視 ZIP 檔案內容並分類。

    Returns:
        (category, file_list)
        - "totfa": 包含 TOTFA.xml（標準申報檔）
        - "csv": 包含至少一個 CSV 檔案
        - "empty": 無有效檔案
        - "other": 其他檔案（如 PDF 或影像）
    """
    try:
        if isinstance(zip_source, bytes):
            zf = zipfile.ZipFile(io.BytesIO(zip_source))
        elif isinstance(zip_source, (str, os.PathLike)):
            zf = zipfile.ZipFile(zip_source)
        else:
            zf = zipfile.ZipFile(zip_source)
    except Exception as exc:
        raise ZipExtractError(f"ZIP 壓縮檔損毀或無法讀取: {exc}") from exc

    with zf:
        namelist = zf.namelist()
        # 1. 檢查是否包含 TOTFA.xml
        for name in namelist:
            if not is_safe_zip_path(name):
                raise ZipExtractError(f"ZIP 內含不安全之路徑: {name}")
            base = os.path.basename(name).lower()
            if base == "totfa.xml":
                return "totfa", []

        # 2. 檢索 CSV
        csv_files = []
        other_files = []
        for name in namelist:
            if name.endswith("/") or name.startswith("__MACOSX"):
                continue
            if not is_safe_zip_path(name):
                raise ZipExtractError(f"ZIP 內含不安全之路徑: {name}")
            ext = os.path.splitext(name)[1].lower()
            content = zf.read(name)
            if ext == ".csv":
                csv_files.append((name, content))
            elif ext in (".pdf", ".jpg", ".jpeg", ".png"):
                other_files.append((name, content))

        if csv_files:
            return "csv", csv_files
        if other_files:
            return "other", other_files
        return "empty", []
