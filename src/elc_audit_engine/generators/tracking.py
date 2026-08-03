"""審核軌跡 JSON 生成器（D9/D-03/D-04）。

D9：逐條審四狀態「採用／編輯後採用／略過／標記不符事實」＋整稿確認；
全程留審核軌跡 JSON（狀態、原文、編輯後文、時間）— 合規責任歸屬＋
採用率數據飛輪。

`render_tracking(comparison, decisions, reviewed_at=None)` 為純函式：
- decisions 為醫師審核結果輸入：{候選補強 index: (status, edited_text)}
- 未審核的候選補強 → status=「未審核」
- reviewed_at 可注入固定時間（ISO UTC），預設取現在
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from elc_audit_engine.comparator.models import CaseComparisonResult

# D9 四狀態
STATUS_ADOPT = "採用"
STATUS_ADOPT_EDITED = "編輯後採用"
STATUS_DECLINE = "略過"
STATUS_FLAG = "標記不符事實"
STATUS_PENDING = "未審核"
STATUSES = (STATUS_ADOPT, STATUS_ADOPT_EDITED, STATUS_DECLINE, STATUS_FLAG)


def render_tracking(
    comparison: CaseComparisonResult,
    decisions: dict | None = None,
    reviewed_at: str | None = None,
) -> str:
    """渲染審核軌跡 JSON（D-03）。

    Args:
        comparison: Phase 5 比對結果（提供候選補強敘述清單）。
        decisions: 醫師審核結果，格式：
            `{narrative_index: (status, edited_text)}`，其中
            narrative_index 為候選補強在整份報告中的順序號（0-based，
            依 order_judgments × narratives 依序展開）；status 為
            採用/編輯後採用/略過/標記不符事實；edited_text 為編輯後文
            （採用但未編輯時可為 None）。
        reviewed_at: 審核時間戳（ISO 8601）；預設現在（UTC）。

    Returns:
        審核軌跡 JSON 字串（含 case_record_no、reviewed_at、逐條記錄）。
    """
    if reviewed_at is None:
        reviewed_at = datetime.now(timezone.utc).isoformat()

    decisions = decisions or {}
    entries: list[dict] = []

    narrative_index = 0
    for oj in comparison.order_judgments:
        for narrative in oj.narratives:
            status, edited_text = decisions.get(
                narrative_index, (STATUS_PENDING, None)
            )
            if status not in STATUSES:
                status = STATUS_PENDING
            entries.append(
                {
                    "order_code": oj.order_code,
                    "narrative_text": narrative.text,
                    "status": status,
                    "edited_text": edited_text,
                    "rule_location": narrative.rule_location,
                }
            )
            narrative_index += 1

    payload = {
        "case_record_no": comparison.case_record_no,
        "reviewed_at": reviewed_at,
        "entries": entries,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
