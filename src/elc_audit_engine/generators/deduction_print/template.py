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
    sha256_path = os.path.splitext(template_odt_path)[0] + ".sha256"
    if not os.path.isfile(sha256_path):
        return None
    with open(sha256_path, "r", encoding="utf-8") as f:
        return f.read().strip()

def verify_template_hash(template_path: str, expected_sha256: str | None) -> None:
    if not os.path.isfile(template_path):
        raise FileNotFoundError(f"Template not found: {template_path}")
    if expected_sha256 is None:
        raise ValueError("Expected SHA256 is required.")
    
    actual_hash = _sha256_file(template_path)
    if actual_hash != expected_sha256:
        raise ValueError(f"Template hash mismatch. Expected {expected_sha256}, got {actual_hash}")
