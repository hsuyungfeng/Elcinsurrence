"""申報批次 20+10 抽樣選案演算法（Phase 16-01）。

- 隨機抽樣：自批次全部案件中隨機抽取 `random_count` 件（可指定 seed 以利重現）。
- 立意抽查：每案以「前三個最高點數醫令（p12）」之點數合計排序，由高到低取 `intentional_count` 件；
  已被隨機抽中者略過，由下一名順延，避免重複。
- 合併：隨機在前、立意在後，總數為兩者之和（批次案件不足時取全部）。

同一批次、同一 seed 結果完全相同；排序與抽樣前都先依 case_id 排序，確保可重現。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from elc_audit_engine.case_store.store import CaseStore
from elc_audit_engine.ingest.sampling import SamplingCaseRecord

SAMPLE_RANDOM = "random"
SAMPLE_INTENTIONAL = "intentional"
TOP_ORDER_COUNT = 3
_PAGE = 500


@dataclass(frozen=True)
class SampledCase:
    sample_type: str  # random | intentional
    monthly_case_id: str  # 申報批次案件的 MON-… 內容雜湊 ID
    top3_points_total: Decimal
    target_order_code: str | None
    record: SamplingCaseRecord
    # 來源申報總檔案件的完整 payload（含 case_class、d1/d2/d3、orders 原始欄位）；
    # 供抽樣案件組裝健保抽審 XML（sampling_xml.build_sampling_xml 的 monthly_source）。
    source_payload: dict = field(default_factory=dict, compare=False, repr=False)


def _points(raw: Any) -> Decimal:
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        return Decimal(0)
    return value if value.is_finite() else Decimal(0)


def _order_points(payload: dict) -> list[tuple[Decimal, str]]:
    """每筆醫令的 (點數 p12, 醫令代碼 p4)；依點數由高到低排序（同點數依代碼）。"""
    rows = [(_points(o.get("p12")), (o.get("p4") or "").strip()) for o in payload.get("orders") or []]
    return sorted(rows, key=lambda row: (-row[0], row[1]))


def top3_points_total(payload: dict) -> Decimal:
    """前三個最高點數醫令之點數合計（不足三筆則全部相加）。"""
    return sum((points for points, _code in _order_points(payload)[:TOP_ORDER_COUNT]), Decimal(0))


def _target_code(payload: dict) -> str | None:
    ordered = _order_points(payload)
    return ordered[0][1] or None if ordered else None


def _record(payload: dict, target_code: str | None) -> SamplingCaseRecord:
    return SamplingCaseRecord(
        order_code=target_code or "",
        order_name=None,
        case_seq=payload.get("case_seq"),
        record_no=payload.get("record_no"),
        patient_name=payload.get("patient_name"),
        visit_date=payload.get("visit_date"),
        clinic=payload.get("clinic"),
        soap_text="",
        source="monthly_batch",
    )


def _all_monthly_payloads(store: CaseStore, batch_id: str) -> dict[str, dict]:
    """批次內全部案件：{case_id: payload}，分頁讀取，不截斷。"""
    payloads: dict[str, dict] = {}
    offset = 0
    while True:
        rows = store.list_by_batch(batch_id, limit=_PAGE, offset=offset)
        if not rows:
            break
        for row in rows:
            if row.payload is not None:
                payloads[row.case_id] = row.payload
        offset += len(rows)
    return payloads


def sample_monthly_batch(
    store: CaseStore,
    batch_id: str,
    random_count: int = 20,
    intentional_count: int = 10,
    seed: int | None = None,
) -> list[SampledCase]:
    """依 20 隨機 + 10 立意產生抽樣名單（不重複）。

    Raises:
        ValueError: 抽樣數為負數。
    """
    if random_count < 0 or intentional_count < 0:
        raise ValueError("抽樣數不得為負數")

    payloads = _all_monthly_payloads(store, batch_id)
    case_ids = sorted(payloads)  # 先排序，確保同 seed 可重現
    top3 = {cid: top3_points_total(payloads[cid]) for cid in case_ids}

    rng = random.Random(seed)
    random_ids = rng.sample(case_ids, min(random_count, len(case_ids)))
    chosen = set(random_ids)

    ranked = sorted(case_ids, key=lambda cid: (-top3[cid], cid))
    intentional_ids: list[str] = []
    for cid in ranked:
        if len(intentional_ids) >= intentional_count:
            break
        if cid in chosen:
            continue  # 已被隨機抽中：由下一名順延
        intentional_ids.append(cid)
        chosen.add(cid)

    picks = [(SAMPLE_RANDOM, cid) for cid in random_ids] + [(SAMPLE_INTENTIONAL, cid) for cid in intentional_ids]
    result: list[SampledCase] = []
    for sample_type, cid in picks:
        payload = payloads[cid]
        target = _target_code(payload)
        result.append(
            SampledCase(
                sample_type=sample_type,
                monthly_case_id=cid,
                top3_points_total=top3[cid],
                target_order_code=target,
                record=_record(payload, target),
                source_payload=payload,
            )
        )
    return result
