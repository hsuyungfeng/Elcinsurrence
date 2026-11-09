"""Agent-Desktop integration bridge for Windows UIA automation in Elcinsurrence.

Features:
1. Observe–Act–Verify loop for headless HIS writing without stealing focus.
2. 3-Tier Fallback:
   - Tier 1: UIA ValuePattern (set-value @ref)
   - Tier 2: Focus + Clipboard Paste + Restore
   - Tier 3: Floating Copy Card fallback
3. STALE_REF generation handling and automatic snapshot retry.
4. Vendor Profiles (展望 Vision, 耀聖 Yaosheng, 佲格 Minger, 志氏 Chihshi).
5. BridgeQueue HIS_PUSH worker integration with CAS locking.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default HIS Vendor Profiles
DEFAULT_HIS_PROFILES: Dict[str, Any] = {
    "vision": {
        "vendor_name": "展望醫療資訊系統 (Vision HIS)",
        "exe_names": ["VisionHIS.exe", "VisionMain.exe"],
        "calibrated": False,
        "calibrated_at": None,
        "calibrated_by": None,
        "fields": {
            "soap_s": {"automation_id": "txtSubjective", "name": "主訴", "role": "Edit"},
            "soap_o": {"automation_id": "txtObjective", "name": "客觀檢查", "role": "Edit"},
            "soap_a": {"automation_id": "txtAssessment", "name": "臨床評估", "role": "Edit"},
            "soap_p": {"automation_id": "txtPlan", "name": "治療計畫", "role": "Edit"},
            "icd10": {"automation_id": "txtICD10", "name": "主診斷碼", "role": "Edit"},
        },
    },
    "yaosheng": {
        "vendor_name": "耀聖醫療資訊系統 (Yaosheng HIS)",
        "exe_names": ["YaoShengClinic.exe", "YaoMain.exe"],
        "calibrated": False,
        "calibrated_at": None,
        "calibrated_by": None,
        "fields": {
            "soap_s": {"automation_id": "Edit_S", "name": "S", "role": "Edit"},
            "soap_o": {"automation_id": "Edit_O", "name": "O", "role": "Edit"},
            "soap_a": {"automation_id": "Edit_A", "name": "A", "role": "Edit"},
            "soap_p": {"automation_id": "Edit_P", "name": "P", "role": "Edit"},
            "icd10": {"automation_id": "Edit_ICD", "name": "ICD-10", "role": "Edit"},
        },
    },
    "minger": {
        "vendor_name": "佲格門診系統 (Minger HIS)",
        "exe_names": ["MingerClinic.exe"],
        "calibrated": False,
        "calibrated_at": None,
        "calibrated_by": None,
        "fields": {
            "soap_s": {"automation_id": "txtS", "name": "S", "role": "Edit"},
            "soap_o": {"automation_id": "txtO", "name": "O", "role": "Edit"},
            "soap_a": {"automation_id": "txtA", "name": "A", "role": "Edit"},
            "soap_p": {"automation_id": "txtP", "name": "P", "role": "Edit"},
            "icd10": {"automation_id": "txtDiag1", "name": "診斷一", "role": "Edit"},
        },
    },
    "chihshi": {
        "vendor_name": "志氏醫療系統 (Chihshi HIS)",
        "exe_names": ["ChihShiEMR.exe"],
        "calibrated": False,
        "calibrated_at": None,
        "calibrated_by": None,
        "fields": {
            "soap_s": {"automation_id": "RichEdit_S", "name": "主訴紀錄", "role": "Document"},
            "soap_o": {"automation_id": "RichEdit_O", "name": "檢查數據", "role": "Document"},
            "soap_a": {"automation_id": "RichEdit_A", "name": "診斷評估", "role": "Document"},
            "soap_p": {"automation_id": "RichEdit_P", "name": "用藥處置", "role": "Document"},
            "icd10": {"automation_id": "Edit_ICD1", "name": "國際疾病分類碼", "role": "Edit"},
        },
    },
}


class AgentDesktopError(RuntimeError):
    """Base error for agent-desktop bridge."""


class StaleRefError(AgentDesktopError):
    """Raised when accessibility ref has gone stale due to window repaint."""


@dataclass
class UIElementRef:
    ref_id: str
    role: str
    name: str = ""
    automation_id: str = ""
    value: str = ""


@dataclass
class WriteResult:
    field_key: str
    ref_id: str
    target_value: str
    actual_value: str
    verified: bool
    tier_used: str  # "tier1_value_pattern", "tier2_clipboard", "tier3_copy_card"
    retries: int = 0


class AgentDesktopRunner:
    """Interface to agent-desktop CLI / FFI."""

    def __init__(self, executable_path: str = "agent-desktop"):
        self.executable_path = executable_path
        self._mock_driver: Optional[Callable[..., Any]] = None

    def set_mock_driver(self, driver: Callable[..., Any]):
        """Inject mock driver for non-Windows or test environments."""
        self._mock_driver = driver

    def snapshot(self, app_name: str) -> List[UIElementRef]:
        """Capture UIA accessibility tree snapshot and return @ref list."""
        if self._mock_driver:
            return self._mock_driver("snapshot", app_name=app_name)

        cmd = [self.executable_path, "snapshot", "--app", app_name, "-i", "--json"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(res.stdout)
            elements = []
            for item in data.get("elements", []):
                elements.append(
                    UIElementRef(
                        ref_id=item.get("ref", ""),
                        role=item.get("role", "Edit"),
                        name=item.get("name", ""),
                        automation_id=item.get("automation_id", ""),
                        value=item.get("value", ""),
                    )
                )
            return elements
        except Exception as exc:
            raise AgentDesktopError(f"agent-desktop snapshot failed: {exc}") from exc

    def set_value(self, ref_id: str, value: str) -> None:
        """Tier 1: UIA ValuePattern write."""
        if self._mock_driver:
            return self._mock_driver("set_value", ref_id=ref_id, value=value)

        cmd = [self.executable_path, "set-value", ref_id, value]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            if "STALE_REF" in res.stderr:
                raise StaleRefError(f"Element {ref_id} is stale")
            raise AgentDesktopError(f"set-value failed: {res.stderr}")

    def get_value(self, ref_id: str) -> str:
        """Read back value for verification."""
        if self._mock_driver:
            return self._mock_driver("get_value", ref_id=ref_id)

        cmd = [self.executable_path, "get-value", ref_id]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            if "STALE_REF" in res.stderr:
                raise StaleRefError(f"Element {ref_id} is stale")
            raise AgentDesktopError(f"get-value failed: {res.stderr}")
        return res.stdout.strip()

    def set_clipboard_and_paste(self, ref_id: str, value: str) -> None:
        """Tier 2: Focus + Clipboard Paste."""
        if self._mock_driver:
            return self._mock_driver("paste", ref_id=ref_id, value=value)

        cmd = [self.executable_path, "paste-to", ref_id, value]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise AgentDesktopError(f"paste-to failed: {res.stderr}")


class HISPushAutomator:
    """Manages Observe-Act-Verify loop with 3-tier fallback and vendor profiles."""

    def __init__(
        self,
        runner: AgentDesktopRunner,
        profiles: Optional[Dict[str, Any]] = None,
    ):
        self.runner = runner
        self.profiles = profiles or DEFAULT_HIS_PROFILES

    def match_fields_to_refs(
        self,
        vendor_key: str,
        elements: List[UIElementRef],
    ) -> Dict[str, UIElementRef]:
        """Match HIS vendor profile fields to concrete UIElementRef items in snapshot."""
        profile = self.profiles.get(vendor_key)
        if not profile:
            raise ValueError(f"Unknown HIS vendor profile: {vendor_key}")

        field_defs = profile.get("fields", {})
        matched: Dict[str, UIElementRef] = {}

        for field_key, rule in field_defs.items():
            target_id = rule.get("automation_id", "")
            target_name = rule.get("name", "")
            target_role = rule.get("role", "")

            best_elem = None
            for elem in elements:
                if target_role and elem.role != target_role:
                    continue
                if target_id and elem.automation_id == target_id:
                    best_elem = elem
                    break
                if target_name and target_name in elem.name:
                    best_elem = elem
                    break
            if best_elem:
                matched[field_key] = best_elem

        return matched

    def push_case_to_his(
        self,
        vendor_key: str,
        app_name: str,
        case_payload: Dict[str, Any],
        max_retries: int = 2,
        write_soap_only: bool = False,
    ) -> Dict[str, Any]:
        """Execute Observe–Act–Verify loop to push S/O/A/P into HIS.

        When write_soap_only=True (Phase 29 §8.9 standard), only S/O/A/P are written;
        diagnoses, orders, and medications are advisory only and never written to HIS.
        """
        soap = case_payload.get("soap") or {}
        if isinstance(soap, dict):
            s_val = soap.get("s") or soap.get("subjective") or case_payload.get("soap_s") or ""
            o_val = soap.get("o") or soap.get("objective") or case_payload.get("soap_o") or ""
            a_val = soap.get("a") or soap.get("assessment") or case_payload.get("soap_a") or ""
            p_val = soap.get("p") or soap.get("plan") or case_payload.get("soap_p") or ""
        else:
            s_val = case_payload.get("soap_s") or ""
            o_val = case_payload.get("soap_o") or ""
            a_val = case_payload.get("soap_a") or ""
            p_val = case_payload.get("soap_p") or ""

        target_values = {
            "soap_s": s_val,
            "soap_o": o_val,
            "soap_a": a_val,
            "soap_p": p_val,
        }

        # 依 29-DESIGN.md §8.9：只寫 S/O/A/P；非 write_soap_only 時才寫入 icd10（維持舊測試相容）
        eff_write_soap_only = write_soap_only or case_payload.get("write_soap_only", False)
        if not eff_write_soap_only:
            icd_val = case_payload.get("icd10_code") or case_payload.get("icd10") or ""
            if icd_val:
                target_values["icd10"] = icd_val

        results: Dict[str, WriteResult] = {}
        fallback_copy_card: Dict[str, str] = {}

        # 1. OBSERVE: capture accessibility snapshot
        snapshot_elements = self.runner.snapshot(app_name)
        matched_refs = self.match_fields_to_refs(vendor_key, snapshot_elements)

        for f_key, target_text in target_values.items():
            if not target_text:
                continue

            elem = matched_refs.get(f_key)
            if not elem:
                # Field not found in UI, fall back to Tier 3 copy card
                fallback_copy_card[f_key] = target_text
                results[f_key] = WriteResult(
                    field_key=f_key,
                    ref_id="",
                    target_value=target_text,
                    actual_value="",
                    verified=False,
                    tier_used="tier3_copy_card",
                )
                continue

            # ACT with 3-tier fallback and STALE_REF retry
            written = False
            tier_used = "tier1_value_pattern"
            retries = 0

            for _attempt in range(max_retries + 1):
                try:
                    # Tier 1: ValuePattern write
                    self.runner.set_value(elem.ref_id, target_text)
                    written = True
                    tier_used = "tier1_value_pattern"
                    break
                except StaleRefError:
                    # Stale ref: refresh snapshot and re-match
                    retries += 1
                    logger.info("STALE_REF encountered for %s. Refreshing snapshot...", f_key)
                    snapshot_elements = self.runner.snapshot(app_name)
                    matched_refs = self.match_fields_to_refs(vendor_key, snapshot_elements)
                    elem = matched_refs.get(f_key)
                    if not elem:
                        break
                except Exception as exc:
                    logger.warning("Tier 1 set_value failed for %s: %s. Trying Tier 2...", f_key, exc)
                    try:
                        # Tier 2: Focus + Clipboard Paste
                        self.runner.set_clipboard_and_paste(elem.ref_id, target_text)
                        written = True
                        tier_used = "tier2_clipboard"
                        break
                    except Exception as paste_exc:
                        logger.warning("Tier 2 paste failed for %s: %s", f_key, paste_exc)
                        break

            if not written:
                # Tier 3 Fallback
                fallback_copy_card[f_key] = target_text
                results[f_key] = WriteResult(
                    field_key=f_key,
                    ref_id=elem.ref_id if elem else "",
                    target_value=target_text,
                    actual_value="",
                    verified=False,
                    tier_used="tier3_copy_card",
                    retries=retries,
                )
                continue

            # VERIFY: Read back value
            actual = ""
            verified = False
            try:
                actual = self.runner.get_value(elem.ref_id)
                verified = (actual.strip() == target_text.strip()) or (target_text.strip() in actual)
            except Exception as read_exc:
                logger.warning("Verify read failed for %s: %s", f_key, read_exc)

            results[f_key] = WriteResult(
                field_key=f_key,
                ref_id=elem.ref_id,
                target_value=target_text,
                actual_value=actual,
                verified=verified,
                tier_used=tier_used,
                retries=retries,
            )

        has_fallback = bool(fallback_copy_card)
        all_ok = (not has_fallback) and bool(results) and all(r.verified for r in results.values())

        return {
            "status": "success" if all_ok else "partial",
            "vendor_key": vendor_key,
            "app_name": app_name,
            "results": {k: vars(v) for k, v in results.items()},
            "fallback_copy_card": fallback_copy_card,
        }


def process_his_push_job(
    store,
    job_id: str,
    automator: HISPushAutomator,
    app_name: str = "VisionHIS.exe",
    vendor_key: str = "vision",
) -> Dict[str, Any]:
    """Process a single BridgeQueue job with s_type_code="HIS_PUSH" under CAS protection."""
    from elc_audit_engine.bridge_queue import get_job, report_status

    job = get_job(store, job_id)
    if not job:
        raise ValueError(f"Job not found: {job_id}")

    if job.get("s_type_code") != "HIS_PUSH":
        raise ValueError(f"Job {job_id} has s_type_code={job.get('s_type_code')}, expected HIS_PUSH")

    # Step 1: Transition PENDING -> SENDING via CAS
    try:
        report_status(store, job_id, status="SENDING", expected_status="PENDING")
    except Exception as exc:
        raise AgentDesktopError(f"CAS lock failed for job {job_id}: {exc}") from exc

    # Step 2: Push to HIS
    payload = job.get("extra_payload") or job.get("payload") or {}
    try:
        push_summary = automator.push_case_to_his(
            vendor_key=vendor_key,
            app_name=app_name,
            case_payload=payload,
        )
        final_status = "SUCCESS" if push_summary.get("status") == "success" else "FAILED"
        report_status(store, job_id, status=final_status, expected_status="SENDING")
        return push_summary
    except Exception as exc:
        logger.exception("HIS Push failed for job %s: %s", job_id, exc)
        try:
            report_status(store, job_id, status="FAILED", expected_status="SENDING")
        except Exception:
            pass
        raise
