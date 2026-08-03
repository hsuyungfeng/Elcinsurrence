"""輸出生成器：病歷補強報告（Phase 6）＋ 申復草稿（Phase 7）。

Phase 6 對外 API：
- render_report(comparison, timeline=None) -> str：Markdown checkbox 逐條審報告
- render_tracking(comparison, decisions=None, reviewed_at=None) -> str：審核軌跡 JSON
- write_report(output_dir, case_record_no, comparison, decisions=None, ...)
  -> (report_path, tracking_path)
"""

from .reinforcement_report import render_report, render_timeline_summary, write_report
from .tracking import (
    STATUS_ADOPT,
    STATUS_ADOPT_EDITED,
    STATUS_DECLINE,
    STATUS_FLAG,
    STATUS_PENDING,
    render_tracking,
)

__all__ = [
    "STATUS_ADOPT",
    "STATUS_ADOPT_EDITED",
    "STATUS_DECLINE",
    "STATUS_FLAG",
    "STATUS_PENDING",
    "render_report",
    "render_timeline_summary",
    "render_tracking",
    "write_report",
]
