import os
import json
import uuid
import mimetypes
import contextlib
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, fields

try:  # POSIX 檔案鎖；Windows 無 fcntl 時退化為不加鎖（單機單程序部署）
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None
from PIL import Image
import pillow_heif
from pypdf import PdfReader

from config import settings
from elc_audit_engine.safe_paths import safe_filename

_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB

_MAGIC_BYTES = {
    "png": b"\x89PNG\r\n\x1a\n",
    "jpeg": b"\xff\xd8\xff",
    "pdf": b"%PDF-",
}

class AttachmentStoreError(Exception):
    """Base exception for AttachmentStore operations."""

class InvalidAttachmentError(AttachmentStoreError, ValueError):
    """Raised when an attachment file is invalid, corrupted, or unsupported."""

class AttachmentIndexCorruptError(AttachmentStoreError):
    """meta.json 索引無法解析——fail-fast，不得當成「沒有附件」（A-CR-10）。

    舊實作遇到損毀會重設成 [] 再覆寫，等於把既有附件從索引中抹除；
    列表時回 [] 則讓佐證包在無警告下缺附件、p7 誤判為 N。
    """

@dataclass(frozen=True)
class AttachmentRecord:
    id: str
    case_seq: str
    order_seq: str | None
    order_code: str | None
    filename: str
    file_path: str
    file_size: int
    mime_type: str
    created_at: str

def _validate_file_format(file_bytes: bytes, ext: str) -> str:
    """Validate file bytes against expected extension and return canonical mime type."""
    ext_clean = ext.lower().lstrip(".")
    if ext_clean in ("jpg", "jpeg"):
        if not file_bytes.startswith(_MAGIC_BYTES["jpeg"]):
            raise InvalidAttachmentError("Invalid JPEG header magic bytes.")
        try:
            with Image.open(io_bytes(file_bytes)) as img:
                img.verify()
        except Exception as exc:
            raise InvalidAttachmentError(f"Corrupted JPEG image: {exc}") from exc
        return "image/jpeg"

    elif ext_clean == "png":
        if not file_bytes.startswith(_MAGIC_BYTES["png"]):
            raise InvalidAttachmentError("Invalid PNG header magic bytes.")
        try:
            with Image.open(io_bytes(file_bytes)) as img:
                img.verify()
        except Exception as exc:
            raise InvalidAttachmentError(f"Corrupted PNG image: {exc}") from exc
        return "image/png"

    elif ext_clean == "pdf":
        if not file_bytes.startswith(_MAGIC_BYTES["pdf"]):
            raise InvalidAttachmentError("Invalid PDF header magic bytes.")
        try:
            reader = PdfReader(io_bytes(file_bytes))
            _ = len(reader.pages)
        except Exception as exc:
            raise InvalidAttachmentError(f"Corrupted PDF file: {exc}") from exc
        return "application/pdf"

    elif ext_clean in ("heic", "heif"):
        try:
            heif_file = pillow_heif.read_heif(file_bytes)
            _ = heif_file.size
        except Exception as exc:
            raise InvalidAttachmentError(f"Corrupted or invalid HEIC image: {exc}") from exc
        return "image/heic"

    else:
        raise InvalidAttachmentError(f"Unsupported attachment extension: {ext}")

def io_bytes(b: bytes):
    import io
    return io.BytesIO(b)

_RECORD_FIELDS = {f.name for f in fields(AttachmentRecord)}


@contextlib.contextmanager
def _locked_index(case_dir: str):
    """以 case 目錄下的 .meta.lock 對 meta.json 讀-改-寫加獨占鎖。"""
    os.makedirs(case_dir, exist_ok=True)
    with open(os.path.join(case_dir, ".meta.lock"), "a") as lock:
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _read_index(case_dir: str) -> list[dict]:
    meta_path = os.path.join(case_dir, "meta.json")
    if not os.path.isfile(meta_path):
        return []
    try:
        with open(meta_path, "r", encoding="utf-8") as mf:
            data = json.load(mf)
    except (OSError, json.JSONDecodeError) as exc:
        raise AttachmentIndexCorruptError(f"附件索引無法讀取：{meta_path}：{exc}") from exc
    if not isinstance(data, list):
        raise AttachmentIndexCorruptError(f"附件索引格式錯誤（非陣列）：{meta_path}")
    return data


def _write_index(case_dir: str, meta_list: list[dict]) -> None:
    """寫入暫存檔後 os.replace，崩潰時不會留下半截 JSON。"""
    fd, tmp_path = tempfile.mkstemp(dir=case_dir, prefix=".meta.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as mf:
            json.dump(meta_list, mf, ensure_ascii=False, indent=2)
            mf.flush()
            os.fsync(mf.fileno())
        os.replace(tmp_path, os.path.join(case_dir, "meta.json"))
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
        raise


def _to_record(item: dict) -> AttachmentRecord:
    return AttachmentRecord(**{k: item.get(k) for k in _RECORD_FIELDS})


def save_attachment(
    case_seq: str,
    file_bytes: bytes,
    filename: str,
    order_seq: str | None = None,
    order_code: str | None = None,
) -> AttachmentRecord:
    """Validate and save an evidence attachment file for a given case_seq and optional order_seq."""
    safe_case = safe_filename(case_seq, "case_seq")
    safe_order = safe_filename(order_seq, "order_seq") if order_seq else None

    if not file_bytes or len(file_bytes) > _MAX_ATTACHMENT_BYTES:
        raise InvalidAttachmentError(f"Attachment file size out of bounds (max {_MAX_ATTACHMENT_BYTES} bytes).")

    _, ext = os.path.splitext(filename)
    mime_type = _validate_file_format(file_bytes, ext)

    att_id = uuid.uuid4().hex[:12]
    now_iso = datetime.now(timezone.utc).isoformat()

    case_dir = os.path.join(settings.ATTACHMENTS_DIR, safe_case)
    os.makedirs(case_dir, exist_ok=True)

    prefix = f"{safe_order}_" if safe_order else ""
    target_filename = f"{prefix}{now_iso[:10]}_{att_id}{ext.lower()}"
    file_path = os.path.join(case_dir, target_filename)

    with open(file_path, "wb") as f:
        f.write(file_bytes)

    rec = AttachmentRecord(
        id=att_id,
        case_seq=safe_case,
        order_seq=safe_order,
        order_code=order_code,
        filename=target_filename,
        file_path=file_path,
        file_size=len(file_bytes),
        mime_type=mime_type,
        created_at=now_iso,
    )

    with _locked_index(case_dir):
        meta_list = _read_index(case_dir)
        meta_list.append(asdict(rec))
        _write_index(case_dir, meta_list)

    return rec

def has_attachment(case_seq: str, order_seq: str | None = None) -> bool:
    """Check if physical attachments exist for the specified case_seq (and optional order_seq)."""
    try:
        safe_case = safe_filename(case_seq, "case_seq")
    except Exception:
        return False

    case_dir = os.path.join(settings.ATTACHMENTS_DIR, safe_case)
    if not os.path.isdir(case_dir):
        return False

    records = list_attachments(case_seq, order_seq)
    return len(records) > 0

def list_attachments(case_seq: str, order_seq: str | None = None) -> list[AttachmentRecord]:
    """List all valid attachment records for a case_seq."""
    try:
        safe_case = safe_filename(case_seq, "case_seq")
    except Exception:
        return []

    case_dir = os.path.join(settings.ATTACHMENTS_DIR, safe_case)
    data = _read_index(case_dir)  # 損毀時拋 AttachmentIndexCorruptError，不回 []

    res = []
    safe_order = safe_filename(order_seq, "order_seq") if order_seq else None

    for item in data:
        rec = _to_record(item)
        if os.path.exists(rec.file_path):
            if safe_order is None or rec.order_seq == safe_order:
                res.append(rec)
    return res

def delete_attachment(case_seq: str, attachment_id: str) -> bool:
    """Delete a specified attachment record and file."""
    safe_case = safe_filename(case_seq, "case_seq")
    case_dir = os.path.join(settings.ATTACHMENTS_DIR, safe_case)
    if not os.path.isdir(case_dir):
        return False

    removed_path = None
    with _locked_index(case_dir):
        data = _read_index(case_dir)
        new_data = [item for item in data if item.get("id") != attachment_id]
        deleted = len(new_data) != len(data)
        if deleted:
            removed_path = next(
                (item.get("file_path") for item in data if item.get("id") == attachment_id), None
            )
            # 先原子更新索引再刪實體檔：中途失敗最多留下孤兒檔，不會留下指向不存在檔案的索引
            _write_index(case_dir, new_data)

    if removed_path and os.path.exists(removed_path):
        with contextlib.suppress(OSError):
            os.remove(removed_path)

    return deleted
