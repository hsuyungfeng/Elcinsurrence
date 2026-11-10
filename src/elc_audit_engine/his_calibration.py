"""HIS UI Automation Calibration Data Model and Local Storage (Phase 30: D-30-10, D-30-11, D-30-12).

Defines calibration items, per-machine calibration profiles, readiness gate evaluation,
and atomic JSON persistence for Windows agent client workstations.
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SECTIONS = frozenset({
    "S",
    "O",
    "A",
    "P",
    "ICD10",
    "ORDER",
    "MED",
    "PATIENT_ID",
    "SAVE_BUTTON",
})

KINDS = frozenset({
    "writable",
    "save_action",
    "identity_check",
    "advisory_only",
})

STATUSES = frozenset({
    "pending",
    "confirmed",
    "corrected",
    "skipped",
})

_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_ALLOWED_DETECTED_KEYS = frozenset({
    "role",
    "automation_id",
    "name",
    "control_type",
    "window_title",
})


def new_machine_id() -> str:
    """Generate a clean UUID4 machine identifier (not MAC address)."""
    return str(uuid.uuid4())


def default_base_dir() -> Path:
    """Default calibration store directory based on OS platform."""
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            return Path(local_app_data) / "ElcAgent" / "calibration"
        return Path.home() / "AppData" / "Local" / "ElcAgent" / "calibration"
    return Path.home() / ".elcagent" / "calibration"


@dataclass
class CalibrationItem:
    """A single field/action calibration item in the wizard."""

    item_key: str
    section: str
    kind: str
    detected: Dict[str, Any] = field(default_factory=dict)
    suggested: Optional[Dict[str, Any]] = None
    confirmed: Optional[Dict[str, Any]] = None
    status: str = "pending"
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[str] = None

    def __post_init__(self):
        if self.section not in SECTIONS:
            raise ValueError(f"Unknown section '{self.section}', must be one of {sorted(SECTIONS)}")
        if self.kind not in KINDS:
            raise ValueError(f"Unknown kind '{self.kind}', must be one of {sorted(KINDS)}")
        if self.status not in STATUSES:
            raise ValueError(f"Unknown status '{self.status}', must be one of {sorted(STATUSES)}")
        # Strip any value key from detected to prevent PHI leakage
        if self.detected:
            self.detected = {
                k: v for k, v in self.detected.items()
                if k in _ALLOWED_DETECTED_KEYS and k != "value"
            }

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)


@dataclass
class CalibrationProfile:
    """Complete per-machine HIS vendor profile calibration record."""

    vendor_key: str
    machine_id: str
    vendor_version: str = "1.0.0"
    schema_version: int = 1
    items: List[CalibrationItem] = field(default_factory=list)
    readback_test_passed: bool = False
    calibrated_at: Optional[str] = None
    calibrated_by: Optional[str] = None


def selector_for(item: CalibrationItem) -> Optional[Dict[str, Any]]:
    """Return active selector for writing/action.

    Advisory-only items NEVER return a selector (D-30-12).
    """
    if item.kind == "advisory_only":
        return None
    if item.status in ("confirmed", "corrected"):
        return item.confirmed
    return None


def is_ready(profile: CalibrationProfile) -> bool:
    """Evaluate whether calibration is fully ready for live HIS writeback.

    Rule: All items of kind in (writable, save_action, identity_check) must have
    status in (confirmed, corrected) with confirmed != None, AND readback_test_passed == True.
    Advisory items do not block readiness.
    Does NOT read any external 'calibrated' flag.
    """
    if not profile.readback_test_passed:
        return False

    critical_kinds = {"writable", "save_action", "identity_check"}
    has_critical_item = False

    for item in profile.items:
        if item.kind in critical_kinds:
            has_critical_item = True
            if item.status not in ("confirmed", "corrected") or item.confirmed is None:
                return False

    return has_critical_item


def _clean_detected_dict(elem: Any) -> Dict[str, Any]:
    """Extract whitelist fields from UIElementRef or dict, discarding value."""
    if hasattr(elem, "__dict__"):
        raw = elem.__dict__
    elif isinstance(elem, dict):
        raw = elem
    else:
        raw = {}

    cleaned = {}
    for k in _ALLOWED_DETECTED_KEYS:
        if k in raw and raw[k] is not None:
            cleaned[k] = raw[k]
    return cleaned


def build_items_from_detected(
    vendor_key: str,
    detected_elements: List[Any],
) -> List[CalibrationItem]:
    """Generate default calibration items from snapshot elements for a vendor.

    - S/O/A/P: writable, status=pending
    - PATIENT_ID: identity_check, status=pending
    - SAVE_BUTTON: save_action, status=pending (suggested if button matches save keyword)
    - ICD10, ORDER, MED: advisory_only, status=pending
    All value keys are stripped.
    """
    items: List[CalibrationItem] = []

    # Map detected elements by name/id for suggestions
    save_elem = None
    for el in detected_elements:
        cleaned = _clean_detected_dict(el)
        name = str(cleaned.get("name", "")).casefold()
        autoid = str(cleaned.get("automation_id", "")).casefold()
        if "儲存" in name or "save" in name or "save" in autoid or "btn_save" in autoid:
            save_elem = cleaned
            break

    # 1-4. SOAP S/O/A/P (writable)
    for sec, key in [
        ("S", "soap_s.input"),
        ("O", "soap_o.input"),
        ("A", "soap_a.input"),
        ("P", "soap_p.input"),
    ]:
        items.append(
            CalibrationItem(
                item_key=key,
                section=sec,
                kind="writable",
                detected={},
                suggested=None,
                status="pending",
            )
        )

    # 5. PATIENT_ID (identity_check)
    items.append(
        CalibrationItem(
            item_key="patient_id.check",
            section="PATIENT_ID",
            kind="identity_check",
            detected={},
            suggested=None,
            status="pending",
        )
    )

    # 6. SAVE_BUTTON (save_action)
    items.append(
        CalibrationItem(
            item_key="save_button.action",
            section="SAVE_BUTTON",
            kind="save_action",
            detected=save_elem or {},
            suggested={"automation_id": save_elem["automation_id"]} if save_elem and save_elem.get("automation_id") else ({"name": save_elem["name"]} if save_elem and save_elem.get("name") else None),
            status="pending",
        )
    )

    # 7-9. Advisory only items (ICD10, ORDER, MED) (D-30-12)
    for sec, key in [
        ("ICD10", "icd10.advisory"),
        ("ORDER", "order.advisory"),
        ("MED", "med.advisory"),
    ]:
        items.append(
            CalibrationItem(
                item_key=key,
                section=sec,
                kind="advisory_only",
                detected={},
                suggested=None,
                status="pending",
            )
        )

    return items


def _strip_value_keys(obj: Any) -> Any:
    """Recursively ensure no dictionary key is named 'value'."""
    if isinstance(obj, dict):
        return {
            k: _strip_value_keys(v)
            for k, v in obj.items()
            if k != "value"
        }
    if isinstance(obj, list):
        return [_strip_value_keys(elem) for elem in obj]
    return obj


class CalibrationStore:
    """Atomic local storage manager for calibration profiles."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    def path_for(self, vendor_key: str, machine_id: str) -> Path:
        """Validate identifiers and return storage file path."""
        if not _SAFE_IDENTIFIER_PATTERN.match(vendor_key):
            raise ValueError(f"Invalid vendor_key '{vendor_key}': path traversal or invalid characters detected")
        if not _SAFE_IDENTIFIER_PATTERN.match(machine_id):
            raise ValueError(f"Invalid machine_id '{machine_id}': path traversal or invalid characters detected")
        return self.base_dir / f"{vendor_key}-{machine_id}.json"

    def save(self, profile: CalibrationProfile) -> Path:
        """Atomically persist calibration profile to disk using temp file and os.replace."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        target_path = self.path_for(profile.vendor_key, profile.machine_id)
        temp_path = target_path.with_suffix(".tmp")

        raw_dict = asdict(profile)
        # Deep strip any 'value' key
        safe_dict = _strip_value_keys(raw_dict)

        content = json.dumps(safe_dict, ensure_ascii=False, indent=2)
        temp_path.write_text(content, encoding="utf-8")
        os.replace(temp_path, target_path)
        return target_path

    def load(self, vendor_key: str, machine_id: str) -> Optional[CalibrationProfile]:
        """Load calibration profile from disk, verifying schema version."""
        target_path = self.path_for(vendor_key, machine_id)
        if not target_path.exists():
            return None

        content = target_path.read_text(encoding="utf-8")
        data = json.loads(content)

        schema_version = data.get("schema_version")
        if schema_version != 1:
            raise ValueError(f"Unsupported schema_version: {schema_version}")

        items = []
        for raw_item in data.get("items", []):
            items.append(
                CalibrationItem(
                    item_key=raw_item["item_key"],
                    section=raw_item["section"],
                    kind=raw_item["kind"],
                    detected=raw_item.get("detected") or {},
                    suggested=raw_item.get("suggested"),
                    confirmed=raw_item.get("confirmed"),
                    status=raw_item.get("status", "pending"),
                    confirmed_by=raw_item.get("confirmed_by"),
                    confirmed_at=raw_item.get("confirmed_at"),
                )
            )

        return CalibrationProfile(
            vendor_key=data["vendor_key"],
            machine_id=data["machine_id"],
            vendor_version=data.get("vendor_version", "1.0.0"),
            schema_version=schema_version,
            items=items,
            readback_test_passed=bool(data.get("readback_test_passed", False)),
            calibrated_at=data.get("calibrated_at"),
            calibrated_by=data.get("calibrated_by"),
        )
