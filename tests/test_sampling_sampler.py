"""Phase 16-01：申報批次 20 隨機＋10 立意抽樣演算法與 API。

測試資料為合成案件（MON-001…），以 CaseStore 暫存庫建立，不讀取正式資料。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from elc_audit_engine.case_store.store import CaseStore
from elc_audit_engine.sampling_sampler import (
    SAMPLE_INTENTIONAL,
    SAMPLE_RANDOM,
    sample_monthly_batch,
    top3_points_total,
)

KEY = {"X-API-Key": "valid-key-123"}
BATCH = "MONTHLY-202307"


def _payload(index: int, points: list[int]) -> dict:
    return {
        "batch": BATCH,
        "case_seq": str(index),
        "record_no": f"A{index:09d}",
        "patient_name": f"病患{index}",
        "visit_date": "1120718",
        "clinic": "03",
        "orders": [
            {"p3": "2", "p4": f"O{index:03d}{j}", "p12": str(p), "p13": str(j + 1)}
            for j, p in enumerate(points)
        ],
    }


def _seed_store(tmp_path, cases: dict[int, list[int]]) -> CaseStore:
    store = CaseStore(db_path=str(tmp_path / "cases.sqlite3"))
    for index, points in cases.items():
        store.create(case_id=f"MON-{index:03d}", kind="monthly", payload=_payload(index, points))
    return store


def _cases_40() -> dict[int, list[int]]:
    """40 案：每案 4 筆醫令，點數以索引變化，前三合計互不相同（便於驗證排名）。"""
    return {i: [i * 10, i * 7 + 3, i * 3 + 1, 5] for i in range(1, 41)}


def _top3(points: list[int]) -> int:
    return sum(sorted(points, reverse=True)[:3])


# ── 演算法 ──────────────────────────────────────────────────────


def test_top3_points_total_sums_three_highest_orders():
    assert top3_points_total(_payload(1, [100, 400, 300, 200])) == Decimal(900)
    assert top3_points_total(_payload(1, [50])) == Decimal(50)
    assert top3_points_total({"orders": []}) == Decimal(0)


def test_total_is_30_with_20_random_and_10_intentional(tmp_path):
    store = _seed_store(tmp_path, _cases_40())
    picked = sample_monthly_batch(store, BATCH, seed=7)
    assert len(picked) == 30
    assert sum(p.sample_type == SAMPLE_RANDOM for p in picked) == 20
    assert sum(p.sample_type == SAMPLE_INTENTIONAL for p in picked) == 10


def test_no_duplicates_across_random_and_intentional(tmp_path):
    store = _seed_store(tmp_path, _cases_40())
    picked = sample_monthly_batch(store, BATCH, seed=7)
    ids = [p.monthly_case_id for p in picked]
    assert len(set(ids)) == len(ids) == 30


def test_intentional_picks_are_the_highest_top3_cases_not_already_random(tmp_path):
    cases = _cases_40()
    store = _seed_store(tmp_path, cases)
    picked = sample_monthly_batch(store, BATCH, seed=11)
    random_ids = {p.monthly_case_id for p in picked if p.sample_type == SAMPLE_RANDOM}
    intentional = [p for p in picked if p.sample_type == SAMPLE_INTENTIONAL]

    # 立意 10 件的前三合計，必須不低於任何未入選案件（順延後仍為最高者）
    intentional_ids = {p.monthly_case_id for p in intentional}
    rest = [f"MON-{i:03d}" for i in cases if f"MON-{i:03d}" not in random_ids | intentional_ids]
    lowest_chosen = min(_top3(cases[int(cid[4:])]) for cid in intentional_ids)
    highest_rest = max(_top3(cases[int(cid[4:])]) for cid in rest)
    assert lowest_chosen >= highest_rest

    # 每件立意的 top3 合計與演算法回報一致
    for p in intentional:
        assert p.top3_points_total == Decimal(_top3(cases[int(p.monthly_case_id[4:])]))


def test_overlap_is_skipped_and_next_ranked_case_fills_in(tmp_path):
    """若隨機抽中的案件正好是立意排名第一，立意應順延到第二名，總數仍為 30。"""
    cases = _cases_40()
    store = _seed_store(tmp_path, cases)
    ranked = sorted(cases, key=lambda i: (-_top3(cases[i]), f"MON-{i:03d}"))
    # 以相同 seed 預先找出隨機抽中的集合，確認本測試情境成立
    import random as _random

    all_ids = sorted(f"MON-{i:03d}" for i in cases)
    top_id = f"MON-{ranked[0]:03d}"
    seed = next(s for s in range(200) if top_id in set(_random.Random(s).sample(all_ids, 20)))
    picked = sample_monthly_batch(store, BATCH, seed=seed)
    assert any(p.monthly_case_id == top_id and p.sample_type == SAMPLE_RANDOM for p in picked)
    intentional_ids = [p.monthly_case_id for p in picked if p.sample_type == SAMPLE_INTENTIONAL]
    assert top_id not in intentional_ids
    assert len(picked) == 30


def test_same_seed_gives_identical_selection(tmp_path):
    store = _seed_store(tmp_path, _cases_40())
    first = [(p.sample_type, p.monthly_case_id) for p in sample_monthly_batch(store, BATCH, seed=42)]
    second = [(p.sample_type, p.monthly_case_id) for p in sample_monthly_batch(store, BATCH, seed=42)]
    assert first == second


def test_target_order_is_highest_points_order(tmp_path):
    store = _seed_store(tmp_path, {1: [100, 900, 300]})
    picked = sample_monthly_batch(store, BATCH, random_count=1, intentional_count=0, seed=1)
    assert picked[0].target_order_code == "O0011"  # 點數 900 為該案最高


def test_small_batch_returns_all_cases_without_duplicates(tmp_path):
    store = _seed_store(tmp_path, {1: [10], 2: [20], 3: [30], 4: [40], 5: [50]})
    picked = sample_monthly_batch(store, BATCH, seed=5)
    assert len(picked) == 5
    assert len({p.monthly_case_id for p in picked}) == 5


def test_negative_counts_rejected(tmp_path):
    store = _seed_store(tmp_path, {1: [10]})
    with pytest.raises(ValueError):
        sample_monthly_batch(store, BATCH, random_count=-1)


def test_empty_batch_returns_empty(tmp_path):
    store = _seed_store(tmp_path, {})
    assert sample_monthly_batch(store, BATCH, seed=1) == []


# ── API ─────────────────────────────────────────────────────────


@pytest.fixture
def api(make_api_app, tmp_path):
    app = make_api_app()
    store = app.extensions["elc"].case_store
    for index, points in _cases_40().items():
        store.create(case_id=f"MON-{index:03d}", kind="monthly", payload=_payload(index, points))
    return app


@pytest.fixture
def client(api):
    with api.test_client() as c:
        yield c


def test_sample_batch_endpoint_persists_30_sampling_cases(client, api):
    res = client.post("/api/sampling/sample-batch", headers=KEY,
                      json={"batch": BATCH, "random_count": 20, "intentional_count": 10, "seed": 9})
    assert res.status_code == 200
    body = res.get_json()
    assert body["sampled"] == 30 and body["random"] == 20 and body["intentional"] == 10
    assert body["case_store_persisted"] == 30 and body["case_store_conflicts"] == []

    store = api.extensions["elc"].case_store
    stored = store.list_all(kind="sampling")
    assert len(stored) == 30
    assert {r.payload["sample_type"] for r in stored} == {SAMPLE_RANDOM, SAMPLE_INTENTIONAL}


def test_sample_batch_is_idempotent_on_repeat(client):
    payload = {"batch": BATCH, "random_count": 20, "intentional_count": 10, "seed": 9}
    client.post("/api/sampling/sample-batch", headers=KEY, json=payload)
    again = client.post("/api/sampling/sample-batch", headers=KEY, json=payload).get_json()
    assert again["case_store_persisted"] == 0
    assert len(again["case_store_conflicts"]) == 30


def test_sample_batch_requires_api_key(client):
    assert client.post("/api/sampling/sample-batch", json={"batch": BATCH}).status_code == 401


@pytest.mark.parametrize("body", [
    {"batch": "MONTHLY-2023"},
    {"batch": BATCH, "random_count": 500},
    {"batch": BATCH, "intentional_count": "ten"},
    {"batch": BATCH, "seed": "x"},
])
def test_sample_batch_validates_input(client, body):
    assert client.post("/api/sampling/sample-batch", headers=KEY, json=body).status_code == 400


def test_sample_batch_unknown_batch_is_404(client):
    res = client.post("/api/sampling/sample-batch", headers=KEY, json={"batch": "MONTHLY-209901"})
    assert res.status_code == 404
