"""Phase 31: 循環草稿送出、隔離檢索與 advisory 整合 (D-31-39, D-31-16, D-31-13, D-31-23, D-31-25, D-31-27).

核心職責：
- 循環草稿送出 (submit_cycle_draft)：需 upload_complete=1，以 session_id 冪等，保存逐字稿與 extras
- 循環草稿檢視 (cycle_draft_view)：唯讀 advisory、依參數包含逐字稿
- 循環隔離 (cycle_bound_draft_ids, is_cycle_bound)：供 pending-review 排除與 approve/edit 409 防護
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import uuid
from typing import Any, Dict, Optional, Sequence, Set, Tuple

from elc_audit_engine.cycles.states import (
    STATE_AWAITING_CONFIRM,
    STATE_AWAITING_DRAFT,
    STATE_DRAFT_UNUSABLE,
)
from elc_audit_engine.cycles.store import cycle_dir, cycle_view, transition_cycle

logger = logging.getLogger(__name__)

_SESSION_ID_RE = re.compile(r"^[0-9a-zA-Z_-]{1,64}$")
_MAX_EXTRA_STR_LEN = 20000
_MAX_SUGGESTION_ITEMS = 200


def extract_advisory(comparison: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """從草稿之 comparison 萃取唯讀之建議項（共用於 pending-review 與 cycle_draft_view）。"""
    comp = comparison or {}
    icd10_suggestions = comp.get("icd10_suggestions", [])
    order_suggestions = comp.get("order_suggestions", [])
    med_suggestions = comp.get("med_suggestions", [])

    if not icd10_suggestions and isinstance(comp.get("advice"), dict):
        icd10_suggestions = comp.get("advice", {}).get("icd10", [])

    return {
        "icd10_suggestions": list(icd10_suggestions),
        "order_suggestions": list(order_suggestions),
        "med_suggestions": list(med_suggestions),
        "read_only": True,
    }


def cycle_bound_draft_ids(store, draft_ids: Sequence[str]) -> Set[str]:
    """查詢給定之 draft_ids 清單中哪些已綁定至 recording_cycles。"""
    if not draft_ids:
        return set()
    placeholders = ",".join("?" for _ in draft_ids)
    conn = store._connect()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT draft_id FROM recording_cycles WHERE draft_id IN ({placeholders})",
            list(draft_ids),
        )
        rows = cur.fetchall()
        return {r["draft_id"] for r in rows if r["draft_id"]}
    finally:
        conn.close()


def is_cycle_bound(store, draft_id: str) -> bool:
    """檢查特定 draft_id 是否已被任何循環綁定。"""
    if not draft_id:
        return False
    conn = store._connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM recording_cycles WHERE draft_id = ? LIMIT 1",
            (draft_id,),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def validate_draft_payload(payload: Dict[str, Any]) -> None:
    """驗證草稿送出之資料結構與邊界限制。"""
    session_id = payload.get("session_id")
    if not session_id or not isinstance(session_id, str) or not _SESSION_ID_RE.match(session_id):
        raise ValueError(f"缺少或不合法的 session_id 格式：{session_id!r}")

    soap = payload.get("soap")
    if not isinstance(soap, dict):
        raise ValueError("soap 必須為包含 s, o, a, p 的字典")
    for k in ("s", "o", "a", "p"):
        if k not in soap or not isinstance(soap[k], str):
            raise ValueError(f"soap 缺少或包含無效之鍵：{k}")

    transcript = payload.get("transcript")
    if transcript is not None and not isinstance(transcript, str):
        raise ValueError("transcript 必須為字串")

    extras = payload.get("extras")
    if extras is not None:
        if not isinstance(extras, dict):
            raise ValueError("extras 必須為字典")
        for k in ("summary_zh", "past_history"):
            val = extras.get(k)
            if val is not None:
                if not isinstance(val, str):
                    raise ValueError(f"extras.{k} 必須為字串")
                if len(val) > _MAX_EXTRA_STR_LEN:
                    raise ValueError(f"extras.{k} 長度超過 {_MAX_EXTRA_STR_LEN} 上限")

        sugg = extras.get("suggestions")
        if sugg is not None:
            if not isinstance(sugg, dict):
                raise ValueError("extras.suggestions 必須為字典")
            for sk in ("icd10", "orders", "meds"):
                items = sugg.get(sk)
                if items is not None:
                    if not isinstance(items, list):
                        raise ValueError(f"extras.suggestions.{sk} 必須為清單")
                    if len(items) > _MAX_SUGGESTION_ITEMS:
                        raise ValueError(f"extras.suggestions.{sk} 項目超過 {_MAX_SUGGESTION_ITEMS} 上限")


def submit_cycle_draft(
    store,
    *,
    cycle_id: str,
    payload: Dict[str, Any],
    actor: Optional[str] = None,
) -> Tuple[Dict[str, Any], str, bool]:
    """將 SoapVoice 產出之草稿與逐字稿關聯至循環（以 session_id 冪等）。

    回傳：(cycle_view, draft_id, created)
    """
    validate_draft_payload(payload)

    session_id = payload["session_id"]
    case_id = payload.get("case_id") or f"case_{session_id}"
    soap = payload["soap"]
    order_code = payload.get("order_code")
    transcript = payload.get("transcript") or ""
    extras = payload.get("extras") or {}

    conn = store._connect()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.cursor()

            cur.execute("SELECT * FROM recording_cycles WHERE cycle_id = ?", (cycle_id,))
            c_row = cur.fetchone()
            if not c_row:
                raise LookupError(f"Cycle not found: {cycle_id}")

            # 驗證音訊上傳已完成
            if not bool(c_row["upload_complete"]):
                raise ValueError("音訊尚未完成上傳 (upload_complete=False)，無法送出草稿")

            current_state = c_row["state"]

            # 冪等性檢查
            if c_row["session_id"] == session_id and c_row["draft_id"]:
                return cycle_view(store, c_row), c_row["draft_id"], False

            if current_state not in (STATE_AWAITING_DRAFT, STATE_DRAFT_UNUSABLE):
                raise ValueError(f"循環狀態為 {current_state}，無法接收草稿")

            # 先行寫入 session_id 避免併發 TOCTOU 衝突
            cur.execute(
                "UPDATE recording_cycles SET session_id = ? WHERE cycle_id = ?",
                (session_id, cycle_id),
            )
    finally:
        conn.close()

    # 建立草稿記錄（使用 soap_review 的品質檢驗與範本比對，不觸發自動接入）
    from elc_audit_engine.api.routes.soap_review import _create_draft_record

    draft_record = _create_draft_record(
        store,
        case_id=case_id,
        soap=soap,
        order_code=order_code,
        primary_diagnosis=None,
    )

    # 儲存逐字稿 transcript.txt (tmp + replace)
    c_dir = cycle_dir(cycle_id)
    c_dir.mkdir(parents=True, exist_ok=True)
    tmp_transcript = c_dir / f"transcript.txt.tmp.{uuid.uuid4().hex[:8]}"
    target_transcript = c_dir / "transcript.txt"

    try:
        tmp_transcript.write_text(transcript, encoding="utf-8")
        os.replace(tmp_transcript, target_transcript)
    finally:
        if tmp_transcript.exists():
            try:
                tmp_transcript.unlink(missing_ok=True)
            except OSError:
                pass

    extras_payload = json.dumps(extras, ensure_ascii=False)

    # 判定目標狀態
    if draft_record.state == "quality_failed":
        target_state = STATE_DRAFT_UNUSABLE
    else:
        target_state = STATE_AWAITING_CONFIRM

    updated_cycle = transition_cycle(
        store,
        cycle_id,
        target_state,
        actor=actor,
        fields={
            "draft_id": draft_record.draft_id,
            "transcript_path": str(target_transcript),
            "extras_json": extras_payload,
        },
    )

    return updated_cycle, draft_record.draft_id, True


def cycle_draft_view(
    store,
    cycle_id: str,
    *,
    include_transcript: bool = False,
) -> Dict[str, Any]:
    """取得循環草稿之結構化檢視（契約 §3）。"""
    conn = store._connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM recording_cycles WHERE cycle_id = ?", (cycle_id,))
        c_row = cur.fetchone()
        if not c_row:
            raise LookupError(f"Cycle not found: {cycle_id}")
        draft_id = c_row["draft_id"]
        if not draft_id:
            raise LookupError(f"Cycle {cycle_id} has no draft associated")
        transcript_path = c_row["transcript_path"]
        extras_raw = c_row["extras_json"]
    finally:
        conn.close()

    draft_record = store.get_soap_draft(draft_id)
    if not draft_record:
        raise LookupError(f"Draft not found: {draft_id}")

    try:
        extras = json.loads(extras_raw) if extras_raw else {}
    except Exception:
        extras = {}

    advisory = extract_advisory(draft_record.comparison)

    res: Dict[str, Any] = {
        "cycle_id": cycle_id,
        "draft": {
            "draft_id": draft_record.draft_id,
            "version": draft_record.version,
            "content_hash": draft_record.content_hash,
            "state": draft_record.state,
            "soap": draft_record.soap,
            "quality_issues": draft_record.quality_issues or [],
        },
        "extras": extras,
        "advisory": advisory,
    }

    if include_transcript:
        transcript_text = ""
        if transcript_path and Path(transcript_path).is_file():
            try:
                transcript_text = Path(transcript_path).read_text(encoding="utf-8")
            except OSError:
                transcript_text = ""
        res["transcript"] = transcript_text

    return res
