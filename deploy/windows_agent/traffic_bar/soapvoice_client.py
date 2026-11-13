"""Phase 31: 快捷列與 SoapVoice 本機控制通道客戶端 (契約 §1, D-31-03).

安全限制：
- 僅允許連線 127.0.0.1 或 localhost（防 DNS rebinding，T-31-44）
- 請求一律帶 Host 標頭與 X-Local-Token
- 日誌絕不記錄 token（T-31-45）
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger("traffic_bar.soapvoice_client")

_ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})


def default_token_path() -> Path:
    """依契約 §1 取得平台預設的 control_token 檔案路徑。"""
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "ElcSoapVoice" / "control_token"
    return Path.home() / ".local" / "share" / "ElcSoapVoice" / "control_token"


class IpcError(Exception):
    """本機 IPC 例外基底。"""


class IpcUnavailable(IpcError):
    """SoapVoice 本機控制服務無法連線或逾時。"""


class IpcRejected(IpcError):
    """SoapVoice 回應非 2xx 狀態代碼。"""

    def __init__(
        self,
        status: int,
        error_code: str = "",
        message: str = "",
        body: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(f"IPC rejected ({status}): {error_code} - {message}")
        self.status = status
        self.error_code = error_code
        self.message = message
        self.body = body or {}


class SoapVoiceControlClient:
    """快捷列端呼叫 SoapVoice 本機控制服務的客戶端。"""

    def __init__(
        self,
        port: int = 18765,
        host: str = "127.0.0.1",
        token: Optional[str] = None,
        token_path: Optional[Path] = None,
        timeout: float = 2.0,
    ):
        h = host.strip().lower()
        if h not in _ALLOWED_HOSTS:
            raise ValueError(f"SoapVoice 控制通道僅允許連線 127.0.0.1 或 localhost，不允許：{host!r}")

        self.host = h
        self.port = int(port)
        self.timeout = float(timeout)
        self.token_path = token_path or default_token_path()

        if token is not None:
            self._token: Optional[str] = token.strip()
        else:
            self._token = self._read_token_file()

    def _read_token_file(self) -> Optional[str]:
        try:
            if self.token_path.is_file():
                return self.token_path.read_text(encoding="utf-8").strip()
        except Exception as exc:
            logger.debug("讀取控制 token 失敗: %s", exc)
        return None

    def refresh_token(self) -> None:
        """重新自檔案讀取 token。"""
        self._token = self._read_token_file()

    @property
    def has_token(self) -> bool:
        return bool(self._token)

    def _request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._token:
            # 嘗試重新載入一次
            self.refresh_token()
        if not self._token:
            raise IpcUnavailable("找不到 SoapVoice 控制 token")

        url = f"http://{self.host}:{self.port}{path}"
        headers = {
            "Host": f"{self.host}:{self.port}",
            "X-Local-Token": self._token,
        }

        data_bytes: Optional[bytes] = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_bytes = resp.read()
                if not resp_bytes:
                    return {}
                try:
                    return json.loads(resp_bytes.decode("utf-8"))
                except Exception as exc:
                    raise IpcUnavailable(f"解析 SoapVoice 回應 JSON 失敗: {exc}")
        except urllib.error.HTTPError as exc:
            err_bytes = exc.read()
            body_dict: Dict[str, Any] = {}
            if err_bytes:
                try:
                    body_dict = json.loads(err_bytes.decode("utf-8"))
                except Exception:
                    body_dict = {}
            error_code = str(body_dict.get("error", ""))
            message = str(body_dict.get("message", ""))
            raise IpcRejected(status=exc.code, error_code=error_code, message=message, body=body_dict)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise IpcUnavailable(f"無法連線至 SoapVoice (http://{self.host}:{self.port}): {exc}")

    def status(self) -> Dict[str, Any]:
        """GET /control/v1/status - 查詢 SoapVoice 狀態 (契約 §1)."""
        return self._request("GET", "/control/v1/status")

    def start(self, command_id: str, cycle_id: str) -> Dict[str, Any]:
        """POST /control/v1/start - 開始錄音 (契約 §1)."""
        return self._request(
            "POST",
            "/control/v1/start",
            body={"command_id": command_id, "cycle_id": cycle_id},
        )

    def stop(self, command_id: str, cycle_id: str) -> Dict[str, Any]:
        """POST /control/v1/stop - 停止錄音 (契約 §1)."""
        return self._request(
            "POST",
            "/control/v1/stop",
            body={"command_id": command_id, "cycle_id": cycle_id},
        )

    def archived(self, cycle_id: str) -> Dict[str, Any]:
        """POST /control/v1/archived - 通知已封存 (契約 §1)."""
        return self._request(
            "POST",
            "/control/v1/archived",
            body={"cycle_id": cycle_id},
        )
