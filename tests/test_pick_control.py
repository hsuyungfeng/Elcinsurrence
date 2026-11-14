"""Tests for pick_control element selection logic (Phase 32 Plan 32-04, B7)."""

import pytest
from deploy.windows_agent.pick_control import (
    element_at_point,
    selector_from_element,
    pick_selector,
)


def test_element_at_point():
    # 2 elements, one larger, one smaller inside
    outer = {"name": "Window", "bounds": [0, 0, 800, 600], "automation_id": "win1"}
    inner = {"name": "Subjective", "bounds": [100, 100, 300, 200], "automation_id": "txtS"}
    irrelevant = {"name": "Other", "bounds": [500, 500, 100, 100], "automation_id": "txtOther"}

    elements = [outer, inner, irrelevant]

    # Point inside inner (150, 150) -> should pick inner (smaller area)
    picked = element_at_point(elements, 150, 150)
    assert picked is not None
    assert picked["automation_id"] == "txtS"

    # Point outside all -> None
    assert element_at_point(elements, 900, 900) is None

    # Missing bounds ignored
    no_bounds = {"name": "NoBounds"}
    assert element_at_point([no_bounds], 50, 50) is None


def test_selector_from_element():
    # 1. automation_id preferred
    e1 = {"automation_id": "field_s", "name": "S", "control_type": "Edit"}
    assert selector_from_element(e1) == {"automation_id": "field_s"}

    # 2. name and control_type
    e2 = {"automation_id": "", "name": "主訴", "control_type": "Edit"}
    assert selector_from_element(e2) == {"name": "主訴", "control_type": "Edit"}

    # 3. role mapped to control_type
    e3 = {"automation_id": "", "name": "客觀", "role": "Edit"}
    assert selector_from_element(e3) == {"name": "客觀", "control_type": "Edit"}

    # 4. insufficient data -> None
    e4 = {"automation_id": "", "name": ""}
    assert selector_from_element(e4) is None


def test_pick_selector_focus_first():
    focused_elem = {"name": "FocusField", "automation_id": "focus_auto_id", "focused": True}
    other_elem = {"name": "ClickField", "bounds": [0, 0, 200, 200], "automation_id": "click_auto_id"}

    def mock_snapshot(app_name):
        return [other_elem, focused_elem]

    # Even with point_fn pointing to other_elem, focused element wins
    res = pick_selector(mock_snapshot, "MockHIS", point_fn=lambda: (50, 50))
    assert res == {"automation_id": "focus_auto_id"}


def test_pick_selector_fallback_to_point():
    e = {"name": "Field", "bounds": [10, 10, 100, 100], "automation_id": "auto1"}

    def mock_snapshot(app_name):
        return [e]

    res = pick_selector(mock_snapshot, "MockHIS", point_fn=lambda: (20, 20))
    assert res == {"automation_id": "auto1"}

    # Point misses
    miss = pick_selector(mock_snapshot, "MockHIS", point_fn=lambda: (500, 500))
    assert miss is None
