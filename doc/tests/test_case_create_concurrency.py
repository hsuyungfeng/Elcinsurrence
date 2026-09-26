"""A-WR-01：併發建立同一 case_id，恰好一次成功，其餘為 DuplicateCaseError（不是 IntegrityError）。"""
import threading

from elc_audit_engine.case_store import CaseStore, DuplicateCaseError


def test_concurrent_create_same_id(tmp_path):
    store = CaseStore(db_path=str(tmp_path / "c.sqlite3"))
    ok, dup, other = [], [], []

    def worker():
        try:
            store.create(case_id="SAMP-X", kind="sampling")
            ok.append(1)
        except DuplicateCaseError:
            dup.append(1)
        except Exception as exc:  # noqa: BLE001
            other.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert other == []
    assert len(ok) == 1 and len(dup) == 11
    assert len(store.history("SAMP-X")) == 1
