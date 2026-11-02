"""Phase 20 測試：多案件聚合報告（20-01）、第 2→第 3 階連動（20-02）、全批次審查與 XML（20-03）。

測試資料為合成案件（MON-…、合成病患），以 CaseStore 暫存庫建立，附件與佐證庫指向暫存目錄。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from config import settings
from elc_audit_engine import attachment_store, evidence_vault
from elc_audit_engine.generators.sampling_xml import (
    SamplingXmlError,
    build_batch_sampling_xml,
)
from elc_audit_engine.unified_review_report import (
    ReviewCaseView,
    render_aggregated_review_html,
)

KEY = {"X-API-Key": "valid-key-123"}
BATCH = "MONTHLY-202307"


def _monthly_payload(index: int) -> dict:
    """合成的申報總檔案件（欄位形狀同 case_store/monthly.py）。"""
    return {
        "batch": BATCH,
        "case_class": "3",
        "case_seq": f"{index:04d}",
        "record_no": f"M{index:06d}",
        "patient_name": f"合成病患{index}",
        "birth_date": "0650101",
        "total_points": "2000",
        "clinic": "01",
        "doctor_code": "D1234",
        "visit_date": "1120718",
        "primary_diagnosis": "E119",
        "secondary_diagnoses": ["I10"],
        "orders": [
            {"p1": "01", "p2": "A", "p3": "2", "p4": f"14050{j}", "p5": "1", "p12": str(points), "p13": str(j + 1)}
            for j, points in enumerate([index * 10 + 1, index * 7 + 3, 5])
        ],
        "warnings": [],
    }


@pytest.fixture
def api(make_api_app, tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_store.settings, "ATTACHMENTS_DIR", str(tmp_path / "attachments"))
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "data"))
    app = make_api_app()
    store = app.extensions["elc"].case_store
    for index in range(1, 31):
        store.create(case_id=f"MON-{index:03d}", kind="monthly", payload=_monthly_payload(index))
    return app


@pytest.fixture
def client(api):
    with api.test_client() as c:
        yield c


@pytest.fixture
def sampled(client, api):
    """建立 30 筆第 2 階抽樣案件（20 隨機＋10 立意），回傳案件 ID 清單。"""
    res = client.post(
        "/api/sampling/sample-batch",
        json={"batch": BATCH, "random_count": 20, "intentional_count": 10, "seed": 42},
        headers=KEY,
    )
    assert res.status_code == 200
    return [case["id"] for case in res.get_json()["cases"]]


def _decode_export(body: bytes) -> ET.Element:
    text = body.decode("big5")
    assert text.startswith('<?xml version="1.0" encoding="Big5"?>')
    return ET.fromstring(re.sub(r"^<\?xml[^>]*\?>", "", text).strip())


# ── 20-01：聚合報告 ──────────────────────────────────────────


def _view(case_id: str, state: str) -> ReviewCaseView:
    return ReviewCaseView(
        case_id=case_id,
        stage=2,
        header={"病患": "合成", "醫令": "14050B", "醫令名稱": "HbA1c"},
        support_state=state,
    )


def test_aggregated_report_wraps_each_case_in_collapsed_details():
    html = render_aggregated_review_html(
        [_view("C-A", "充分"), _view("C-B", "裸奔")], title="批次", batch_label=BATCH
    )
    assert html.count('<details class="case-item">') == 2
    assert '<details class="case-item" open' not in html
    assert "C-A" in html and "C-B" in html


def test_aggregated_report_counts_states_and_labels_unreviewed():
    html = render_aggregated_review_html(
        [_view("C-1", "充分"), _view("C-2", None), _view("C-3", "充分")], title="批次"
    )
    assert "未審查" in html
    assert "<td>2</td>" in html  # 充分 兩案


def test_aggregated_report_empty_list_renders_placeholder():
    html = render_aggregated_review_html([], title="批次")
    assert "無案件" in html
    assert '<details class="case-item">' not in html


def test_batch_report_endpoint_lists_all_thirty_cases(client, sampled):
    res = client.get("/api/sampling/batch-report", headers=KEY)
    assert res.status_code == 200
    assert res.mimetype == "text/html"
    html = res.get_data(as_text=True)
    assert html.count('<details class="case-item">') == 30
    assert BATCH in html


# ── 20-03：全自動批次審查與全批次 XML ─────────────────────────


def test_batch_audit_processes_all_thirty_cases(client, api, sampled):
    res = client.post("/api/sampling/batch-audit", headers=KEY)
    assert res.status_code == 200
    data = res.get_json()
    assert data["total"] == 30
    assert data["completed"] + len(data["errors"]) == 30
    assert sum(data["by_state"].values()) == data["completed"]
    first = data["results"][0]["case_id"]
    assert api.extensions["elc"].case_store.get(first).payload["review"]["support_state"] == (
        data["results"][0]["support_state"]
    )


def test_batch_xml_is_single_outpatient_with_thirty_ddata(client, sampled):
    res = client.get("/api/sampling/export-batch-xml", headers=KEY)
    assert res.status_code == 200
    assert "attachment" in res.headers["Content-Disposition"]
    root = _decode_export(res.data)
    assert root.tag == "outpatient"
    assert root.find("tdata/t3").text == "11207"
    ddatas = root.findall("ddata")
    assert len(ddatas) == 30
    assert all(d.find("dbody/d3") is not None for d in ddatas)


def test_batch_xml_rejects_whole_batch_when_one_case_lacks_source(client, api, sampled):
    store = api.extensions["elc"].case_store
    payload = dict(store.get(sampled[3]).payload)
    payload.pop("monthly_source", None)
    store.update_payload(sampled[3], payload)

    res = client.get("/api/sampling/export-batch-xml", headers=KEY)
    assert res.status_code == 422
    assert sampled[3] in res.get_json()["message"]


def test_build_batch_xml_rejects_mixed_batches():
    source = {"case_class": "3", "case_seq": "1", "record_no": "M000001", "orders": [{"p4": "14050B", "p12": "1"}]}
    payloads = [
        {"id": "A", "batch": BATCH, "monthly_source": source},
        {"id": "B", "batch": "MONTHLY-202308", "monthly_source": source},
    ]
    with pytest.raises(SamplingXmlError, match="同一申報批次"):
        build_batch_sampling_xml(payloads)


def test_build_batch_xml_rejects_empty_input():
    with pytest.raises(SamplingXmlError):
        build_batch_sampling_xml([])


# ── 20-02：第 2 → 第 3 階連動 ─────────────────────────────────


def _appeal_ids(store):
    return {r.case_id for r in store.list_all(kind="appeal", limit=1000)}


def test_stage2_link_creates_five_appeal_cases_with_four_part_reason(client, api, sampled):
    store = api.extensions["elc"].case_store
    res = client.post("/api/appeal/sample-from-stage2", json={"count": 5, "seed": 7}, headers=KEY)
    assert res.status_code == 200
    data = res.get_json()
    assert len(data["selected"]) == 5
    assert sorted(data["created"]) == sorted(f"APL-S2-{case_id}" for case_id in data["selected"])
    assert data["duplicates"] == []
    assert _appeal_ids(store) == set(data["created"])

    appeal = store.get(data["created"][0]).payload
    assert appeal["source"] == "stage2"
    titles = [section["title"] for section in appeal["appeal_sections"]]
    assert len(titles) == 4
    assert titles[0].startswith("①") and titles[3].startswith("④")
    assert "appeal_reason1" in appeal and "appeal_reason2" in appeal


def test_stage2_link_is_idempotent_for_same_seed(client, api, sampled):
    first = client.post("/api/appeal/sample-from-stage2", json={"count": 5, "seed": 7}, headers=KEY).get_json()
    second = client.post("/api/appeal/sample-from-stage2", json={"count": 5, "seed": 7}, headers=KEY).get_json()
    assert second["selected"] == first["selected"]
    assert second["created"] == []
    assert sorted(second["duplicates"]) == sorted(first["created"])


def test_stage2_link_carries_labs_and_cloud_evidence(client, api, sampled):
    store = api.extensions["elc"].case_store
    target = sampled[0]
    payload = dict(store.get(target).payload)
    payload["lab_results"] = [{"name": "HbA1c", "value": "8.5", "unit": "%"}]
    payload["cloud_records"] = "外院跨院病歷：第二型糖尿病。"
    store.update_payload(target, payload)

    res = client.post("/api/appeal/sample-from-stage2", json={"count": 30, "seed": 1}, headers=KEY)
    assert res.status_code == 200
    appeal = store.get(f"APL-S2-{target}").payload
    assert appeal["multisource_evidence"]["labs"][0]["name"] == "HbA1c"
    assert appeal["multisource_evidence"]["cloud_sync"] == ["外院跨院病歷：第二型糖尿病。"]
    evidence_text = " ".join(
        section["text"] for section in appeal["appeal_sections"] if section["key"] == "evidence"
    )
    assert "HbA1c" in evidence_text


def test_stage2_link_rejects_out_of_range_count(client, sampled):
    assert client.post("/api/appeal/sample-from-stage2", json={"count": 0}, headers=KEY).status_code == 400
    assert client.post("/api/appeal/sample-from-stage2", json={"count": 31}, headers=KEY).status_code == 400


def test_stage2_link_does_not_change_source_review_state(client, api, sampled):
    store = api.extensions["elc"].case_store
    before = {cid: store.get(cid).payload.get("review") for cid in sampled}
    client.post("/api/appeal/sample-from-stage2", json={"count": 5, "seed": 3}, headers=KEY)
    after = {cid: store.get(cid).payload.get("review") for cid in sampled}
    assert before == after


def test_vault_is_not_required_for_linkage(client, api, sampled, tmp_path, monkeypatch):
    monkeypatch.setattr(evidence_vault.settings, "DATA_DIR", str(tmp_path / "data"))
    res = client.post("/api/appeal/sample-from-stage2", json={"count": 2, "seed": 9}, headers=KEY)
    assert res.status_code == 200
    assert len(res.get_json()["created"]) == 2
