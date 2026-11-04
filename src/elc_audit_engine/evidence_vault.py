"""佐證庫（Evidence Vault）：依 `身分證字號-年月` 歸檔病患月份的佐證檔案（Phase 17-01）。

目錄結構：`<DATA_DIR>/evidence_vault/<vault_key>/<category>/<filename>`

- `vault_key` 格式 `^[A-Z][0-9]{9}-[0-9]{4}$`（如 `A123625499-2605`），
  以 `fullmatch` 校驗，不接受任何路徑成分。
- 檔案依副檔名自動分入 `images` / `audio` / `reports` / `records`；不在白名單內的副檔名拒收。
- 上傳 ZIP 時逐一解開成員，每個成員同樣依副檔名分類；成員若含目錄成分一律取 basename 攤平，
  含 `..`、絕對路徑、空檔名或超過解壓上限者整包拒絕，不做靜默改寫。

與 `safe_paths.py` 相同原則：**校驗後拒絕，而非清洗取代**。
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from dataclasses import dataclass
from typing import BinaryIO

from config import settings
from elc_audit_engine.services.date_utils import ROC_OFFSET

VAULT_KEY_RE = re.compile(r"[A-Z][0-9]{9}-[0-9]{4}")

CATEGORY_EXTENSIONS: dict[str, frozenset[str]] = {
    "images": frozenset({".jpg", ".jpeg", ".png", ".dicom", ".heic"}),
    "audio": frozenset({".mp3", ".m4a", ".wav", ".aac"}),
    "reports": frozenset({".pdf", ".txt", ".csv"}),
    "records": frozenset({".txt", ".json"}),
}

# 同一副檔名可能屬多個分類（如 .txt）：依此順序取第一個命中者。
_CATEGORY_ORDER = ("images", "audio", "reports", "records")

# ZIP 解壓上限，防止壓縮炸彈（單檔上限與整包解壓總量）。
MAX_ZIP_MEMBERS = 500
MAX_MEMBER_BYTES = 50 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 200 * 1024 * 1024
_COPY_CHUNK = 64 * 1024


class VaultError(ValueError):
    """佐證庫操作的呼叫方錯誤（格式不合法、檔案不支援等），可安全回傳給前端。"""


class InvalidVaultKeyError(VaultError):
    """vault_key 不符合 `身分證字號-年月` 格式。"""


class UnsupportedFileError(VaultError):
    """副檔名不在任何分類白名單內，或檔名不合法。"""


@dataclass(frozen=True)
class VaultFile:
    vault_key: str
    category: str
    filename: str
    size: int
    path: str


_CASE_RECORD_NO_RE = re.compile(r"[A-Z][0-9]{9}")
_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_ROC_DATE_RE = re.compile(r"(\d{3})(\d{2})(\d{2})")


def vault_key_for_case(record_no: object, visit_date: object) -> str | None:
    """由案件病歷號與就醫日推導 vault_key（與 static/index.html 的 computeVaultKey 規則一致）。

    病歷號須為「1 英文字母＋9 碼數字」；就醫日接受 `YYYY-MM-DD` 或民國 `YYYMMDD`，
    取西元年後兩碼＋月份。任一條件不符回傳 None，不猜測。
    """
    no = "" if record_no is None else str(record_no).strip().upper()
    if not _CASE_RECORD_NO_RE.fullmatch(no):
        return None
    visit = "" if visit_date is None else str(visit_date).strip()
    iso = _ISO_DATE_RE.fullmatch(visit)
    roc = _ROC_DATE_RE.fullmatch(visit)
    if iso:
        year, month = int(iso.group(1)), int(iso.group(2))
    elif roc:
        year, month = int(roc.group(1)) + ROC_OFFSET, int(roc.group(2))
    else:
        return None
    if not 1 <= month <= 12:
        return None
    return f"{no}-{year % 100:02d}{month:02d}"


def vault_root() -> str:
    """佐證庫根目錄（每次呼叫時讀取 settings，便於測試替換 DATA_DIR）。"""
    return os.path.join(settings.DATA_DIR, "evidence_vault")


def validate_vault_key(vault_key: object) -> str:
    """校驗 vault_key，通過則原樣回傳；失敗拋 InvalidVaultKeyError。"""
    raw = "" if vault_key is None else str(vault_key)
    if not VAULT_KEY_RE.fullmatch(raw):
        raise InvalidVaultKeyError(f"vault_key 格式錯誤（應為 身分證字號-年月，如 A123625499-2605）：{raw!r}")
    return raw


def _validate_category(category: object) -> str:
    raw = "" if category is None else str(category)
    if raw not in CATEGORY_EXTENSIONS:
        raise UnsupportedFileError(f"未知的佐證分類：{raw!r}")
    return raw


def _validate_filename(filename: object) -> str:
    """檔名必須已是單一路徑段：不接受分隔符、`.`/`..`、控制字元或空值（不做 basename 清洗）。"""
    raw = "" if filename is None else str(filename)
    if (
        not raw
        or raw in (".", "..")
        or "/" in raw
        or "\\" in raw
        or ":" in raw
        or "\x00" in raw
        or any(ord(ch) < 32 for ch in raw)
        or raw != raw.strip()
    ):
        raise UnsupportedFileError(f"檔名含不允許的字元或路徑成分，拒絕接收：{raw!r}")
    return raw


def classify(filename: str) -> str:
    """依副檔名回傳分類名稱；不在白名單內拋 UnsupportedFileError。"""
    ext = os.path.splitext(filename)[1].lower()
    for category in _CATEGORY_ORDER:
        if ext in CATEGORY_EXTENSIONS[category]:
            return category
    raise UnsupportedFileError(f"不支援的檔案類型：{filename!r}")


def _vault_dir(vault_key: str) -> str:
    return os.path.join(vault_root(), validate_vault_key(vault_key))


def _category_dir(vault_key: str, category: str) -> str:
    return os.path.join(_vault_dir(vault_key), _validate_category(category))


def _resolve_inside(base: str, *parts: str) -> str:
    """組合路徑並確認結果仍位於 base 之下（縱深防禦，防止 symlink 或遺漏的校驗）。"""
    base_real = os.path.realpath(base)
    target = os.path.realpath(os.path.join(base, *parts))
    if os.path.commonpath([base_real, target]) != base_real:
        raise UnsupportedFileError("目標路徑超出佐證庫範圍，拒絕存取")
    return target


def _unique_target(directory: str, filename: str) -> str:
    """若檔名已存在則加 `_1`、`_2`… 後綴，絕不覆寫既有佐證。"""
    stem, ext = os.path.splitext(filename)
    candidate = filename
    n = 1
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{stem}_{n}{ext}"
        n += 1
    return os.path.join(directory, candidate)


def _store_stream(vault_key: str, filename: str, stream: BinaryIO, limit: int | None) -> VaultFile:
    category = classify(filename)
    directory = _category_dir(vault_key, category)
    os.makedirs(directory, exist_ok=True)
    target = _unique_target(directory, filename)
    tmp_path = target + ".part"
    written = 0
    try:
        with open(tmp_path, "wb") as out:
            while True:
                chunk = stream.read(_COPY_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if limit is not None and written > limit:
                    raise VaultError(f"檔案解壓後超過單檔上限 {limit} bytes：{filename!r}")
                out.write(chunk)
        os.replace(tmp_path, target)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    return VaultFile(
        vault_key=vault_key,
        category=category,
        filename=os.path.basename(target),
        size=written,
        path=target,
    )


def store_single_file(vault_key: str, filename: str, data: bytes) -> VaultFile:
    """儲存單一佐證檔案並依副檔名自動分類。"""
    validate_vault_key(vault_key)
    safe_name = _validate_filename(filename)
    return _store_stream(vault_key, safe_name, io.BytesIO(data), limit=None)


def store_zip(vault_key: str, data: bytes) -> list[VaultFile]:
    """解開 ZIP 並把每個支援的成員分入對應子分類。

    任何一個成員不合法（路徑穿越、不支援類型、超過上限）即整包拒收，
    並清除本次已寫入的檔案，避免留下半套佐證。
    """
    validate_vault_key(vault_key)
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise VaultError(f"ZIP 檔案損毀或格式錯誤：{exc}") from exc

    stored: list[VaultFile] = []
    try:
        with archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if len(members) > MAX_ZIP_MEMBERS:
                raise VaultError(f"ZIP 內檔案數超過上限 {MAX_ZIP_MEMBERS}")
            declared_total = sum(m.file_size for m in members)
            if declared_total > MAX_ZIP_TOTAL_BYTES:
                raise VaultError(f"ZIP 解壓後總量超過上限 {MAX_ZIP_TOTAL_BYTES} bytes")

            for member in members:
                # 只取 basename 攤平目錄成分；basename 本身仍須通過單段檔名校驗。
                name = member.filename.replace("\\", "/").rsplit("/", 1)[-1]
                if member.filename.startswith("/") or ".." in member.filename.replace("\\", "/").split("/"):
                    raise UnsupportedFileError(f"ZIP 成員路徑含穿越成分，整包拒收：{member.filename!r}")
                safe_name = _validate_filename(name)
                with archive.open(member) as src:
                    stored.append(_store_stream(vault_key, safe_name, src, limit=MAX_MEMBER_BYTES))
    except BaseException:
        for item in stored:
            if os.path.exists(item.path):
                os.remove(item.path)
        raise
    return stored


def list_vault_files(vault_key: str) -> dict[str, list[VaultFile]]:
    """列出某 vault_key 下各分類的檔案；尚未建立時回傳每類皆為空清單。"""
    validate_vault_key(vault_key)
    result: dict[str, list[VaultFile]] = {}
    for category in _CATEGORY_ORDER:
        directory = os.path.join(_vault_dir(vault_key), category)
        files: list[VaultFile] = []
        if os.path.isdir(directory):
            for name in sorted(os.listdir(directory)):
                path = os.path.join(directory, name)
                if not os.path.isfile(path) or name.endswith(".part"):
                    continue
                files.append(VaultFile(vault_key, category, name, os.path.getsize(path), path))
        result[category] = files
    return result


def get_vault_file(vault_key: str, category: str, filename: str) -> VaultFile:
    """取得單一檔案的 metadata 與實體路徑；不存在拋 FileNotFoundError。"""
    validate_vault_key(vault_key)
    _validate_category(category)
    safe_name = _validate_filename(filename)
    path = _resolve_inside(_category_dir(vault_key, category), safe_name)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"找不到佐證檔案：{category}/{safe_name}")
    return VaultFile(vault_key, category, safe_name, os.path.getsize(path), path)
