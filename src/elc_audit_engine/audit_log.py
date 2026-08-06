"""存取審計日誌（Phase 9-01：誰在何時存取了什麼端點，零 PHI）。

**禁止記錄的欄位**（一律拋 `AuditFieldError`，絕不靜默剔除）：

- SOAP 全文（`soap`／`soap_text`）
- 病歷號（`record_no`）
- 患者姓名（`patient_name`）
- 身分證號（`id_number`）
- 出生日期（`birth_date`）

理由：審計的目的是「誰在何時存取了哪個端點、結果狀態碼為何」——這是
**存取行為**的紀錄，不是病歷內容的複製。若日誌本身夾帶 PHI，日誌檔案
就成了一個新的洩漏面，與既有 PHI 防護原則（D2／P0-3：個資不出本機、
輸出檔案一律走白名單檢查）背道而馳。

企圖寫入禁止欄位或超長字串時**明確拋錯**而非靜默剔除欄位：靜默剔除會
讓呼叫端誤以為記錄已完整寫入，這與本專案「系統故障必須與業務結論可
區分」的同源原則相符——記錄失敗（含「內容不合規」）必須是呼叫端可見
的錯誤，而不是一個看似成功、實際上少了東西的日誌列。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from config.settings import AUDIT_LOG_PATH

_logger = logging.getLogger(__name__)

#: 禁止出現在 `detail` 鍵中的欄位——皆為 PHI 或近似 PHI 的識別資訊。
_FORBIDDEN_KEYS = frozenset(
    {"soap", "soap_text", "record_no", "patient_name", "id_number", "birth_date"}
)

#: `detail` 內字串值長度上限。長字串是 PHI 夾帶的主要途徑（例如整段
#: SOAP 文字塞進一個非禁止鍵名裡）；審計只需要識別碼層級的資料，
#: 正常值（醫令代碼、caller_id 等）都遠短於此門檻。
_MAX_DETAIL_STR_LEN = 100


class AuditFieldError(ValueError):
    """企圖寫入禁止欄位或超長字串到審計日誌時拋出。"""


def record_access(
    *,
    caller_id: str,
    method: str,
    path: str,
    status: int,
    detail: dict | None = None,
    log_path: str | None = None,
) -> str:
    """寫入一列存取審計紀錄（JSON Lines，附加寫入，UTC 時間戳）。

    Args:
        caller_id: 呼叫方識別（來自 `auth.resolve_caller`，或
            `"anonymous"` 表示未認證/豁免端點）。
        method: HTTP 方法（如 `GET`／`POST`）。
        path: 請求路徑。
        status: HTTP 回應狀態碼。
        detail: 額外的識別碼層級資訊（如醫令代碼）；**不得**含
            `_FORBIDDEN_KEYS` 中任一鍵，字串值長度不得超過
            `_MAX_DETAIL_STR_LEN`。
        log_path: 覆寫預設寫入路徑（測試用）；None 時用
            `config.settings.AUDIT_LOG_PATH`。

    Returns:
        寫入的那一列 JSON 字串（不含結尾換行），供測試與呼叫端斷言。

    Raises:
        AuditFieldError: `detail` 含禁止欄位或字串值過長。
        OSError: 寫檔失敗（目錄不可建立、權限不足等）；記錄 application
            log 後重新拋出，呼叫端自行決定是否阻斷（不吞例外，
            避免審計失敗卻無痕）。
    """
    detail = detail or {}
    for key, value in detail.items():
        if key in _FORBIDDEN_KEYS:
            raise AuditFieldError(
                f"審計日誌禁止記錄欄位 {key!r}（PHI 或近似 PHI，見模組 docstring 白名單原則）"
            )
        if isinstance(value, str) and len(value) > _MAX_DETAIL_STR_LEN:
            raise AuditFieldError(
                f"審計日誌欄位 {key!r} 字串長度 {len(value)} 超過上限 "
                f"{_MAX_DETAIL_STR_LEN}（長字串是 PHI 夾帶的主要途徑）"
            )

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "caller_id": caller_id,
        "method": method,
        "path": path,
        "status": status,
        "detail": detail,
    }
    line = json.dumps(entry, ensure_ascii=False)

    target = log_path if log_path is not None else AUDIT_LOG_PATH
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as exc:
        _logger.error("寫入審計日誌失敗（path=%s）：%s", target, exc)
        raise

    return line


def read_entries(log_path: str) -> list[dict]:
    """讀回 JSON Lines 審計日誌，逐列解析為 dict。

    Args:
        log_path: 日誌檔路徑。

    Returns:
        依寫入順序排列的 dict 列表；檔案不存在時回傳空 list。
    """
    if not os.path.isfile(log_path):
        return []
    entries: list[dict] = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries
