"""案件清單回應（A-WR-12）。"""

from __future__ import annotations

from flask import jsonify, request

from ..context import case_store
from ..errors import ApiError

CASE_LIST_MAX_LIMIT = 1000


def case_list_response(kind: str, demo: list[dict]):
    """案件清單：維持陣列格式，每筆附 state／failure_reason；支援 ?limit=&offset=
    分頁並以 X-Total-Count 揭露總數（不靜默截斷）。未匯入任何案件時回示範資料。"""
    store = case_store()
    total = store.count(kind=kind)
    if not total:
        return jsonify(demo)
    try:
        limit = int(request.args.get("limit", CASE_LIST_MAX_LIMIT))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        raise ApiError("limit／offset 必須為整數")
    if not (1 <= limit <= CASE_LIST_MAX_LIMIT) or offset < 0:
        raise ApiError(f"limit 須介於 1～{CASE_LIST_MAX_LIMIT}，offset 不得為負")
    records = store.list_all(kind=kind, limit=limit, offset=offset)
    items = [
        {**r.payload, "id": r.case_id, "state": r.state, "failure_reason": r.failure_reason}
        for r in records
        if r.payload is not None
    ]
    resp = jsonify(items)
    resp.headers["X-Total-Count"] = str(total)
    return resp
