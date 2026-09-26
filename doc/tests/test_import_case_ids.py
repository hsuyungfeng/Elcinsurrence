"""A-CR-02：第二批不同內容的匯入不得因 id 從 0001 起算而被全數拒收。"""
import io

import server

HEADERS = {"X-API-Key": "valid-key-123"}
HEADER_ROW = "流水號,病歷號,病患姓名,醫令代碼,醫令名稱,就醫日期,科別,SOAP\n"


def _import(client, body: str, name: str):
    data = {"file": (io.BytesIO((HEADER_ROW + body).encode("utf-8-sig")), name)}
    return client.post("/api/sampling/import", data=data, headers=HEADERS,
                       content_type="multipart/form-data").get_json()


def test_second_batch_with_different_rows_is_persisted(client):
    r1 = _import(client, "101,M1001,王小明,14050B,HbA1c,20260701,家醫科,S: DM\n", "a.csv")
    r2 = _import(client, "205,M2002,陳小華,09005C,血糖,20260805,內科,S: DM\n", "b.csv")
    assert r1["case_store_persisted"] == 1
    assert r2["case_store_persisted"] == 1
    assert r2["case_store_conflicts"] == []
    ids = {c.case_id for c in server._case_store.list_all(kind="sampling")}
    assert len(ids) == 2


def test_rows_differing_only_in_patient_get_distinct_ids(client):
    r = _import(
        client,
        "1,M1,甲,14050B,HbA1c,20260701,家醫科,S\n"
        "1,M2,乙,14050B,HbA1c,20260701,家醫科,S\n",
        "c.csv",
    )
    assert r["case_store_persisted"] == 2
