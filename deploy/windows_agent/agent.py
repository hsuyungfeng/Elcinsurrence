"""Windows HIS Writeback Agent (Phase 29: §7, §8).

Deploys on a Windows client machine in the local clinic network.
Features:
1. Pull-based job polling (no fixed IP required for Windows machine).
2. Periodic heartbeat reporting (POST /api/agent/heartbeat).
3. CAS-protected job claim (PENDING -> SENDING).
4. Patient mismatch check before writing.
5. Vendor profile calibration enforcement (§7.4).
6. Observe–Act–Verify loop via AgentDesktopRunner / HISPushAutomator (§8.3).
7. Readback verification against content_hash (§8.4).
8. Status reporting (SUCCESS / FAILED with reason code) (§8.5).
9. Strict PHI protection: NEVER logs raw SOAP text into application logs.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from elc_audit_engine.agent_desktop_bridge import (
    AgentDesktopError,
    AgentDesktopRunner,
    HISPushAutomator,
    StaleRefError,
)
from elc_audit_engine.case_store.soap_draft_states import (
    canonical_soap_text,
    compute_soap_content_hash,
)

logger = logging.getLogger("windows_agent")


class UncalibratedVendorProfileError(RuntimeError):
    """Raised when an uncalibrated vendor profile is used for real HIS writeback."""


@dataclass
class AgentConfig:
    server_url: str
    agent_id: str
    agent_key: str
    vendor_key: str = "vision"
    app_name: str = "VisionHIS.exe"
    calibrated: bool = False
    poll_interval: float = 5.0
    heartbeat_interval: float = 30.0
    version: str = "1.0.0"


class DefaultHttpClient:
    """Lightweight HTTP client using Python standard library urllib."""

    def __init__(self, server_url: str, agent_key: str, timeout: float = 10.0):
        self.server_url = server_url.rstrip("/")
        self.agent_key = agent_key
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> tuple[int, Dict[str, Any]]:
        url = f"{self.server_url}{path}"
        headers = {
            "X-API-Key": self.agent_key,
            "User-Agent": "ElcWindowsAgent/1.0",
        }
        data_bytes = None
        if json_body is not None:
            data_bytes = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status = resp.status
                raw = resp.read().decode("utf-8")
                return status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                data = json.loads(raw)
            except Exception:
                data = {"message": raw}
            return exc.code, data
        except Exception as exc:
            logger.error("HTTP request error to %s: %s", path, exc)
            return 599, {"error": str(exc)}


class WindowsAgent:
    """Client runner executed on Windows client machines to push approved SOAP drafts into HIS."""

    def __init__(
        self,
        config: AgentConfig,
        automator: Optional[HISPushAutomator] = None,
        http_client: Any = None,
        current_patient_getter: Optional[Callable[[], Optional[str]]] = None,
        allow_uncalibrated: bool = False,
    ):
        self.config = config
        self.automator = automator or HISPushAutomator(runner=AgentDesktopRunner())
        self.http_client = http_client or DefaultHttpClient(
            server_url=config.server_url,
            agent_key=config.agent_key,
        )
        self.current_patient_getter = current_patient_getter
        self.allow_uncalibrated = allow_uncalibrated
        self._last_heartbeat_time = 0.0

        # §7.4: Agent 啟動時檢查並拒絕未校準的廠商設定
        self.validate_startup_calibration()

    def validate_startup_calibration(self) -> None:
        """Validate vendor profile calibration at agent startup (§7.4)."""
        is_calibrated = self.config.calibrated
        if not is_calibrated and hasattr(self.automator, "profiles"):
            prof = self.automator.profiles.get(self.config.vendor_key)
            if prof and prof.get("calibrated"):
                is_calibrated = True

        if not is_calibrated and not self.allow_uncalibrated:
            raise UncalibratedVendorProfileError(
                f"HIS 廠商設定檔 '{self.config.vendor_key}' 尚未於現場完成校準，"
                f"依 29-DESIGN.md §7.4 規範禁止啟動並執行正式寫入。"
                f"如為測試環境，請顯式設定 allow_uncalibrated=True 或 config.calibrated=True。"
            )

    def send_heartbeat(self) -> bool:
        """Report agent heartbeat to the central server."""
        payload = {
            "agent_id": self.config.agent_id,
            "version": self.config.version,
            "his_vendor": self.config.vendor_key,
            "his_status": "READY",
            "meta": {
                "app_name": self.config.app_name,
                "calibrated": self.config.calibrated,
            },
        }
        status, data = self.http_client.request("POST", "/api/agent/heartbeat", payload)
        if status == 200:
            self._last_heartbeat_time = time.time()
            return True
        logger.warning("Heartbeat failed with HTTP %d: %s", status, data.get("message"))
        return False

    def poll_pending_jobs(self) -> List[Dict[str, Any]]:
        """Fetch pending HIS_PUSH jobs from bridge queue."""
        status, data = self.http_client.request(
            "GET", "/api/bridge/jobs/pending?sTypeCode=HIS_PUSH"
        )
        if status == 200:
            return data.get("jobs", [])
        logger.warning("Polling failed with HTTP %d: %s", status, data.get("message"))
        return []

    def claim_job(self, job_id: str) -> bool:
        """Attempt to claim job with CAS (PENDING -> SENDING)."""
        status, _ = self.http_client.request(
            "POST",
            f"/api/bridge/jobs/{job_id}/status",
            {"status": "SENDING", "expected_status": "PENDING"},
        )
        return status == 200

    def report_job_status(
        self,
        job_id: str,
        status: str,
        failure_reason: Optional[str] = None,
    ) -> bool:
        """Report execution status back to server."""
        body: Dict[str, Any] = {
            "status": status,
            "expected_status": "SENDING",
        }
        if failure_reason:
            body["reason"] = failure_reason

        http_status, _ = self.http_client.request(
            "POST",
            f"/api/bridge/jobs/{job_id}/status",
            body,
        )
        return http_status == 200

    def execute_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single claimed HIS_PUSH job under Observe–Act–Verify loop."""
        job_id = job.get("job_id", "")
        payload = job.get("extra_payload") or job.get("payload") or {}
        case_id = payload.get("case_id", "")
        expected_hash = payload.get("content_hash", "")
        raw_soap = payload.get("soap") or {}

        logger.info(
            "Executing HIS_PUSH job_id=%s case_id=%s content_hash=%s",
            job_id,
            case_id,
            expected_hash,
        )

        # 1. Check vendor calibration (§7.4)
        if not self.config.calibrated:
            reason = "uncalibrated_profile"
            logger.error("Vendor profile %s is not calibrated! Rejecting writeback.", self.config.vendor_key)
            self.report_job_status(job_id, "FAILED", failure_reason=reason)
            return {"status": "failed", "job_id": job_id, "reason": reason}

        # 2. Patient match verification (§8.2)
        if self.current_patient_getter is not None:
            active_case_id = self.current_patient_getter()
            if active_case_id and active_case_id != case_id:
                reason = "patient_mismatch"
                logger.error(
                    "Patient mismatch! Expected case_id=%s, currently active in HIS=%s",
                    case_id,
                    active_case_id,
                )
                self.report_job_status(job_id, "FAILED", failure_reason=reason)
                return {"status": "failed", "job_id": job_id, "reason": reason}

        # 3. Write via Automator (§8.3, §8.9 只寫 S/O/A/P)
        try:
            push_summary = self.automator.push_case_to_his(
                vendor_key=self.config.vendor_key,
                app_name=self.config.app_name,
                case_payload=payload,
                write_soap_only=True,
            )
        except (StaleRefError, AgentDesktopError) as exc:
            reason = "ui_error"
            logger.error("UI error during writeback for job_id=%s: %s", job_id, exc)
            self.report_job_status(job_id, "FAILED", failure_reason=reason)
            return {"status": "failed", "job_id": job_id, "reason": reason}
        except Exception as exc:
            reason = "ui_error"
            logger.exception("Unexpected error during writeback: %s", exc)
            self.report_job_status(job_id, "FAILED", failure_reason=reason)
            return {"status": "failed", "job_id": job_id, "reason": reason}

        # 4. Readback verification (§8.4)
        # Extract read back actual values from each field
        res_map = push_summary.get("results") or {}
        readback_soap = {
            "s": (res_map.get("soap_s") or {}).get("actual_value", ""),
            "o": (res_map.get("soap_o") or {}).get("actual_value", ""),
            "a": (res_map.get("soap_a") or {}).get("actual_value", ""),
            "p": (res_map.get("soap_p") or {}).get("actual_value", ""),
        }

        readback_hash = compute_soap_content_hash(readback_soap)
        if readback_hash != expected_hash or push_summary.get("status") != "success":
            reason = "readback_mismatch"
            logger.error(
                "Readback hash mismatch! expected=%s readback=%s summary_status=%s",
                expected_hash,
                readback_hash,
                push_summary.get("status"),
            )
            self.report_job_status(job_id, "FAILED", failure_reason=reason)
            return {"status": "failed", "job_id": job_id, "reason": reason}

        # 5. Report SUCCESS (§8.5)
        self.report_job_status(job_id, "SUCCESS")
        logger.info("Successfully pushed and verified job_id=%s case_id=%s", job_id, case_id)
        return {"status": "success", "job_id": job_id, "readback_hash": readback_hash}

    def run_once(self) -> Optional[Dict[str, Any]]:
        """Perform one polling and execution cycle. Concurrency is fixed at 1 (§8.8)."""
        # Check heartbeat
        now = time.time()
        if now - self._last_heartbeat_time >= self.config.heartbeat_interval:
            self.send_heartbeat()

        jobs = self.poll_pending_jobs()
        if not jobs:
            return None

        # Take the first job and attempt claim
        for candidate in jobs:
            job_id = candidate.get("job_id")
            if not job_id:
                continue
            if self.claim_job(job_id):
                return self.execute_job(candidate)

        return None
