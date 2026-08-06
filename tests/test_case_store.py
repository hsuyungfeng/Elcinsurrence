"""CaseStore SQLite 持久化＋轉換歷史＋重啟讀回＋同步佇列查詢測試。

全部使用 `tmp_path` 建立臨時 DB，**零 LLM 依賴**。
"""

import sqlite3

import pytest

from elc_audit_engine.case_store.states import UnknownStateError
from elc_audit_engine.case_store.store import (
    CaseNotFoundError,
    CaseStore,
    DuplicateCaseError,
    MissingFailureReasonError,
)
from elc_audit_engine.safe_paths import UnsafeIdentifierError


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "test_cases.sqlite3")


@pytest.fixture
def store(db_path) -> CaseStore:
    return CaseStore(db_path=db_path)


def test_create_then_get_returns_imported_state_with_history(store):
    store.create(case_id="C001", kind="sampling")
    record = store.get("C001")
    assert record.state == "imported"

    history = store.history("C001")
    assert len(history) == 1
    assert history[0].from_state is None
    assert history[0].to_state == "imported"


def test_main_line_transitions_all_succeed_with_full_history(store):
    store.create(case_id="C002", kind="sampling")
    store.transition("C002", "parsed")
    store.transition("C002", "reviewing")
    store.transition("C002", "reviewed")
    store.transition("C002", "appealed")
    store.transition("C002", "submitted")

    record = store.get("C002")
    assert record.state == "submitted"

    history = store.history("C002")
    assert len(history) == 6


def test_illegal_transition_from_submitted_to_imported_leaves_state_and_history_unchanged(store):
    from elc_audit_engine.case_store.states import IllegalTransitionError

    store.create(case_id="C003", kind="sampling")
    for target in ("parsed", "reviewing", "reviewed", "appealed", "submitted"):
        store.transition("C003", target)

    history_before = store.history("C003")

    with pytest.raises(IllegalTransitionError):
        store.transition("C003", "imported")

    assert store.get("C003").state == "submitted"
    assert store.history("C003") == history_before


def test_transition_to_failed_without_reason_raises_missing_failure_reason_error(store):
    store.create(case_id="C004", kind="sampling")
    with pytest.raises(MissingFailureReasonError):
        store.transition("C004", "failed")

    record = store.transition("C004", "failed", reason="LLM 逾時")
    assert record.state == "failed"
    assert record.failure_reason == "LLM 逾時"


def test_failed_back_to_parsed_clears_failure_reason(store):
    store.create(case_id="C005", kind="sampling")
    store.transition("C005", "failed", reason="DB 連線逾時")
    store.transition("C005", "parsed")

    record = store.get("C005")
    assert record.state == "parsed"
    assert record.failure_reason is None


def test_create_duplicate_case_id_raises_duplicate_case_error_and_does_not_overwrite_history(store):
    store.create(case_id="C006", kind="sampling")
    store.transition("C006", "parsed")

    with pytest.raises(DuplicateCaseError):
        store.create(case_id="C006", kind="sampling")

    # 未被覆寫：狀態仍為 parsed，歷史仍只有 create + transition 兩列
    assert store.get("C006").state == "parsed"
    assert len(store.history("C006")) == 2


def test_get_nonexistent_case_raises_case_not_found_error(store):
    with pytest.raises(CaseNotFoundError):
        store.get("不存在的案件")


def test_create_with_path_traversal_case_id_raises_unsafe_identifier_error(store):
    with pytest.raises(UnsafeIdentifierError):
        store.create(case_id="../etc/passwd", kind="sampling")


def test_restart_persists_state_and_history_across_new_store_instance(db_path):
    store_a = CaseStore(db_path=db_path)
    store_a.create(case_id="C007", kind="appeal")
    store_a.transition("C007", "parsed")
    store_a.transition("C007", "reviewing")
    del store_a

    store_b = CaseStore(db_path=db_path)
    record = store_b.get("C007")
    assert record.state == "reviewing"

    history = store_b.history("C007")
    assert len(history) == 3


def test_list_by_state_filters_by_kind_and_orders_fifo(store):
    store.create(case_id="S001", kind="sampling")
    store.create(case_id="A001", kind="appeal")
    store.create(case_id="S002", kind="sampling")

    results = store.list_by_state("imported", kind="sampling")
    assert [r.case_id for r in results] == ["S001", "S002"]


def test_list_by_state_unknown_state_raises_unknown_state_error(store):
    with pytest.raises(UnknownStateError):
        store.list_by_state("bogus")


def test_counts_by_state_sums_to_list_all_length(store):
    store.create(case_id="C010", kind="sampling")
    store.create(case_id="C011", kind="sampling")
    store.transition("C011", "parsed")
    store.create(case_id="C012", kind="appeal")

    counts = store.counts_by_state()
    assert sum(counts.values()) == len(store.list_all())
    assert counts["imported"] == 2
    assert counts["parsed"] == 1


def test_transition_atomicity_state_unchanged_when_transition_insert_fails(store, monkeypatch):
    store.create(case_id="C013", kind="sampling")

    def _boom(self, conn, **kwargs):
        raise sqlite3.Error("模擬寫入 case_transitions 失敗")

    monkeypatch.setattr(CaseStore, "_insert_transition", _boom)

    with pytest.raises(sqlite3.Error):
        store.transition("C013", "parsed")

    # 狀態未變（沒有只寫一半）
    assert store.get("C013").state == "imported"
    # 歷史仍只有 create 那一列
    assert len(store.history("C013")) == 1
