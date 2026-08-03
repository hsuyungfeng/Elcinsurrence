"""輸出生成器：病歷補強報告（Phase 6）＋ 申復草稿（Phase 7）。

Phase 6 對外 API：
- render_report(comparison, timeline=None) -> str：Markdown checkbox 逐條審報告
- render_tracking(comparison, decisions=None, reviewed_at=None) -> str：審核軌跡 JSON
- write_report(output_dir, case_record_no, comparison, decisions=None, ...)
  -> (report_path, tracking_path)

Phase 7 對外 API：
- build_appeal_draft(record, *, is_appealing, claimed_points, timeline, ...)
  -> AppealDraft：D10 四段組裝＋字數控制器（Q15）＋P6 硬檢查（C3）
- adopted_narratives_from_tracking(tracking)：審核軌跡 → 採用/編輯後採用敘述
- render_appeal_markdown / render_appeal_json / write_appeal：輸出（C7）
"""

from .appeal import (
    MAX_FIELD_CHARS,
    MAX_TOTAL_CHARS,
    AppealDraft,
    AppealSection,
    adopted_narratives_from_tracking,
    build_appeal_draft,
    build_necessity,
    render_appeal_json,
    render_appeal_markdown,
    resolve_p6_points,
    validate_appeal_claim,
    write_appeal,
)
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
    "MAX_FIELD_CHARS",
    "MAX_TOTAL_CHARS",
    "STATUS_ADOPT",
    "STATUS_ADOPT_EDITED",
    "STATUS_DECLINE",
    "STATUS_FLAG",
    "STATUS_PENDING",
    "AppealDraft",
    "AppealSection",
    "adopted_narratives_from_tracking",
    "build_appeal_draft",
    "build_necessity",
    "render_appeal_json",
    "render_appeal_markdown",
    "render_report",
    "render_timeline_summary",
    "render_tracking",
    "resolve_p6_points",
    "validate_appeal_claim",
    "write_appeal",
    "write_report",
]
