"""第 2、3 階審查報告統一格式（相容層）。

實作已移至 `elc_audit_engine.services.report_renderer`（Phase 22-04）。
本模組保留既有匯入路徑，供路由與測試沿用，行為與原模組一致。
"""

from __future__ import annotations

from elc_audit_engine.services.report_renderer import (  # noqa: F401
    SECTION_ORDER,
    STAGE_TITLES,
    ReviewCaseView,
    RuleBlock,
    Stage,
    __all__,  # noqa: F401
    build_review_case_view,
    make_thumbnail_data_uri,
    render_aggregated_review_html,
    render_unified_review_html,
)
