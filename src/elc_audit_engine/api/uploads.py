"""批次匯入的上傳暫存與錯誤訊息（P1-3 防路徑穿越、A-WR-02 不外洩內部細節）。"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from elc_audit_engine.ingest import MediaExtractError
from elc_audit_engine.ingest.media import MediaLimitError

from .errors import UploadFileError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_EXTS = {".csv", ".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}


def save_upload(file_storage, raw_dir: str) -> tuple[str, str]:
    """儲存上傳檔到 raw_dir（uuid 檔名，防路徑穿越 P1-3）。回傳 (儲存路徑, 原始檔名)。"""
    filename = (file_storage.filename or "").strip()
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise UploadFileError(f"不支援的檔案類型: {ext or '(無副檔名)'}（支援 CSV / PDF / JPEG 等）")
    os.makedirs(raw_dir, exist_ok=True)
    dest = os.path.join(raw_dir, f"{uuid.uuid4().hex}{ext}")
    size = 0
    with open(dest, "wb") as out:
        while True:
            chunk = file_storage.stream.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                os.remove(dest)
                raise UploadFileError("檔案超過 10MB 上限")
            out.write(chunk)
    return dest, filename


def import_error_message(exc: Exception) -> str:
    """匯入失敗的對外訊息（A-WR-02）：不回傳外部工具 stderr、暫存路徑等內部細節。

    SamplingImportError／DeductionFileError 的訊息是給使用者看的業務說明，
    照常回傳；由 OSError 引起者與 MediaExtractError 一律改為固定訊息，細節只進
    日誌。MediaLimitError（頁數上限等）為使用者說明，原樣回傳。
    """
    if isinstance(exc, MediaLimitError):
        return f"匯入失敗：{exc}"
    if isinstance(exc, MediaExtractError) or isinstance(exc.__cause__, OSError):
        return "匯入失敗：檔案內容無法擷取（格式不支援或檔案損毀），請改以 CSV 上傳"
    return f"匯入失敗：{exc}"
