"""Physician SOAP Review Client & View Model (Phase 30: D-30-03, D-30-12).

Pure logic client for desktop review window:
- ReviewClient communicates with central server using operator API key.
- build_review_view_model formats draft into editable SOAP sections and read-only advisory sidebar.
- DraftChangedError raised on HTTP 409 (content_hash mismatch) preventing silent overwrites.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("windows_agent.review_client")


class DraftChangedError(Exception):
    """Raised when a draft's content_hash or state has changed concurrently (HTTP 409)."""


class DefaultReviewHttp:
    """Lightweight urllib client utilizing operator API key."""

    def __init__(self, operator_key: str, timeout: float = 10.0):
        self.operator_key = operator_key
        self.timeout = timeout

    def request(
        self,
        base_url: str,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        url = f"{base_url.rstrip('/')}{path}"
        headers = {
            "X-API-Key": self.operator_key,
            "User-Agent": "ElcReviewClient/1.0",
        }
        data_bytes = None
        if json_body is not None:
            data_bytes = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                data = json.loads(raw)
            except Exception:
                data = {"message": raw}
            return exc.code, data
        except Exception as exc:
            return 599, {"error": str(exc)}


class ReviewClient:
    """API client for the physician review window."""

    def __init__(
        self,
        base_url: str,
        operator_key: str,
        http: Any = None,
    ):
        if not operator_key or not str(operator_key).strip():
            raise ValueError("operator_key must not be empty")

        self.base_url = base_url.rstrip("/")
        self.operator_key = operator_key
        self.http = http or DefaultReviewHttp(operator_key)

    def list_pending(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch drafts in validated state waiting for physician review."""
        status, data = self.http.request(self.base_url, "GET", f"/api/soap/drafts/pending-review?limit={limit}")
        if status != 200:
            logger.warning("Failed to list pending drafts: HTTP %d", status)
            return []
        return data.get("drafts", [])

    def get_draft(self, draft_id: str) -> Dict[str, Any]:
        """Fetch draft details."""
        status, data = self.http.request(self.base_url, "GET", f"/api/soap/drafts/{draft_id}")
        if status != 200:
            raise RuntimeError(f"Failed to fetch draft {draft_id}: HTTP {status}")
        return data.get("draft", {})

    def approve(self, draft_id: str, content_hash: str) -> Dict[str, Any]:
        """Physician approves draft to queue for HIS push."""
        logger.info("Approving draft_id=%s with content_hash=%s", draft_id, content_hash)
        body = {"content_hash": content_hash}
        status, data = self.http.request(self.base_url, "POST", f"/api/soap/drafts/{draft_id}/approve", json_body=body)

        if status == 409:
            raise DraftChangedError(f"Draft {draft_id} content has changed or already modified")
        if status not in (200, 201):
            raise RuntimeError(f"Approval failed for draft {draft_id}: HTTP {status}")

        return data

    def edit(self, draft_id: str, soap: Dict[str, str], base_content_hash: str) -> Dict[str, Any]:
        """Physician edits draft, incrementing version."""
        logger.info("Editing draft_id=%s base_hash=%s", draft_id, base_content_hash)
        body = {
            "soap": soap,
            "base_content_hash": base_content_hash,
        }
        status, data = self.http.request(self.base_url, "POST", f"/api/soap/drafts/{draft_id}/edit", json_body=body)

        if status == 409:
            raise DraftChangedError(f"Draft {draft_id} modified concurrently during edit")
        if status not in (200, 201):
            raise RuntimeError(f"Edit failed for draft {draft_id}: HTTP {status}")

        return data

    def reject(self, draft_id: str, reason_code: str, reason_text: str = "") -> Dict[str, Any]:
        """Physician rejects draft."""
        logger.info("Rejecting draft_id=%s reason_code=%s", draft_id, reason_code)
        body = {
            "reason_code": reason_code,
            "reason_text": reason_text,
        }
        status, data = self.http.request(self.base_url, "POST", f"/api/soap/drafts/{draft_id}/reject", json_body=body)
        if status not in (200, 201):
            raise RuntimeError(f"Reject failed for draft {draft_id}: HTTP {status}")
        return data


def build_review_view_model(draft_json: Dict[str, Any]) -> Dict[str, Any]:
    """Transform draft JSON into view model for review UI.

    S/O/A/P fields are marked writable=True.
    Advisory fields (ICD-10, orders, meds) are marked writable=False, read_only=True.
    """
    soap = draft_json.get("soap") or {}
    advisory = draft_json.get("advisory") or {}

    return {
        "draft_id": draft_json.get("draft_id", ""),
        "version": draft_json.get("version", 1),
        "content_hash": draft_json.get("content_hash", ""),
        "patient_ref": draft_json.get("patient_ref", ""),
        "editors": {
            "s": {"value": soap.get("s", ""), "writable": True, "read_only": False},
            "o": {"value": soap.get("o", ""), "writable": True, "read_only": False},
            "a": {"value": soap.get("a", ""), "writable": True, "read_only": False},
            "p": {"value": soap.get("p", ""), "writable": True, "read_only": False},
        },
        "advisory": {
            "icd10": {
                "items": advisory.get("icd10_suggestions", []),
                "writable": False,
                "read_only": True,
            },
            "order": {
                "items": advisory.get("order_suggestions", []),
                "writable": False,
                "read_only": True,
            },
            "med": {
                "items": advisory.get("med_suggestions", []),
                "writable": False,
                "read_only": True,
            },
            "read_only": True,
        },
    }
