"""
核減明細列印 - 模板處理。
"""
from __future__ import annotations
import hashlib
import os

def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _load_expected_sha256(template_odt_path: str) -> str | None:
    """讀取模板旁的 *.sha256 sidecar。

    與 appeal_print 一致（A-WR-13）：`*_print_base.odt` 屬版控資產，缺 sidecar
    即無法偵測竄改，拒絕靜默跳過校驗；其他（官方未壓縮）模板無 sidecar 回 None。
    """
    sha256_path = os.path.splitext(template_odt_path)[0] + ".sha256"
    if not os.path.isfile(sha256_path):
        if template_odt_path.endswith("_print_base.odt"):
            raise ValueError(
                "核減明細基準模板缺少 *.sha256 sidecar，無法校驗完整性；"
                "請確認 *_print_base.odt 與其 *.sha256 均已入庫"
            )
        return None
    with open(sha256_path, "r", encoding="utf-8") as f:
        return f.read().strip() or None

def verify_template_hash(template_path: str, expected_sha256: str | None) -> None:
    if not os.path.isfile(template_path):
        raise FileNotFoundError(f"Template not found: {template_path}")
    if expected_sha256 is None:
        return
    
    actual_hash = _sha256_file(template_path)
    if actual_hash.lower() != expected_sha256.strip().lower():
        raise ValueError("核減明細模板 sha256 不符，可能已被竄改（階段：verify_template_hash）")
