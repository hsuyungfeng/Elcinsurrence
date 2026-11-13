"""Phase 31: 快捷列與 Server 循環 API 客戶端 (契約 §3, D-31-03, D-30-09).

安全限制：
- 一律帶 operator_key 作為 X-API-Key（具醫師/操作員權限，非 Agent 專用金鑰）
- repr() 絕不顯示 operator_key（T-31-45）
- 日誌絕不輸出金鑰與病歷內容
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("traffic_bar.server_client")


class ServerError(Exception):
    """Server 通訊例外基底。"""


class ServerUnavailable(ServerError):
    """Server 無法連線、逾時或連線中斷。"""


class ServerRejected(ServerError):
    """Server 回應非預期錯誤狀態代碼。"""

    def __init__(self, status: int, message: str = "", body: Optional[Dict[str, Any]] = None):
        super().__init__(f"Server rejected ({status}): {message}")
        self.status = status
        self.message = message
        self.body = body or {}


class CycleServerClient:
    """快捷列呼叫 elc server 循環管理端點之客戶端。"""

    def __init__(self, base_url: str, operator_key: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self._operator_key = (operator_key or "").strip()
        self.timeout = float(timeout)

    def __repr__(self) -> str:
        return f"CycleServerClient(base_url={self.base_url!r}, timeout={self.timeout})"

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        allow_statuses: Tuple[int, ...] = (200, 201),
    ) -> Tuple[int, Dict[str, Any]]:
        url = f"{self.base_url}{path}"
        headers = {
            "X-API-Key": self._operator_key,
        }

        data_bytes: Optional[bytes] = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_bytes = resp.read()
                data_dict: Dict[str, Any] = {}
                if resp_bytes:
                    try:
                        data_dict = json.loads(resp_bytes.decode("utf-8"))
                    except Exception as exc:
                        raise ServerUnavailable(f"解析 Server 回應 JSON 失敗: {exc}")
                return resp.status, data_dict
        except urllib.error.HTTPError as exc:
            err_bytes = exc.read()
            body_dict: Dict[str, Any] = {}
            if err_bytes:
                try:
                    body_dict = json.loads(err_bytes.decode("utf-8"))
                except Exception:
                    body_dict = {}

            if exc.code in allow_statuses:
                return exc.code, body_dict

            msg = str(body_dict.get("message") or body_dict.get("error") or "")
            raise ServerRejected(status=exc.code, message=msg, body=body_dict)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ServerUnavailable(f"無法連線至 Server ({self.base_url}): {exc}")

    def create_cycle(
        self,
        command_id: str,
        machine_id: str,
        room_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """POST /api/cycles - 建立新循環 (契約 §3)."""
        payload: Dict[str, Any] = {
            "command_id": command_id,
            "machine_id": machine_id,
        }
        if room_id:
            payload["room_id"] = room_id
        _, data = self._request("POST", "/api/cycles", body=payload, allow_statuses=(200, 201))
        return data.get("cycle") or data

    def get_active(self, machine_id: str) -> Optional[Dict[str, Any]]:
        """GET /api/cycles?machine_id=... - 取得本機未終結循環 (契約 §3)."""
        query = urllib.parse.urlencode({"machine_id": machine_id})
        _, data = self._request("GET", f"/api/cycles?{query}")
        return data.get("cycle")

    def get_cycle(self, cycle_id: str) -> Dict[str, Any]:
        """GET /api/cycles/{cycle_id} - 取得單一循環狀態 (契約 §3)."""
        _, data = self._request("GET", f"/api/cycles/{urllib.parse.quote(cycle_id)}")
        return data.get("cycle") or data

    def stop(self, cycle_id: str, command_id: str) -> Dict[str, Any]:
        """POST /api/cycles/{cycle_id}/stop - 停止循環錄音 (契約 §3)."""
        _, data = self._request(
            "POST",
            f"/api/cycles/{urllib.parse.quote(cycle_id)}/stop",
            body={"command_id": command_id},
        )
        return data.get("cycle") or data

    def get_draft(self, cycle_id: str, include_transcript: bool = False) -> Dict[str, Any]:
        """GET /api/cycles/{cycle_id}/draft - 取得待確認草稿檢視 (契約 §3)."""
        q = "?include_transcript=1" if include_transcript else ""
        _, data = self._request("GET", f"/api/cycles/{urllib.parse.quote(cycle_id)}/draft{q}")
        return data

    def confirm(
        self,
        cycle_id: str,
        content_hash: str,
        soap: Optional[Dict[str, Any]] = None,
        reviewer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """POST /api/cycles/{cycle_id}/confirm - 醫師確認草稿 (契約 §3)."""
        payload: Dict[str, Any] = {"content_hash": content_hash}
        if soap is not None:
            payload["soap"] = soap
        if reviewer_id is not None:
            payload["reviewer_id"] = reviewer_id
        _, data = self._request(
            "POST",
            f"/api/cycles/{urllib.parse.quote(cycle_id)}/confirm",
            body=payload,
        )
        return data

    def archive(self, cycle_id: str, command_id: str) -> Tuple[int, Dict[str, Any]]:
        """POST /api/cycles/{cycle_id}/archive - 觸發封存與 HIS 寫入 (契約 §3).

        回傳 (status_code, body)：
        - 200: {"status": "archived" | "already_archived"}
        - 202: {"status": "his_pending" | "his_retry_queued"}
        - 409: {"status": "not_confirmed" | "his_failed", "reason": ...}
        """
        return self._request(
            "POST",
            f"/api/cycles/{urllib.parse.quote(cycle_id)}/archive",
            body={"command_id": command_id},
            allow_statuses=(200, 202, 409),
        )

    def abandon(self, cycle_id: str, reason_code: str) -> Dict[str, Any]:
        """POST /api/cycles/{cycle_id}/abandon - 放棄循環 (契約 §3)."""
        _, data = self._request(
            "POST",
            f"/api/cycles/{urllib.parse.quote(cycle_id)}/abandon",
            body={"reason_code": reason_code},
        )
        return data.get("cycle") or data

    def heartbeat(
        self,
        machine_id: str,
        machine_name: Optional[str] = None,
        room_id: Optional[str] = None,
        bar_state: Optional[str] = None,
        soapvoice_state: Optional[str] = None,
        chunks_pending: Optional[int] = None,
        app_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """POST /api/clients/heartbeat - 心跳回報與搭便車通知 (契約 §3)."""
        payload: Dict[str, Any] = {"machine_id": machine_id}
        if machine_name is not None:
            payload["machine_name"] = machine_name
        if room_id is not None:
            payload["room_id"] = room_id
        if bar_state is not None:
            payload["bar_state"] = bar_state
        if soapvoice_state is not None:
            payload["soapvoice_state"] = soapvoice_state
        if chunks_pending is not None:
            payload["chunks_pending"] = chunks_pending
        if app_version is not None:
            payload["app_version"] = app_version

        _, data = self._request("POST", "/api/clients/heartbeat", body=payload)
        return data
