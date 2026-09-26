"""請求欄位驗證（P1-5：入參長度上限）。"""

from __future__ import annotations

from .errors import ApiError

# SOAP 全文取 10KB，其餘識別欄位取短上限——正常值都是代碼/流水號等級的長度。
MAX_SOAP_CHARS = 10_000
MAX_FIELD_CHARS = 200


def clean_str(data: dict, key: str, *, required: bool = False, max_len: int = MAX_FIELD_CHARS) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise ApiError(f"欄位 {key} 必須為字串")
    value = value.strip()
    if required and not value:
        raise ApiError(f"缺少必要欄位 {key}")
    if len(value) > max_len:
        raise ApiError(f"欄位 {key} 超過長度上限（{max_len} 字）")
    return value


def json_body(request) -> dict:
    data = request.json or {}
    if not isinstance(data, dict):
        raise ApiError("請求主體必須為 JSON 物件")
    return data
