"""Phase 29：當月申報流程改善——機構代碼批次、不覆寫院所設定、下載包（ZIP）與院所資料前置確認。

全部使用 `make_api_app`（暫存 CaseStore）與 `facility_config`／tmp 路徑隔離院所設定，不寫入正式 config/facility.json。
"""

from __future__ import annotations

import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from config import settings
from elc_audit_engine.monthly_audit import audit_batch
from elc_audit_engine.monthly_package import (
    build_batch_package,
    profile_status,
)
from elc_audit_engine.parsers.totfa import batch_name_from_header, split_monthly_batch_id
from elc_audit_engine.appeal_linkage import _fee_year_month

KEY = {"X-API-Key": "valid-key-123"}
FAC = "3503250461"
BATCH = f"MONTHLY-202307-{FAC}"


def _ddata(seq: int, *, dept: str, doctor: str, orders, total: str = "2000") -> str:
    pdatas = "".join(
        f"<pdata><p1>0</p1><p3>{cat}</p3><p4>{code}</p4><p10>1.0</p10>"
        f"<p11>{unit}</p11><p12>{points}</p12><p13>{i + 1}</p13></pdata>"
        for i, (code, cat, unit, points) in enumerate(orders)
    )
    return (
        f"<ddata><dhead><d1>02</d1><d2>{seq}</d2></dhead><dbody>"
        f"<d3>M{seq:04d}</d3><d8>{dept}</d8><d9>1120718</d9><d19>S00123A</d19>"
        f"<d30>{doctor}</d30><d39>{total}</d39><d49>測試病患</d49>{pdatas}</dbody></ddata>"
    )


def _zip_with_facility(cases: list[str], *, t2: str | None, t3: str = "11207") -> bytes:
    t2_xml = f"<t2>{t2}</t2>" if t2 is not None else ""
    text = (
        '<?xml version="1.0" encoding="Big5"?>\r\n<outpatient>\r\n'
        f"<tdata><t1>10</t1>{t2_xml}<t3>{t3}</t3></tdata>\r\n" + "\r\n".join(cases) + "\r\n</outpatient>\r\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("TOTFA.xml", text.encode("big5"))
    return buf.getvalue()


def _sample_zip(t2: str | None = FAC) -> bytes:
    return _zip_with_facility(
        [
            # 案 1：處置醫令 400 點（> 350，非藥品）→ 有處置醫令、無 SOAP 時應標示「尚未預生成」
            _ddata(1, dept="03", doctor="DOC_A", orders=[("TST1", "2", "1", "400"), ("PLAIN", "2", "1", "10")]),
            # 案 2：僅藥品、總點數 500 → 無處置醫令
            _ddata(2, dept="01", doctor="DOC_B", orders=[("TSTDRUG", "4", "0.00", "0")], total="500"),
        ],
        t2=t2,
    )


@pytest.fixture
def client(make_api_app):
    return make_api_app().test_client()


def _upload(client, data: bytes):
    return client.post(
        "/api/monthly/upload",
        headers=KEY,
        data={"file": (io.BytesIO(data), "TOTFA.zip")},
        content_type="multipart/form-data",
    )


# ── 批次 ID 與院所設定：純函式 ─────────────────────────────────────


def test_batch_name_includes_valid_facility_code():
    assert batch_name_from_header({"t2": FAC, "t3": "11207"}) == BATCH


def test_batch_name_falls_back_to_legacy_when_facility_missing_or_invalid():
    assert batch_name_from_header({"t3": "11207"}) == "MONTHLY-202307"
    # 含非英數字元的機構代碼不得進入批次名稱（防路徑與注入字元）
    assert batch_name_from_header({"t2": "../x", "t3": "11207"}) == "MONTHLY-202307"


def test_split_batch_id_accepts_legacy_and_suffixed_formats():
    assert split_monthly_batch_id("MONTHLY-202307") == ("202307", None)
    assert split_monthly_batch_id(BATCH) == ("202307", FAC)
    assert split_monthly_batch_id("MONTHLY-2023-07") is None
    assert split_monthly_batch_id("MONTHLY-202307-bad code") is None


def test_fee_year_month_reads_suffixed_batch():
    assert _fee_year_month(BATCH) == "202307"
    assert _fee_year_month("MONTHLY-202307") == "202307"
    assert _fee_year_month("not-a-batch") is None


def test_profile_status_requires_fields_and_explicit_confirmation():
    full = {"code": FAC, "name": "院所", "email": "a@b.tw"}
    assert profile_status(full).complete is True
    assert profile_status(full).ready is False  # 尚未確認
    assert profile_status(dict(full, profile_confirmed=True)).ready is True
    # 字串 "true" 不算確認（只接受布林 True）
    assert profile_status(dict(full, profile_confirmed="true")).ready is False
    missing = profile_status({"code": FAC, "profile_confirmed": True})
    assert missing.ready is False
    assert set(missing.missing) == {"name", "email"}


# ── 上傳：不覆寫本院院所設定 ───────────────────────────────────────


def test_upload_with_foreign_facility_keeps_clinic_profile(make_api_app, facility_config, tmp_path):
    client = make_api_app().test_client()
    resp = _upload(client, _sample_zip(FAC))
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["batch"] == BATCH
    assert body["facility_code"] == FAC
    assert body["foreign_facility"] is True
    # 本院設定（facility_config fixture 的 01015C）未被改寫
    assert settings.load_facility_config()["code"] == facility_config["code"]


def test_upload_initializes_facility_code_when_unset(make_api_app, tmp_path, monkeypatch):
    path = tmp_path / "facility.json"
    monkeypatch.setattr(settings, "FACILITY_CONFIG_PATH", str(path), raising=False)
    client = make_api_app().test_client()
    body = _upload(client, _sample_zip(FAC)).get_json()
    assert body["foreign_facility"] is False
    assert json.loads(path.read_text(encoding="utf-8"))["code"] == FAC


def test_upload_same_facility_is_not_foreign(make_api_app, facility_config):
    client = make_api_app().test_client()
    body = _upload(client, _sample_zip(facility_config["code"])).get_json()
    assert body["foreign_facility"] is False


# ── 院所確認旗標（POST /api/facility）──────────────────────────────


def test_facility_post_stores_profile_confirmed_flag(client, facility_config):
    resp = client.post(
        "/api/facility",
        headers=KEY,
        json={"source": "web", "code": "01015C", "name": "測試", "email": "a@b.tw", "profile_confirmed": True},
    )
    assert resp.status_code == 200
    assert settings.load_facility_config()["profile_confirmed"] is True


# ── 下載包：前置條件與內容 ─────────────────────────────────────────


def test_package_requires_confirmed_facility_profile(make_api_app, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "FACILITY_CONFIG_PATH", str(tmp_path / "none.json"), raising=False)
    client = make_api_app().test_client()
    _upload(client, _sample_zip(FAC))  # 建立批次（院所尚未設定 → 由 zip 初始化代碼但缺名稱與信箱）
    resp = client.get(f"/api/monthly/batch/{BATCH}/package", headers=KEY)
    assert resp.status_code == 412
    body = resp.get_json()
    assert body["code"] == "facility_profile_required"
    assert {"name", "email"} <= set(body["missing"])
    assert body["confirmed"] is False


def test_package_after_confirmation_returns_zip_with_report_and_case_docs(make_api_app, facility_config):
    client = make_api_app().test_client()
    _upload(client, _sample_zip(FAC))
    # 首次確認院所資料（診所表單）
    confirm = client.post(
        "/api/facility",
        headers=KEY,
        json={"source": "web", "code": facility_config["code"], "name": facility_config["name"],
              "email": "clinic@example.tw", "profile_confirmed": True},
    )
    assert confirm.status_code == 200

    resp = client.get(f"/api/monthly/batch/{BATCH}/package", headers=KEY)
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    assert f"monthly_package_{BATCH}.zip" in resp.headers["Content-Disposition"]

    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        names = zf.namelist()
        assert "報告.html" in names
        case_docs = [n for n in names if n.startswith("病歷/") and n.endswith(".html")]
        assert len(case_docs) == 2  # 每筆申報案件一份病歷文件
        report = zf.read("報告.html").decode("utf-8")
        assert facility_config["name"] in report  # 院所資料已帶入報告

        docs = {n: zf.read(n).decode("utf-8") for n in case_docs}
    # 案 1 有處置醫令、無 SOAP、無快取範本 → 明確標示未預生成（不捏造）
    assert any("尚未預生成" in text and "TST1" in text for text in docs.values())
    # 案 2 僅藥品 → 不產生範例病歷，並明確說明
    assert any("無處置／手術高價醫令" in text for text in docs.values())


def test_package_uses_cached_template_for_case_without_soap(make_api_app, facility_config):
    app = make_api_app()
    store = app.extensions["elc"].case_store
    client = app.test_client()
    _upload(client, _sample_zip(FAC))

    # 找出含處置醫令之案件的主診斷，並寫入一筆快取範本（模擬已預生成）
    audit = audit_batch(store, BATCH, persist=False)
    target = next(c for c in audit.cases if any(f.code == "TST1" for f in c.findings))
    dx = target.primary_diagnosis or ""
    if not dx:
        pytest.skip("fixture 案件無主診斷，無法對應快取範本")
    store.put_soap_template(
        "TST1", dx,
        {"s": "Patient reports a synthetic test complaint.", "o": "Synthetic objective finding.",
         "a": "Synthetic assessment (S61.2).", "p": "Synthetic plan."},
        source="test", quality_score=90,
    )
    client.post(
        "/api/facility",
        headers=KEY,
        json={"source": "web", "code": facility_config["code"], "name": facility_config["name"],
              "email": "clinic@example.tw", "profile_confirmed": True},
    )
    resp = client.get(f"/api/monthly/batch/{BATCH}/package", headers=KEY)
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        doc = zf.read(f"病歷/{target.case_id}.html").decode("utf-8")
    assert "範例病歷（依申報醫令預生成" in doc
    assert "Synthetic objective finding." in doc
    assert "非實際病歷" in doc


def test_package_unknown_batch_is_404_not_400(client, facility_config):
    resp = client.get("/api/monthly/batch/MONTHLY-209901-3503250461/package", headers=KEY)
    assert resp.status_code == 404


def test_package_rejects_malformed_batch_id(client, facility_config):
    resp = client.get("/api/monthly/batch/MONTHLY-2023-07/package", headers=KEY)
    assert resp.status_code == 400


def test_build_package_refuses_incomplete_profile(make_api_app):
    from elc_audit_engine.monthly_package import FacilityProfileError

    store = make_api_app().extensions["elc"].case_store
    with pytest.raises(FacilityProfileError):
        build_batch_package(store, BATCH, facility={"code": FAC})


# ── 單案文件：SOAP 優先（單元）─────────────────────────────────────


def test_case_document_pastes_existing_soap_first():
    from elc_audit_engine.monthly_package import _case_document

    case = SimpleNamespace(
        case_id="MON-1", case_seq="1", patient_id="M1", patient_name="測", visit_date="1120718",
        department="03", primary_diagnosis="S61.2", findings=(),
    )
    payload = {"soap": {"s": "S text", "o": "O text", "a": "A text", "p": "P text"}, "record_no": "M1"}
    doc = _case_document(store=None, case=case, record_payload=payload, templates={})
    assert "門診 SOAP（語音比對）" in doc
    assert "S text" in doc and "P text" in doc
    assert "範例病歷" not in doc


def test_case_document_escapes_html_in_soap():
    from elc_audit_engine.monthly_package import _case_document

    case = SimpleNamespace(
        case_id="MON-2", case_seq="2", patient_id=None, patient_name=None, visit_date=None,
        department=None, primary_diagnosis=None, findings=(),
    )
    doc = _case_document(store=None, case=case, record_payload={"soap_text": "<script>x</script>"}, templates={})
    assert "<script>x</script>" not in doc
    assert "&lt;script&gt;" in doc


def test_pregen_target_covers_payment_restricted_orders():
    from elc_audit_engine.monthly_audit import STATUS_RESTRICTION, OrderFinding
    from elc_audit_engine.monthly_pregen import is_pregen_target

    def _f(code, *, status, flags=(), category="2"):
        return OrderFinding(
            order_seq="1", code=code, category=category, points="10", unit_price=None,
            flags=tuple(flags), rule_status=status,
        )

    # 給付限制醫令即使點數不高也須有範本
    assert is_pregen_target(_f("RESTR1", status=STATUS_RESTRICTION)) is True
    # 一般醫令（無限制、無高價旗標）不產生範本目標
    assert is_pregen_target(_f("PLAIN1", status="no_restriction_markers")) is False
    # 診療費（001 開頭）排除
    assert is_pregen_target(_f("001123C", status=STATUS_RESTRICTION)) is False
