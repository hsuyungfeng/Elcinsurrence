"""Plan 15-04：處置／手術範例病歷預生成、DB 快取、品質檢核與報告內嵌（單元＋整合）。

LLM 皆以假函式取代，測試不連網路、不呼叫本機模型。
"""

from __future__ import annotations

import io
import sqlite3
import zipfile

import pytest

from elc_audit_engine.case_store.store import CaseStore, CaseStoreError
from elc_audit_engine.comparator.soap_advice import validate_soap_quality
from elc_audit_engine.monthly_audit import BatchAudit, aggregate_batch, audit_case
from elc_audit_engine.monthly_pregen import (
    STATUS_CACHE,
    STATUS_GENERATED,
    STATUS_QUALITY_FAILED,
    STATUS_UNDETERMINED,
    is_procedure_finding,
    load_templates,
    pregen_batch,
    pregen_template,
    procedure_targets,
)
from elc_audit_engine.monthly_report_html import render_batch_report_html
from elc_audit_engine.rule_repository.models import RuleResult, not_found

KEY = {"X-API-Key": "valid-key-123"}
BATCH = "MONTHLY-202307"

# 總字元數須落在 500–1000（見 comparator/soap_advice.py 與 LLM 系統提示）；
# 舊版固定樣本僅約 330 字元，於 phase-18 加入總長檢核後即不合格，故擴充樣本。
GOOD_SOAP = {
    "s": (
        "Patient reports painful nail bed injury of the right index finger after a machine accident "
        "at the workshop about two hours before arrival. Pain is rated 6 out of 10 and worse with "
        "movement. No prior injury to the same digit. Tetanus status reviewed and documented as up to date."
    ),
    "o": (
        "Nail bed laceration about 1.5 cm with partial nail plate avulsion over the right index finger. "
        "Capillary refill is brisk and neurovascular status is intact distally. No active bleeding after "
        "compression. Surrounding soft tissue shows mild swelling without signs of infection."
    ),
    "a": (
        "Traumatic nail bed injury with nail plate avulsion of the right index finger (S61.2). "
        "No open fracture of the distal phalanx on initial assessment."
    ),
    "p": (
        "Nail bed repair under digital block with absorbable sutures; nail plate reposition and splinting "
        "applied. Wound care instructions given, including daily dressing change and elevation. Oral "
        "analgesics prescribed. Follow-up in one week for wound check and suture assessment."
    ),
}
GOOD_REPLY = {"status": "success", "comparison": "中文比對說明", "recommended_soap": GOOD_SOAP,
              "approval_advice": "中文審批建議"}


def _rule(code: str, text: str) -> RuleResult:
    return RuleResult(code=code, source="payment", name=f"合成{code}", payment_text=text,
                      effective_from="2023-01-01", effective_to="2910-12-31", article_location=None,
                      article_full_text=None, article_source=None, found=True)


# ── 1. 品質檢核 validate_soap_quality ─────────────────────────────


def test_good_english_soap_passes_with_high_score():
    result = validate_soap_quality(GOOD_SOAP)
    assert result["pass"] is True
    assert result["quality_score"] >= 90
    assert result["issues"] == []


@pytest.mark.parametrize("missing", ["s", "o", "a", "p"])
def test_missing_section_fails(missing):
    soap = {k: v for k, v in GOOD_SOAP.items() if k != missing}
    result = validate_soap_quality(soap)
    assert result["pass"] is False
    assert any(i["code"] == "missing" and i["section"] == missing for i in result["issues"])


@pytest.mark.parametrize("placeholder", [
    "Pending physician input.", "Not documented in source record.", "Information missing.",
    "[insert finding here]", "TBD", "待補",
])
def test_placeholder_text_fails(placeholder):
    soap = dict(GOOD_SOAP, o=placeholder + " Additional padding text to exceed the minimum length.")
    result = validate_soap_quality(soap)
    assert result["pass"] is False
    assert any(i["code"] == "placeholder" for i in result["issues"])


def test_chinese_heavy_section_fails_language_check():
    soap = dict(GOOD_SOAP, s="病患因機器受傷右手食指指甲床撕裂，疼痛明顯，需要門診進一步處置與縫合。")
    result = validate_soap_quality(soap)
    assert result["pass"] is False
    assert any(i["code"] == "not_english" for i in result["issues"])


def test_too_short_section_fails():
    result = validate_soap_quality(dict(GOOD_SOAP, p="Repair."))
    assert result["pass"] is False
    assert any(i["code"] == "too_short" for i in result["issues"])


def test_missing_icd_in_assessment_is_only_a_deduction():
    result = validate_soap_quality(dict(GOOD_SOAP, a="Traumatic nail bed injury with nail plate avulsion."))
    assert result["pass"] is True
    assert result["quality_score"] == 95
    assert any(i["code"] == "no_icd10" for i in result["issues"])


def test_non_dict_input_fails_safely():
    result = validate_soap_quality("not a dict")
    assert result == {"pass": False, "quality_score": 0,
                      "issues": [{"section": "*", "code": "not_a_dict", "detail": "SOAP 非物件"}]}


# ── 2. DB 快取（soap_templates） ──────────────────────────────────


@pytest.fixture
def store(tmp_path) -> CaseStore:
    return CaseStore(db_path=str(tmp_path / "cases.sqlite3"))


def test_template_round_trip(store):
    store.put_soap_template("64140C", "S61.2", GOOD_SOAP, source="llm_validated", quality_score=95)
    cached = store.get_soap_template("64140C", "S61.2")
    assert cached["soap"] == GOOD_SOAP
    assert cached["source"] == "llm_validated"
    assert cached["quality_score"] == 95


def test_template_key_is_normalized(store):
    store.put_soap_template("64140c", "s61.2", GOOD_SOAP, source="llm_validated", quality_score=95)
    assert store.get_soap_template(" 64140C ", "S61.2") is not None


def test_template_overwrite_records_physician_edit(store):
    store.put_soap_template("64140C", "S61.2", GOOD_SOAP, source="llm_validated", quality_score=95)
    edited = dict(GOOD_SOAP, p="Edited by physician: nail bed repair with 6-0 nylon.")
    store.put_soap_template("64140C", "S61.2", edited, source="physician_edited", quality_score=None)
    cached = store.get_soap_template("64140C", "S61.2")
    assert cached["soap"]["p"].startswith("Edited by physician")
    assert cached["source"] == "physician_edited"


def test_template_missing_order_code_is_rejected(store):
    with pytest.raises(CaseStoreError):
        store.get_soap_template("", "S61.2")
    with pytest.raises(CaseStoreError):
        store.put_soap_template("  ", "S61.2", GOOD_SOAP, source="llm_validated", quality_score=95)


def test_general_template_with_empty_diagnosis_can_be_stored(store):
    store.put_soap_template("64140C", "", GOOD_SOAP, source="llm_validated", quality_score=95)
    general = store.get_soap_template("64140C", "", fallback_general=False)
    assert general["soap"] == GOOD_SOAP and general["scope"] == "general"


# ── 通用範本回退（Plan 15-05） ────────────────────────────────────


def test_specific_miss_falls_back_to_general_template(store):
    store.put_soap_template("64140C", "", GOOD_SOAP, source="llm_validated", quality_score=95)
    hit = store.get_soap_template("64140C", "S61.2")
    assert hit["soap"] == GOOD_SOAP
    assert hit["scope"] == "general"


def test_specific_template_takes_precedence_over_general(store):
    store.put_soap_template("64140C", "", GOOD_SOAP, source="llm_validated", quality_score=95)
    specific = dict(GOOD_SOAP, p="Specific plan for this diagnosis, nail bed repair.")
    store.put_soap_template("64140C", "S61.2", specific, source="physician_edited", quality_score=None)
    hit = store.get_soap_template("64140C", "S61.2")
    assert hit["soap"] == specific
    assert hit["scope"] == "specific"


def test_fallback_can_be_disabled(store):
    store.put_soap_template("64140C", "", GOOD_SOAP, source="llm_validated", quality_score=95)
    assert store.get_soap_template("64140C", "S61.2", fallback_general=False) is None


def test_fallback_miss_returns_none(store):
    assert store.get_soap_template("NOPE", "S61.2") is None


def test_pregen_uses_general_cache_without_calling_llm(store):
    store.put_soap_template("64140C", "", GOOD_SOAP, source="llm_validated", quality_score=95)
    calls: list = []
    outcome = pregen_template(store, order_code="64140C", order_name="甲床重建",
                              primary_diagnosis="S61.2", generator=_fake(calls=calls))
    assert outcome.status == STATUS_CACHE
    assert calls == []


def test_report_embeds_general_template_for_specific_diagnosis(store):
    store.put_soap_template("PROC1", "", GOOD_SOAP, source="llm_validated", quality_score=95)
    batch = _batch(_case("A", "S61.2", [_proc("PROC1")]))
    loaded = load_templates(store, batch)
    assert loaded[("PROC1", "S61.2")] == GOOD_SOAP
    html = render_batch_report_html(batch, templates=loaded)
    assert "S: Patient reports" in html


def test_his_soap_enhance_serves_cached_template_without_llm(make_api_app, monkeypatch):
    from elc_audit_engine.api.routes import his_integration
    from elc_audit_engine.rule_repository.models import RuleResult as _RR

    calls: list = []
    monkeypatch.setattr(his_integration, "generate_soap_advice", _fake(calls=calls))
    monkeypatch.setattr(his_integration, "get_rule", lambda code, db_path=None: _RR(
        code=code, source="payment", name="甲床重建", payment_text="限外傷。", effective_from=None,
        effective_to=None, article_location=None, article_full_text=None, article_source=None, found=True))
    app = make_api_app()
    app.extensions["elc"].case_store.put_soap_template("64140C", "", GOOD_SOAP, source="llm_validated", quality_score=95)
    with app.test_client() as client:
        res = client.post("/api/his/v1/cases/soap-enhance", headers=KEY,
                          json={"order_code": "64140C", "primary_diagnosis": "S61.2"})
    data = res.get_json()
    assert res.status_code == 200
    assert data["status"] == "success" and data["from_cache"] is True
    assert data["template_scope"] == "general"
    assert "S: Patient reports" in data["example_soap_template"]
    assert calls == []  # 命中快取，不呼叫 LLM


def test_template_table_exists_in_existing_database(tmp_path):
    """既有資料庫升級：init_schema 冪等建立 soap_templates 表。"""
    path = str(tmp_path / "old.sqlite3")
    CaseStore(db_path=path)
    CaseStore(db_path=path)  # 再次初始化不得失敗
    conn = sqlite3.connect(path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "soap_templates" in names


# ── 3. 預生成與快取（pregen_template） ─────────────────────────────


def _fake(reply=None, calls=None):
    def _gen(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        if isinstance(reply, Exception):
            raise reply
        return reply if reply is not None else dict(GOOD_REPLY)
    return _gen


def test_cache_hit_does_not_call_llm(store):
    store.put_soap_template("64140C", "S61.2", GOOD_SOAP, source="llm_validated", quality_score=95)
    calls: list = []
    outcome = pregen_template(store, order_code="64140C", order_name="甲床重建", primary_diagnosis="S61.2",
                              generator=_fake(calls=calls))
    assert outcome.status == STATUS_CACHE
    assert calls == []
    assert outcome.soap == GOOD_SOAP


def test_miss_generates_validates_and_stores(store):
    calls: list = []
    outcome = pregen_template(store, order_code="64140C", order_name="甲床重建", primary_diagnosis="S61.2",
                              rule_text="限外傷。", generator=_fake(calls=calls))
    assert outcome.status == STATUS_GENERATED
    assert len(calls) == 1 and calls[0]["rule_text"] == "限外傷。"
    stored = store.get_soap_template("64140C", "S61.2")
    assert stored["source"] == "llm_validated"
    assert stored["soap"]["a"].startswith("Traumatic")


def test_quality_failure_is_not_cached(store):
    bad = dict(GOOD_REPLY, recommended_soap=dict(GOOD_SOAP, o="Pending exam."))
    outcome = pregen_template(store, order_code="64140C", order_name="x", primary_diagnosis="S61.2",
                              generator=_fake(reply=bad))
    assert outcome.status == STATUS_QUALITY_FAILED
    assert outcome.quality["pass"] is False
    assert store.get_soap_template("64140C", "S61.2") is None


def test_llm_error_is_undetermined_and_not_cached(store):
    outcome = pregen_template(store, order_code="64140C", order_name="x", primary_diagnosis="S61.2",
                              generator=_fake(reply={"status": "error", "recommended_soap": {}}))
    assert outcome.status == STATUS_UNDETERMINED
    assert store.get_soap_template("64140C", "S61.2") is None


def test_force_regenerates_over_cache(store):
    store.put_soap_template("64140C", "S61.2", GOOD_SOAP, source="physician_edited", quality_score=None)
    calls: list = []
    outcome = pregen_template(store, order_code="64140C", order_name="x", primary_diagnosis="S61.2",
                              force=True, generator=_fake(calls=calls))
    assert outcome.status == STATUS_GENERATED and len(calls) == 1


# ── 4. 批次目標與上限 ─────────────────────────────────────────────


def _case(case_id: str, dx: str, orders: list[dict], total: str = "2000"):
    payload = {"batch": BATCH, "case_seq": case_id, "visit_date": "1120718", "total_points": total,
               "primary_diagnosis": dx, "secondary_diagnoses": [], "orders": orders}
    return audit_case(case_id, payload, lookup=_lookup)


def _lookup(code: str) -> RuleResult:
    if code in ("PROC1", "PROC2", "DRUG1"):
        return _rule(code, "限外傷使用，需檢附病歷。")
    return not_found(code)


def _proc(code: str, points: str = "500", cat: str = "2", seq: str = "1", unit: str = "1") -> dict:
    return {"p3": cat, "p4": code, "p10": "1.0", "p11": unit, "p12": points, "p13": seq}


def _batch(*cases) -> BatchAudit:
    flagged = tuple(c for c in cases if c.findings)
    return BatchAudit(batch=BATCH, cases_total=len(cases), cases=flagged, report=aggregate_batch(len(cases), flagged))


def test_restricted_orders_are_targets_and_unflagged_low_points_are_not():
    # Phase 29：範本目標 = 處置高價醫令 ∪ 所有給付限制（restriction_present）醫令。
    # 本例 PROC1、DRUG1 皆有給付限制 → 皆為目標；PROC2（≤350 點、無旗標）不成為 finding。
    batch = _batch(_case("A", "S61.2", [
        _proc("PROC1", points="500"),          # 處置 >350 且有給付限制 ✓
        _proc("DRUG1", points="400", cat="4", unit="6.00", seq="2"),  # 限制藥品 ✓
        _proc("PROC2", points="300", seq="3"),  # 無旗標、不列入
    ]))
    assert [t[0] for t in procedure_targets(batch)] == ["PROC1", "DRUG1"]
    assert all(is_procedure_finding(f) for c in batch.cases for f in c.findings if f.code == "PROC1")


def test_targets_are_unique_per_code_and_diagnosis():
    batch = _batch(
        _case("A", "S61.2", [_proc("PROC1", seq="1")]),
        _case("B", "S61.2", [_proc("PROC1", seq="1")]),  # 同醫令同診斷：只一份
        _case("C", "S52.1", [_proc("PROC1", seq="1")]),  # 不同診斷：另一份
    )
    assert len(procedure_targets(batch)) == 2


def test_batch_pregen_respects_limit_and_reuses_cache(store):
    batch = _batch(
        _case("A", "S61.2", [_proc("PROC1")]),
        _case("B", "S61.2", [_proc("PROC2", seq="2")]),
        _case("C", "S52.1", [_proc("PROC1", seq="1")]),
    )
    calls: list = []
    first = pregen_batch(store, batch, limit=2, generator=_fake(calls=calls))
    assert first["targets"] == 3
    assert first["generated"] == 2 and first["skipped_limit"] == 1
    assert len(calls) == 2

    second = pregen_batch(store, batch, limit=5, generator=_fake(calls=calls))
    assert second["cached"] == 2 and second["generated"] == 1
    assert len(calls) == 3  # 快取命中不再呼叫 LLM


def test_load_templates_returns_only_cached_targets(store):
    batch = _batch(_case("A", "S61.2", [_proc("PROC1")]), _case("B", "S52.1", [_proc("PROC2", seq="2")]))
    store.put_soap_template("PROC1", "S61.2", GOOD_SOAP, source="llm_validated", quality_score=95)
    loaded = load_templates(store, batch)
    assert list(loaded) == [("PROC1", "S61.2")]


# ── 5. 報告內嵌與複製 ─────────────────────────────────────────────


def test_report_embeds_cached_template_with_copy_and_editable_text(store):
    batch = _batch(_case("A", "S61.2", [_proc("PROC1")]))
    templates = {("PROC1", "S61.2"): GOOD_SOAP}
    html = render_batch_report_html(batch, templates=templates)
    assert '<details class="soap-example">' in html
    assert "<textarea" in html and "S: Patient reports" in html
    assert 'onclick="copySoap(this)"' in html
    assert "function copySoap" in html  # 內嵌複製腳本


def test_no_empty_box_when_procedure_has_no_template():
    batch = _batch(_case("A", "S61.2", [_proc("PROC1")]))
    html = render_batch_report_html(batch, templates={})
    assert 'class="soap-example"' not in html
    assert "<textarea" not in html


def test_drug_never_gets_example_even_if_a_template_exists():
    batch = _batch(_case("A", "S61.2", [_proc("DRUG1", points="400", cat="4", unit="6.00")]))
    html = render_batch_report_html(batch, templates={("DRUG1", "S61.2"): GOOD_SOAP})
    assert 'class="soap-example"' not in html


def test_template_text_is_escaped_in_report():
    batch = _batch(_case("A", "S61.2", [_proc("PROC1")]))
    evil = dict(GOOD_SOAP, s="<script>alert(1)</script> injected text here for length")
    html = render_batch_report_html(batch, templates={("PROC1", "S61.2"): evil})
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


# ── 6. API 整合：上傳 → 預生成 → 報告內嵌 ─────────────────────────


def _zip_bytes() -> bytes:
    def ddata(seq, dx, pdatas):
        return (f"<ddata><dhead><d1>02</d1><d2>{seq}</d2></dhead><dbody><d3>A123456789</d3><d8>03</d8>"
                f"<d9>1120718</d9><d19>{dx}</d19><d30>DOC</d30><d39>2000</d39><d49>測試病患</d49>"
                f"{pdatas}</dbody></ddata>")

    proc = ("<pdata><p1>0</p1><p3>2</p3><p4>PROC1</p4><p10>1.0</p10><p11>1</p11>"
            "<p12>500</p12><p13>1</p13></pdata>")
    text = ('<?xml version="1.0" encoding="Big5"?>\r\n<outpatient>\r\n'
            "<tdata><t1>10</t1><t3>11207</t3></tdata>\r\n" + ddata(1, "S61.2", proc) + "\r\n</outpatient>\r\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("TOTFA.xml", text.encode("big5"))
    return buf.getvalue()


@pytest.fixture
def api(make_api_app, tmp_path, monkeypatch):
    rules_db = str(tmp_path / "rules.sqlite3")
    from elc_audit_engine.rule_repository.db import (
        SCHEMA_DRUG,
        SCHEMA_PAYMENT,
        SCHEMA_RULE_MAPPING,
    )

    conn = sqlite3.connect(rules_db)
    for ddl in (SCHEMA_PAYMENT, SCHEMA_DRUG, SCHEMA_RULE_MAPPING):
        conn.execute(ddl)
    conn.execute("INSERT INTO payment_rules VALUES ('PROC1','甲床重建','限外傷使用，需檢附病歷。','2023-01-01','2910-12-31')")
    conn.commit()
    conn.close()

    from elc_audit_engine import monthly_pregen

    calls: list = []
    monkeypatch.setattr(monthly_pregen, "generate_soap_advice", _fake(calls=calls))
    app = make_api_app(ELC_RULES_DB_PATH=rules_db)
    app.test_calls = calls  # type: ignore[attr-defined]
    return app


@pytest.fixture
def client(api):
    with api.test_client() as c:
        c.post("/api/monthly/upload", data={"file": (io.BytesIO(_zip_bytes()), "TOTFA.zip")},
               headers=KEY, content_type="multipart/form-data")
        yield c


def test_pregen_endpoint_requires_api_key(client):
    assert client.post(f"/api/monthly/batch/{BATCH}/pregen").status_code == 401


def test_pregen_endpoint_validates_limit(client):
    assert client.post(f"/api/monthly/batch/{BATCH}/pregen?limit=0", headers=KEY).status_code == 400
    assert client.post(f"/api/monthly/batch/{BATCH}/pregen?limit=abc", headers=KEY).status_code == 400


def test_pregen_endpoint_unknown_batch_is_404(client):
    assert client.post("/api/monthly/batch/MONTHLY-209901/pregen", headers=KEY).status_code == 404


def test_upload_then_pregen_then_report_embeds_example(client, api):
    res = client.post(f"/api/monthly/batch/{BATCH}/pregen?limit=5", headers=KEY)
    assert res.status_code == 200
    counts = res.get_json()
    assert counts["targets"] == 1 and counts["generated"] == 1
    assert len(api.test_calls) == 1

    html = client.get(f"/api/monthly/batch/{BATCH}/report?format=html", headers=KEY).get_data(as_text=True)
    assert '<details class="soap-example">' in html
    assert "Nail bed repair" in html  # 範本內容已內嵌

    # 再次預生成：快取命中，不再呼叫 LLM
    again = client.post(f"/api/monthly/batch/{BATCH}/pregen?limit=5", headers=KEY).get_json()
    assert again["cached"] == 1 and again["generated"] == 0
    assert len(api.test_calls) == 1


def test_template_endpoint_returns_cache_status_without_llm(client, api):
    body = {"order_code": "PROC1", "primary_diagnosis": "S61.2"}
    first = client.post("/api/monthly/template", headers=KEY, json=body)
    assert first.status_code == 200 and first.get_json()["status"] == STATUS_GENERATED
    second = client.post("/api/monthly/template", headers=KEY, json=body)
    assert second.get_json()["status"] == STATUS_CACHE
    assert len(api.test_calls) == 1


def test_template_endpoint_quality_failure_is_422_and_not_stored(client, api, monkeypatch):
    from elc_audit_engine import monthly_pregen

    bad = dict(GOOD_REPLY, recommended_soap=dict(GOOD_SOAP, s="待補"))
    monkeypatch.setattr(monthly_pregen, "generate_soap_advice", _fake(reply=bad))
    res = client.post("/api/monthly/template", headers=KEY,
                      json={"order_code": "PROC9", "primary_diagnosis": "S61.2"})
    assert res.status_code == 422
    assert res.get_json()["status"] == "quality_failed"


def test_template_endpoint_llm_failure_is_503(client, monkeypatch):
    from elc_audit_engine import monthly_pregen

    monkeypatch.setattr(monthly_pregen, "generate_soap_advice", _fake(reply={"status": "error", "recommended_soap": {}}))
    res = client.post("/api/monthly/template", headers=KEY,
                      json={"order_code": "PROC1", "primary_diagnosis": "S52.1", "force": True})
    assert res.status_code == 503
    assert res.get_json()["status"] == "undetermined"


def test_template_endpoint_requires_fields(client):
    assert client.post("/api/monthly/template", headers=KEY, json={"order_code": "PROC1"}).status_code == 400


# ── 7. 病理檢驗排除（25003C、25004C 及 25 開頭） ───────────────────


@pytest.mark.parametrize("code", ["25003C", "25004C", "25001C", " 25003c "])
def test_pathology_codes_are_not_procedure_findings(code):
    from elc_audit_engine.monthly_pregen import is_pathology_code

    assert is_pathology_code(code)
    finding = audit_case("P", _payload_for(code), lookup=_lookup).findings[0]
    assert not is_procedure_finding(finding)


def test_surgical_code_is_still_a_procedure_finding():
    finding = audit_case("S", _payload_for("PROC1"), lookup=_lookup).findings[0]
    assert is_procedure_finding(finding)
    assert not __import__("elc_audit_engine.monthly_pregen", fromlist=["x"]).is_pathology_code("64140C")


def _payload_for(code: str) -> dict:
    return {"batch": BATCH, "case_seq": "1", "visit_date": "1120718", "total_points": "2000",
            "primary_diagnosis": "S61.2", "secondary_diagnoses": [],
            "orders": [_proc(code, points="500")]}


def test_pathology_excluded_from_targets_and_report_even_if_template_stored(store):
    batch = _batch(_case("A", "S61.2", [_proc("25003C"), _proc("PROC1", seq="2")]))
    assert [t[0] for t in procedure_targets(batch)] == ["PROC1"]
    store.put_soap_template("25003C", "S61.2", GOOD_SOAP, source="llm_validated", quality_score=95)
    html = render_batch_report_html(batch, templates=load_templates(store, batch))
    assert "S: Patient reports" not in html  # 病理項目即使有快取也不輸出
    assert 'class="soap-example"' not in html


def test_script_collector_excludes_pathology(tmp_path):
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "pregen_monthly_procedures.py"
    spec = importlib.util.spec_from_file_location("pregen_monthly_procedures", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    batch = _batch(_case("A", "S61.2", [_proc("25003C"), _proc("25004C", seq="2"), _proc("PROC1", seq="3")]))
    codes = [code for code, _name, _text in module.collect_general_targets(batch)]
    assert codes == ["PROC1"]
