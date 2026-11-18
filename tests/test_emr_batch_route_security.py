"""EMR 批次打包路由安全回歸測試（CR-01 路徑穿越、CR-02 假資料進入申報包）。"""

from __future__ import annotations

import pytest


@pytest.fixture
def api(make_api_app):
    return make_api_app()


@pytest.fixture
def client(api):
    with api.test_client() as c:
        yield c


def _post(client, payload):
    return client.post("/api/emr/batch-package", json=payload)


@pytest.mark.parametrize(
    "bad_code",
    ["../../../x", "/tmp/evil", "123", "35032504611", "35032504A1", "..\\..\\x"],
)
def test_facility_code_must_be_ten_digits(client, bad_code):
    """CR-01：非 10 碼數字的機構代碼必須在進入檔案系統前被拒絕。"""
    res = _post(client, {"target": "sampling", "facility_code": bad_code})
    assert res.status_code == 400
    assert "10 碼" in res.get_json()["message"]


def test_empty_database_does_not_fall_back_to_demo_cases(client):
    """CR-02：資料庫沒有案件時回 400，不得用展示病人產生 ZIP。"""
    res = _post(client, {"target": "sampling", "facility_code": "3503250461"})
    assert res.status_code == 400
    assert "無可供打包" in res.get_json()["message"]


def test_no_demo_import_in_route_module():
    """CR-02：路由模組不得再匯入展示資料。"""
    import elc_audit_engine.api.routes.emr_packaging as mod

    assert not hasattr(mod, "DEMO_SAMPLING_CASES")
    assert not hasattr(mod, "DEMO_APPEAL_CASES")
