"""影像佐證附件儲存（Phase 12）。

檔案存於 `ATTACHMENTS_DIR/<case_key>/`；索引存於 `ATTACHMENTS_DIR/attachments.sqlite3`
（review 第 5 步：原本每案一份 meta.json，靠 flock＋原子替換維持一致；改用
SQLite 交易）。case_key 一律為 CaseStore 的 case_id（A-CR-03）。

升級相容：某案目錄仍有舊版 meta.json 時，第一次存取該案會把其內容匯入
SQLite 並改名為 meta.json.migrated；meta.json 損毀時拋
AttachmentIndexCorruptError（不當成「沒有附件」，A-CR-10）。
"""

import contextlib
import json
import mimetypes
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, fields
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

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS attachments ("
    "id TEXT PRIMARY KEY, "
    "case_key TEXT NOT NULL, "
    "order_seq TEXT, "
    "order_code TEXT, "
    "filename TEXT NOT NULL, "
    "file_size INTEGER NOT NULL, "
    "mime_type TEXT NOT NULL, "
    "created_at TEXT NOT NULL"
    ")"
)
_SCHEMA_INDEX = "CREATE INDEX IF NOT EXISTS idx_attachments_case ON attachments (case_key, order_seq)"
_LEGACY_META = "meta.json"


def _db_path() -> str:
    return os.path.join(settings.ATTACHMENTS_DIR, "attachments.sqlite3")


@contextlib.contextmanager
def _connect():
    os.makedirs(settings.ATTACHMENTS_DIR, exist_ok=True)
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(_SCHEMA)
        conn.execute(_SCHEMA_INDEX)
        yield conn
    finally:
        conn.close()


def _case_dir(case_key: str) -> str:
    return os.path.join(settings.ATTACHMENTS_DIR, case_key)


def _row_to_record(row: sqlite3.Row) -> AttachmentRecord:
    # 路徑於讀取時由目錄＋檔名組出（不存絕對路徑，ATTACHMENTS_DIR 搬移後仍有效）
    return AttachmentRecord(
        id=row["id"],
        case_seq=row["case_key"],
        order_seq=row["order_seq"],
        order_code=row["order_code"],
        filename=row["filename"],
        file_path=os.path.join(_case_dir(row["case_key"]), row["filename"]),
        file_size=row["file_size"],
        mime_type=row["mime_type"],
        created_at=row["created_at"],
    )


def _migrate_legacy_meta(conn: sqlite3.Connection, case_key: str) -> None:
    """把舊版 `<case_dir>/meta.json` 匯入 SQLite（冪等），完成後改名保留。"""
    meta_path = os.path.join(_case_dir(case_key), _LEGACY_META)
    if not os.path.isfile(meta_path):
        return
    try:
        with open(meta_path, "r", encoding="utf-8") as mf:
            data = json.load(mf)
    except (OSError, json.JSONDecodeError) as exc:
        raise AttachmentIndexCorruptError(f"附件索引無法讀取：{meta_path}：{exc}") from exc
    if not isinstance(data, list):
        raise AttachmentIndexCorruptError(f"附件索引格式錯誤（非陣列）：{meta_path}")
    with conn:
        for item in data:
            if not isinstance(item, dict) or not item.get("id") or not item.get("filename"):
                raise AttachmentIndexCorruptError(f"附件索引項目格式錯誤：{meta_path}")
            conn.execute(
                "INSERT OR IGNORE INTO attachments "
                "(id, case_key, order_seq, order_code, filename, file_size, mime_type, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item["id"], case_key, item.get("order_seq"), item.get("order_code"),
                    item["filename"], int(item.get("file_size") or 0),
                    item.get("mime_type") or "application/octet-stream",
                    item.get("created_at") or "",
                ),
            )
    os.replace(meta_path, meta_path + ".migrated")


def save_attachment(
    case_seq: str,
    file_bytes: bytes,
    filename: str,
    order_seq: str | None = None,
    order_code: str | None = None,
) -> AttachmentRecord:
    """驗證並儲存附件；case_seq 參數為案件鍵（呼叫端傳 CaseStore case_id）。"""
    case_key = safe_filename(case_seq, "case_seq")
    safe_order = safe_filename(order_seq, "order_seq") if order_seq else None

    if not file_bytes or len(file_bytes) > _MAX_ATTACHMENT_BYTES:
        raise InvalidAttachmentError(f"Attachment file size out of bounds (max {_MAX_ATTACHMENT_BYTES} bytes).")

    _, ext = os.path.splitext(filename)
    mime_type = _validate_file_format(file_bytes, ext)

    att_id = uuid.uuid4().hex[:12]
    now_iso = datetime.now(timezone.utc).isoformat()
    case_dir = _case_dir(case_key)
    os.makedirs(case_dir, exist_ok=True)
    prefix = f"{safe_order}_" if safe_order else ""
    target_filename = f"{prefix}{now_iso[:10]}_{att_id}{ext.lower()}"
    file_path = os.path.join(case_dir, target_filename)

    # 先寫暫存檔再改名；索引寫入失敗時移除檔案，不留孤兒
    tmp_path = file_path + ".part"
    with open(tmp_path, "wb") as f:
        f.write(file_bytes)
    os.replace(tmp_path, file_path)
    try:
        with _connect() as conn:
            _migrate_legacy_meta(conn, case_key)
            with conn:
                conn.execute(
                    "INSERT INTO attachments "
                    "(id, case_key, order_seq, order_code, filename, file_size, mime_type, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (att_id, case_key, safe_order, order_code, target_filename,
                     len(file_bytes), mime_type, now_iso),
                )
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(file_path)
        raise

    return AttachmentRecord(
        id=att_id,
        case_seq=case_key,
        order_seq=safe_order,
        order_code=order_code,
        filename=target_filename,
        file_path=file_path,
        file_size=len(file_bytes),
        mime_type=mime_type,
        created_at=now_iso,
    )


def list_attachments(case_seq: str, order_seq: str | None = None) -> list[AttachmentRecord]:
    """列出案件（可再依醫令序過濾）且實體檔仍存在的附件，依建立時間排序。"""
    try:
        case_key = safe_filename(case_seq, "case_seq")
    except Exception:
        return []
    safe_order = safe_filename(order_seq, "order_seq") if order_seq else None

    with _connect() as conn:
        _migrate_legacy_meta(conn, case_key)
        if safe_order is None:
            rows = conn.execute(
                "SELECT * FROM attachments WHERE case_key = ? ORDER BY created_at, id",
                (case_key,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM attachments WHERE case_key = ? AND order_seq = ? "
                "ORDER BY created_at, id",
                (case_key, safe_order),
            ).fetchall()
    records = [_row_to_record(r) for r in rows]
    return [r for r in records if os.path.exists(r.file_path)]


def has_attachment(case_seq: str, order_seq: str | None = None) -> bool:
    """案件（可再依醫令序過濾）是否有實體存在的附件。"""
    return bool(list_attachments(case_seq, order_seq))


def delete_attachment(case_seq: str, attachment_id: str) -> bool:
    """刪除附件：先在交易內移除索引，再刪實體檔（中途失敗最多留下孤兒檔）。"""
    case_key = safe_filename(case_seq, "case_seq")
    with _connect() as conn:
        _migrate_legacy_meta(conn, case_key)
        with conn:
            row = conn.execute(
                "SELECT * FROM attachments WHERE case_key = ? AND id = ?",
                (case_key, attachment_id),
            ).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
    path = _row_to_record(row).file_path
    with contextlib.suppress(OSError):
        os.remove(path)
    return True
