"""視窗置頂工具測試（不需要顯示器）。"""

import logging

from deploy.windows_agent.window_utils import keep_on_top


class _FakeRoot:
    def __init__(self):
        self.calls = []

    def attributes(self, *args):
        self.calls.append(("attributes",) + args)

    def lift(self):
        self.calls.append(("lift",))

    def focus_force(self):
        self.calls.append(("focus_force",))


def test_keep_on_top_sets_topmost_and_focus():
    root = _FakeRoot()
    keep_on_top(root)
    assert ("attributes", "-topmost", True) in root.calls
    assert ("lift",) in root.calls
    assert ("focus_force",) in root.calls


class _BrokenRoot:
    def attributes(self, *args):
        raise RuntimeError("platform unsupported")


def test_keep_on_top_failure_logs_warning_and_does_not_raise(caplog):
    with caplog.at_level(logging.WARNING):
        keep_on_top(_BrokenRoot())
    assert any("無法設定視窗置頂" in r.message for r in caplog.records)
