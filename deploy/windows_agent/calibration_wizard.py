"""HIS UI Automation First-Use Calibration Wizard Controller (Phase 30: D-30-10, D-30-11, D-30-12).

Pure-logic controller guiding step-by-step UI element calibration:
- One item at a time presentation (current item view model)
- Detected properties sanitized (never retains 'value' to prevent PHI leakage)
- Advisory-only items (ICD10, ORDER, MED) are read-only and cannot be confirmed
- Readback test verification with fixed probe string "CALIBRATION-PROBE"
- Ready gate enforcement before persistence
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Ensure src is on sys.path for standalone or subfolder executions
_src_dir = str(Path(__file__).resolve().parent.parent.parent / "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from elc_audit_engine.agent_desktop_bridge import (
    DEFAULT_HIS_PROFILES,
    HISPushAutomator,
    UIElementRef,
)
from elc_audit_engine.his_calibration import (
    CalibrationItem,
    CalibrationProfile,
    CalibrationStore,
    _clean_detected_dict,
    build_items_from_detected,
    is_ready,
)

logger = logging.getLogger("windows_agent.calibration_wizard")

PROBE_TEXT = "CALIBRATION-PROBE"


class NotReadyError(RuntimeError):
    """Raised when finalize() is called on an uncalibrated or incomplete profile."""


class CalibrationWizard:
    """Step-by-step calibration controller for Windows agent HIS setup."""

    def __init__(
        self,
        vendor_key: str,
        app_name: str,
        runner_snapshot_fn: Callable[[str], List[Any]],
        store: CalibrationStore,
        machine_id: str,
        actor_id: str,
        profiles: Optional[Dict[str, Any]] = None,
    ):
        if not actor_id or not str(actor_id).strip():
            raise ValueError("actor_id must be a non-empty string")
        if not vendor_key or not str(vendor_key).strip():
            raise ValueError("vendor_key must be a non-empty string")
        if not machine_id or not str(machine_id).strip():
            raise ValueError("machine_id must be a non-empty string")

        self.vendor_key = vendor_key.strip()
        self.app_name = app_name.strip()
        self.runner_snapshot_fn = runner_snapshot_fn
        self.store = store
        self.machine_id = machine_id.strip()
        self.actor_id = str(actor_id).strip()
        self.profiles = profiles or DEFAULT_HIS_PROFILES

        self.profile: Optional[CalibrationProfile] = None
        self._current_index: int = 0

    @property
    def items(self) -> List[CalibrationItem]:
        return self.profile.items if self.profile else []

    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    def is_done(self) -> bool:
        return self.profile is not None and self._current_index >= len(self.profile.items)

    def start(self) -> None:
        """Capture snapshot and build ordered list of calibration items."""
        elements = self.runner_snapshot_fn(self.app_name)

        # Convert elements if they are dicts into objects supporting attributes for matcher
        wrapped_elements: List[Any] = []
        for el in elements:
            if isinstance(el, dict):
                ref = UIElementRef(
                    ref_id=str(el.get("ref_id", "")),
                    role=str(el.get("role", "")),
                    name=str(el.get("name", "")),
                    automation_id=str(el.get("automation_id", "")),
                    value=str(el.get("value", "")),
                )
                # Preserve extra fields like control_type or window_title
                for extra in ("control_type", "window_title"):
                    if extra in el:
                        setattr(ref, extra, el[extra])
                wrapped_elements.append(ref)
            else:
                wrapped_elements.append(el)

        # Match HIS vendor profile fields
        automator = HISPushAutomator(runner=None, profiles=self.profiles)  # type: ignore[arg-type]
        try:
            matched = automator.match_fields_to_refs(self.vendor_key, wrapped_elements)
        except Exception:
            matched = {}

        # Build initial items with value stripped
        items = build_items_from_detected(self.vendor_key, elements)

        # Map matched elements into S, O, A, P, ICD10 items
        section_to_field = {
            "S": "soap_s",
            "O": "soap_o",
            "A": "soap_a",
            "P": "soap_p",
            "ICD10": "icd10",
        }

        for it in items:
            field_name = section_to_field.get(it.section)
            if field_name and field_name in matched:
                elem = matched[field_name]
                it.detected = _clean_detected_dict(elem)
                aid = getattr(elem, "automation_id", None)
                nm = getattr(elem, "name", None)
                if aid:
                    it.suggested = {"automation_id": aid}
                elif nm:
                    it.suggested = {"name": nm}

        # Check for PATIENT_ID element in snapshot if not yet detected
        patient_item = next((it for it in items if it.section == "PATIENT_ID"), None)
        if patient_item and not patient_item.detected:
            for el in wrapped_elements:
                cd = _clean_detected_dict(el)
                aid = str(cd.get("automation_id", "")).casefold()
                nm = str(cd.get("name", "")).casefold()
                if "patient" in aid or "patient" in nm or "病歷" in nm or "病患" in nm:
                    patient_item.detected = cd
                    if cd.get("automation_id"):
                        patient_item.suggested = {"automation_id": cd["automation_id"]}
                    elif cd.get("name"):
                        patient_item.suggested = {"name": cd["name"]}
                    break

        self.profile = CalibrationProfile(
            vendor_key=self.vendor_key,
            machine_id=self.machine_id,
            items=items,
            readback_test_passed=False,
        )
        self._current_index = 0

    def current(self) -> Optional[CalibrationItem]:
        """Return the current calibration item or None if at the end."""
        if not self.profile or self._current_index >= len(self.profile.items):
            return None
        return self.profile.items[self._current_index]

    def confirm(
        self,
        selector: Optional[Dict[str, Any]] = None,
        actor_id: Optional[str] = None,
    ) -> CalibrationItem:
        """Confirm current item with suggested or specified selector."""
        item = self.current()
        if item is None:
            raise ValueError("No current item to confirm")

        if item.kind == "advisory_only":
            raise ValueError(f"advisory_only item '{item.item_key}' cannot be confirmed as an active selector")

        effective_actor = str(actor_id).strip() if actor_id is not None else self.actor_id
        if not effective_actor:
            raise ValueError("actor_id must be a non-empty string")

        sel = selector if selector is not None else item.suggested
        if not sel:
            raise ValueError(f"No selector available to confirm for '{item.item_key}'; use correct() instead")

        item.confirmed = dict(sel)
        item.status = "confirmed"
        item.confirmed_by = effective_actor
        item.confirmed_at = datetime.now(timezone.utc).isoformat()
        self._current_index += 1
        return item

    def correct(
        self,
        new_selector: Dict[str, Any],
        actor_id: Optional[str] = None,
    ) -> CalibrationItem:
        """Correct current item with a user-supplied selector."""
        item = self.current()
        if item is None:
            raise ValueError("No current item to correct")

        if item.kind == "advisory_only":
            raise ValueError(f"advisory_only item '{item.item_key}' cannot be corrected as an active selector")

        effective_actor = str(actor_id).strip() if actor_id is not None else self.actor_id
        if not effective_actor:
            raise ValueError("actor_id must be a non-empty string")

        if not new_selector or not isinstance(new_selector, dict):
            raise ValueError("new_selector must be a non-empty dictionary")

        item.confirmed = dict(new_selector)
        item.status = "corrected"
        item.confirmed_by = effective_actor
        item.confirmed_at = datetime.now(timezone.utc).isoformat()
        self._current_index += 1
        return item

    def skip(self) -> CalibrationItem:
        """Skip current item without confirming."""
        item = self.current()
        if item is None:
            raise ValueError("No current item to skip")

        item.status = "skipped"
        item.confirmed = None
        self._current_index += 1
        return item

    def readback_test(self, write_and_read_fn: Callable[[str], str]) -> bool:
        """Execute readback verification using fixed probe string (no PHI)."""
        try:
            read_value = write_and_read_fn(PROBE_TEXT)
            passed = bool(read_value == PROBE_TEXT)
        except Exception as exc:
            logger.warning("Readback test probe execution error: %s", exc)
            passed = False

        if self.profile:
            self.profile.readback_test_passed = passed
        return passed

    def finalize(self) -> Path:
        """Persist calibration profile to store after ensuring is_ready is True."""
        if self.profile is None or not is_ready(self.profile):
            raise NotReadyError(
                "Calibration profile is not ready: all writable/action items must be confirmed and readback test passed."
            )

        self.profile.calibrated_at = datetime.now(timezone.utc).isoformat()
        self.profile.calibrated_by = self.actor_id
        return self.store.save(self.profile)
