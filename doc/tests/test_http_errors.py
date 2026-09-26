"""A-CR-08：HTTPException 不得被 Exception 兜底吞成 500。"""


def test_unknown_route_returns_404_json(client):
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    assert resp.get_json()["status"] == "error"


def test_malformed_json_returns_400_not_500(client):
    resp = client.post(
        "/api/sampling/audit",
        data="{bad json",
        headers={"Content-Type": "application/json", "X-API-Key": "valid-key-123"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["status"] == "error"


def test_wrong_method_returns_405(client):
    resp = client.delete("/api/sampling/audit")
    assert resp.status_code == 405
