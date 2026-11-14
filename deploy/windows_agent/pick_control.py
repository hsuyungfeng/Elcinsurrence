"""Pure-logic and cursor coordinate picking for HIS controls (Phase 32 Plan 32-04, B7)."""

from __future__ import annotations

import logging
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("windows_agent.pick_control")


def _get_val(elem: Any, key: str, default: Any = None) -> Any:
    if isinstance(elem, dict):
        return elem.get(key, default)
    return getattr(elem, key, default)


def _parse_bounds(elem: Any) -> Optional[Tuple[float, float, float, float, float]]:
    """Extract (x, y, w, h, area) from element bounds, or None."""
    raw = _get_val(elem, "bounds")
    if raw is None:
        raw = _get_val(elem, "bounding_rectangle") or _get_val(elem, "rect")
    if raw is None:
        return None

    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        x, y, w, h = float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])
        # If w > x and h > y and coordinates look like (left, top, right, bottom)
        # But commonly in UI automation, bounds is [left, top, width, height]
        # We compute area = w * h. If w < 0 or h < 0, fallback.
        area = abs(w * h)
        return (x, y, w, h, area)
    elif isinstance(raw, dict):
        x = float(raw.get("x", raw.get("left", 0)))
        y = float(raw.get("y", raw.get("top", 0)))
        w = float(raw.get("width", raw.get("w", 0)))
        h = float(raw.get("height", raw.get("h", 0)))
        if not w and "right" in raw:
            w = float(raw["right"]) - x
        if not h and "bottom" in raw:
            h = float(raw["bottom"]) - y
        area = abs(w * h)
        return (x, y, w, h, area)
    return None


def element_at_point(elements: List[Any], x: float, y: float) -> Optional[Any]:
    """Return the element containing (x, y) with the smallest area, or None."""
    candidates = []
    for elem in elements:
        parsed = _parse_bounds(elem)
        if parsed is None:
            continue
        ex, ey, ew, eh, area = parsed
        # Check containment: ex <= x <= ex + ew and ey <= y <= ey + eh
        # Also check if ew/eh was right/bottom
        in_wh = (ex <= x <= ex + ew) and (ey <= y <= ey + eh)
        in_rb = (ex <= x <= ew) and (ey <= y <= eh)
        if in_wh or in_rb:
            candidates.append((area, elem))

    if not candidates:
        return None

    # Pick smallest area
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]


def selector_from_element(elem: Any) -> Optional[Dict[str, Any]]:
    """Convert UI element reference into a selector dict."""
    if elem is None:
        return None

    auto_id = _get_val(elem, "automation_id")
    if auto_id and str(auto_id).strip():
        return {"automation_id": str(auto_id).strip()}

    name = _get_val(elem, "name")
    ctype = _get_val(elem, "control_type") or _get_val(elem, "role")

    if name and str(name).strip() and ctype and str(ctype).strip():
        return {
            "name": str(name).strip(),
            "control_type": str(ctype).strip(),
        }

    return None


def default_point_fn() -> Optional[Tuple[int, int]]:
    """Return cursor position (x, y) on Windows, or None on other platforms."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

            pt = POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):  # type: ignore[attr-defined]
                return (int(pt.x), int(pt.y))
        except Exception as exc:
            logger.warning("Failed to get cursor position via ctypes: %s", exc)
    return None


def pick_selector(
    snapshot_fn: Callable[[str], List[Any]],
    app_name: str,
    point_fn: Optional[Callable[[], Optional[Tuple[int, int]]]] = None,
) -> Optional[Dict[str, Any]]:
    """Query snapshot and find selector via focused element or cursor click."""
    try:
        elements = snapshot_fn(app_name) or []

        # 1. Check focused element
        for elem in elements:
            is_focused = bool(_get_val(elem, "focused") or _get_val(elem, "has_keyboard_focus"))
            if is_focused:
                sel = selector_from_element(elem)
                if sel:
                    return sel

        # 2. Check point from point_fn
        if point_fn is not None:
            pt = point_fn()
            if pt is not None:
                x, y = pt
                target = element_at_point(elements, x, y)
                if target is not None:
                    sel = selector_from_element(target)
                    if sel:
                        return sel

        return None
    except Exception as exc:
        logger.warning("pick_selector failed: %s", exc)
        return None
