"""API key 服務間認證（Phase 9-01：HIS 呼叫方身分辨識）。

本服務會接觸病歷資料（SOAP 全文、病歷號、患者姓名），呼叫方是 HIS 服務
而非瀏覽器使用者，故採 **API key** 而非 JWT／mTLS／session（2026-08-05
使用者裁示，見 09-CONTEXT.md）。

設計要點：

- key 表格式 `ELC_API_KEYS="his1:key1,his2:key2"`：**多呼叫方識別**，
  讓審計日誌能記錄「是誰調閱了病歷」，而非只知道「有人用了某把 key」。
- 比對一律用 `hmac.compare_digest`（constant-time），**禁止 `==`**——
  逐字元比對在錯誤發生的位置提前 return 會洩漏時序側通道資訊。
- `ELC_API_KEYS` 未設定或格式錯誤時 **fail-fast**：本模組不提供任何
  「降級為無認證」的路徑，服務啟動即失敗，不得以無認證狀態運行。
- caller_id 校驗沿用 `safe_paths.safe_filename`（校驗後拒絕，不清洗）——
  caller_id 之後會流入審計日誌與（未來）檔名情境，同一防線需一致套用。
"""

from __future__ import annotations

import functools
import hmac
import os

from flask import g, request

from elc_audit_engine.safe_paths import UnsafeIdentifierError, safe_filename

#: HTTP header 名稱：呼叫方在此攜帶 API key。
API_KEY_HEADER = "X-API-Key"

#: 環境變數名稱：`his1:key1,his2:key2` 格式的呼叫方↔key 對照表。
ENV_API_KEYS = "ELC_API_KEYS"

#: 弱 key 門檻：短於此長度視為不安全，拒絕啟動（而非警告後放行）。
_MIN_KEY_LEN = 16

#: 認證失敗的固定訊息（不得依情境變化，避免洩漏「key 存在但錯誤」等細節）。
_AUTH_FAIL_MESSAGE = "認證失敗：缺少或無效的 API key"

#: dummy 比對用的固定字串，長度需 >= _MIN_KEY_LEN 以模擬正常比對耗時。
_DUMMY_KEY = "0" * _MIN_KEY_LEN


class AuthConfigError(RuntimeError):
    """認證設定缺失或格式錯誤（啟動期 fail-fast 用）。

    出現此例外時服務**不得**以無認證狀態繼續啟動——本服務會接觸病歷
    資料，設定缺失等同於「無認證對外開放」，比啟動失敗更危險。
    """


class AuthenticationError(Exception):
    """單次請求認證失敗（缺 header 或 key 不在表內）。

    訊息固定為 `_AUTH_FAIL_MESSAGE`，不因「缺 header」與「錯誤 key」而
    不同——差異化訊息本身就是一種資訊洩漏。與「查無資料」的回應必須
    可區分（此例外一律轉為 401，而非 200 帶空結果或 404）。
    """

    def __init__(self, message: str = _AUTH_FAIL_MESSAGE):
        super().__init__(message)
        self.message = message


def parse_api_keys(raw: str) -> dict[str, str]:
    """解析 `ELC_API_KEYS` 原始字串，回傳 `{key: caller_id}`。

    以 key 為字典鍵（而非 caller_id）：查詢方向永遠是「拿到呼叫方
    出示的 key，找出是誰」，用 key 當鍵可避免每次認證都要線性掃描
    caller_id（雖然目前 resolve_caller 仍會走完整迴圈，見該函式
    docstring 的 constant-time 理由）。

    格式：以 `,` 切分項目，每項再以第一個 `:` 切分為
    `caller_id:key`（key 本身若含 `:` 也沒問題，只切第一個）。

    Args:
        raw: `ELC_API_KEYS` 環境變數原始值。

    Returns:
        `{key: caller_id}` 對照表。

    Raises:
        AuthConfigError: 格式錯誤、caller_id／key 為空、key 過短、
            key 重複、caller_id 含不安全字元，或解析結果為空。
    """
    entries = [item.strip() for item in raw.split(",") if item.strip()]
    result: dict[str, str] = {}
    for entry in entries:
        if ":" not in entry:
            raise AuthConfigError(
                f"{ENV_API_KEYS} 格式錯誤：項目 {entry!r} 缺少 ':' 分隔 caller_id 與 key"
            )
        caller_id, key = entry.split(":", 1)
        caller_id = caller_id.strip()
        key = key.strip()
        if not caller_id:
            raise AuthConfigError(f"{ENV_API_KEYS} 格式錯誤：項目 {entry!r} 的 caller_id 為空")
        if not key:
            raise AuthConfigError(f"{ENV_API_KEYS} 格式錯誤：呼叫方 {caller_id!r} 的 key 為空")
        if len(key) < _MIN_KEY_LEN:
            # 訊息不得回顯 key 本體——即使是弱 key，也不該被記錄或顯示。
            raise AuthConfigError(
                f"{ENV_API_KEYS} 設定錯誤：呼叫方 {caller_id!r} 的 key 長度須 >= "
                f"{_MIN_KEY_LEN} 字元"
            )
        try:
            caller_id = safe_filename(caller_id, "caller_id")
        except UnsafeIdentifierError as exc:
            raise AuthConfigError(
                f"{ENV_API_KEYS} 設定錯誤：caller_id {caller_id!r} 含不允許的字元"
            ) from exc
        if key in result:
            raise AuthConfigError(f"{ENV_API_KEYS} 設定錯誤：key 重複出現（呼叫方 {caller_id!r}）")
        result[key] = caller_id

    if not result:
        raise AuthConfigError(f"{ENV_API_KEYS} 設定錯誤：未解析出任何有效的呼叫方/key 配對")
    return result


def load_api_keys(raw: str | None = None) -> dict[str, str]:
    """載入並解析 API key 表；`raw` 為 None 時讀環境變數。

    Args:
        raw: 直接提供的原始字串（測試用）；None 時讀
            `os.environ.get(ENV_API_KEYS)`。

    Returns:
        `{key: caller_id}` 對照表（委派 `parse_api_keys`）。

    Raises:
        AuthConfigError: 環境變數未設定／為空字串，或格式錯誤
            （fail-fast：本服務會接觸病歷資料，不得以無認證狀態啟動）。
    """
    if raw is None:
        raw = os.environ.get(ENV_API_KEYS)
    if not raw:
        raise AuthConfigError(
            f"環境變數 {ENV_API_KEYS} 未設定：本服務會接觸病歷資料，"
            "不得以無認證狀態啟動"
        )
    return parse_api_keys(raw)


def resolve_caller(presented_key: str | None, keys: dict[str, str]) -> str:
    """以 constant-time 比對找出 `presented_key` 對應的 caller_id。

    **禁止使用 `==` 比對 key**（時序側通道）：`==` 在 CPython 對字串
    是逐字元比對且提前 return，比對耗時會隨「前綴相符長度」變化，
    攻擊者可藉此逐字元猜出正確 key。改用 `hmac.compare_digest`。

    **無論命中與否都走完全部 key 的比對迴圈**，不可 early-return——
    提前結束迴圈本身就會洩漏「第幾把 key 比對到相符」的資訊。

    `presented_key` 為 None 或空字串時仍執行一次 dummy `compare_digest`
    才拋錯，避免「完全沒帶 header」比「帶了錯的 key」耗時明顯更短。

    Args:
        presented_key: 呼叫方於 `X-API-Key` header 帶的值。
        keys: `load_api_keys` 回傳的 `{key: caller_id}` 對照表。

    Returns:
        命中的 caller_id。

    Raises:
        AuthenticationError: 未帶 key 或 key 不在表內。
    """
    candidate = (presented_key or "").encode("utf-8")
    matched_caller_id: str | None = None
    for key, caller_id in keys.items():
        # 兩側皆 encode 後比對；即使 candidate 為空仍執行，維持迴圈長度
        # 與時間開銷跟「有帶但錯誤的 key」一致。
        is_match = hmac.compare_digest(candidate, key.encode("utf-8"))
        if is_match and presented_key:
            matched_caller_id = caller_id
        # 不 break、不 continue 提前跳過——確保迴圈耗時只取決於 keys 數量。

    if not presented_key:
        # 缺 header 仍執行一次額外 dummy 比對，讓「缺 header」與「錯 key」
        # 的耗時輪廓一致（兩者都至少做過一次 compare_digest）。
        hmac.compare_digest(_DUMMY_KEY.encode("utf-8"), _DUMMY_KEY.encode("utf-8"))
        raise AuthenticationError()

    if matched_caller_id is None:
        raise AuthenticationError()
    return matched_caller_id


def require_api_key(view_func):
    """Flask view decorator：強制 `X-API-Key` 認證。

    key 表由 `flask.current_app.config["ELC_API_KEYS"]` 取得（由
    server 啟動時經 `load_api_keys()` 注入一次，避免每次請求重讀
    環境變數）。成功時把 caller_id 寫入 `flask.g.caller_id` 供
    審計日誌使用；失敗時讓 `AuthenticationError` 傳播，由呼叫端的
    Flask errorhandler 轉為 401。

    本專案實際採用 `before_request` 統一強制（見 server.py，理由是
    「新增端點預設受保護」），此 decorator 保留供未來 blueprint 或
    需要單一端點顯式標註認證的場景使用。
    """

    @functools.wraps(view_func)
    def wrapper(*args, **kwargs):
        from flask import current_app

        keys = current_app.config["ELC_API_KEYS"]
        presented_key = request.headers.get(API_KEY_HEADER)
        caller_id = resolve_caller(presented_key, keys)
        g.caller_id = caller_id
        return view_func(*args, **kwargs)

    return wrapper
