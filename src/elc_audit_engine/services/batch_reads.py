"""批次讀取與截斷揭露（Phase 22-04：Flask-free，供服務層使用；P1-10）。

CaseStore.list_all 單次最多讀取 limit 筆，超過時以 total 揭露真實總數。
"""

from __future__ import annotations

BATCH_READ_LIMIT = 1000


def read_batch(store, kind: str, *, limit: int | None = None) -> tuple[list, dict]:
    """讀取某類案件（依 created_at 升冪）並回傳截斷揭露資訊。

    回傳 (records, meta)；meta 含 total（資料庫真實總數）、returned、truncated、limit。
    """
    cap = BATCH_READ_LIMIT if limit is None else limit
    total = store.count(kind=kind)
    records = list(store.list_all(kind=kind, limit=cap))
    meta = {
        "total": total,
        "returned": len(records),
        "truncated": total > len(records),
        "limit": cap,
    }
    return records, meta


__all__ = ["BATCH_READ_LIMIT", "read_batch"]
