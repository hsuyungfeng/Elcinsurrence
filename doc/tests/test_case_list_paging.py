"""A-WR-12：案件清單附狀態、分頁、揭露總數。"""
import server


def test_case_list_includes_state_and_total(client):
    for i in range(3):
        server._case_store.create(case_id=f"SAMP-{i}", kind="sampling", payload={"id": f"SAMP-{i}"})
    server._case_store.transition("SAMP-0", "failed", reason="x")
    resp = client.get("/api/sampling/cases?limit=2")
    assert resp.status_code == 200
    items = resp.get_json()
    assert len(items) == 2
    assert resp.headers["X-Total-Count"] == "3"
    assert items[0]["state"] == "failed" and items[0]["failure_reason"] == "x"
    rest = client.get("/api/sampling/cases?limit=2&offset=2").get_json()
    assert [r["id"] for r in rest] == ["SAMP-2"]


def test_case_list_rejects_bad_paging(client):
    server._case_store.create(case_id="SAMP-A", kind="sampling", payload={"id": "SAMP-A"})
    assert client.get("/api/sampling/cases?limit=0").status_code == 400
    assert client.get("/api/sampling/cases?limit=abc").status_code == 400
