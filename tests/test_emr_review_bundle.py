"""EMR 審查包（XML 核算＋HTML 審查，影像內嵌）：檔名規範、ZIP 命名、影像縮圖、切包。"""

from __future__ import annotations

import base64
import io
import re
import zipfile

import pytest
from PIL import Image

from elc_audit_engine.generators import emr_review_bundle as eb
from elc_audit_engine.generators.emr_review_bundle import (
    BundleError,
    CaseBundle,
    ReviewImage,
    build_base_name,
    build_zip_name,
    compress_image,
    pack_zips,
    render_review_html,
)


def test_base_name_is_exactly_11_ascii_chars():
    name = build_base_name("12", "A", "03", "123345")
    assert name == "12A03123345" and len(name) == 11
    assert build_base_name("11", "B", "09", "1352") == "11B09001352"


@pytest.mark.parametrize("args", [
    ("1", "A", "03", "1"),      # 第一階層須 2 碼
    ("12", "E", "03", "1"),     # 資料屬性只能 A–D
    ("12", "A", "3", "1"),      # 案件分類須 2 碼
    ("12", "A", "03", "1234567"),  # 流水號最多 6 碼
    ("12", "A", "03", "12X"),   # 非數字
])
def test_base_name_rejects_invalid_parts(args):
    with pytest.raises(BundleError):
        build_base_name(*args)


def test_zip_name_follows_spec():
    assert build_zip_name("3501200000", "1150109", 1) == "3501200000_1150109_001.zip"
    assert build_zip_name("3503250461", "1151109", 12) == "3503250461_1151109_012.zip"
    with pytest.raises(BundleError):
        build_zip_name("350120", "1150109", 1)        # 機構代碼非 10 碼
    with pytest.raises(BundleError):
        build_zip_name("3501200000", "20260109", 1)   # 非民國 7 碼


def _png(size=(3000, 2000), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_image_is_downscaled_to_1600_long_side_jpeg():
    out = compress_image(_png())
    assert out is not None
    img = Image.open(io.BytesIO(out))
    assert img.format == "JPEG"
    assert max(img.size) <= eb.MAX_IMAGE_LONG_SIDE


def test_unreadable_image_is_skipped_not_fatal():
    assert compress_image(b"not an image") is None


def test_html_embeds_images_base64_and_escapes_text():
    jpeg = compress_image(_png((400, 300)))
    html_text = render_review_html(
        case_title="案件 <script>x</script>",
        soap={"s": "S & <b>", "o": "O", "a": "A", "p": "P"},
        orders=[{"code": "14050B", "name": "HbA1c", "points": "100"}],
        images=[ReviewImage(caption="傷口照片", jpeg=jpeg)],
    )
    assert "<script>x</script>" not in html_text          # 標題跳脫
    assert "S &amp; &lt;b&gt;" in html_text                # SOAP 跳脫
    b64 = base64.b64encode(jpeg).decode("ascii")
    assert f"data:image/jpeg;base64,{b64}" in html_text   # 影像內嵌
    assert "醫師簽章" in html_text                          # 簽章區存在（無憑證時標示待附）


def test_html_without_soap_or_images_is_still_valid():
    html_text = render_review_html(case_title="T", soap=None, orders=[], images=[])
    assert "本案無 SOAP 紀錄" in html_text and "無影像佐證" in html_text


def _bundle(name: str, size: int) -> CaseBundle:
    return CaseBundle(base_name=name, xml_bytes=b"x" * size, html_bytes=b"")


def test_pack_zips_splits_when_over_threshold_and_names_each_zip():
    bundles = [_bundle(f"12A03{i:06d}", 400) for i in range(1, 4)]
    zips = pack_zips(bundles, facility_code="3501200000", roc_date="1150109", split_bytes=700)
    assert [n for n, _ in zips] == ["3501200000_1150109_001.zip", "3501200000_1150109_002.zip",
                                    "3501200000_1150109_003.zip"]
    for _, data in zips:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert all(re.fullmatch(r"[A-Za-z0-9]{11}\.(xml|html)", n) for n in zf.namelist())


def test_case_bundle_contains_xml_and_html_pair(monkeypatch):
    monkeypatch.setattr(eb, "build_sampling_xml", lambda payload: b"<xml/>")
    bundle = eb.build_case_bundle(
        base_name="12A03123345", xml_payload={}, case_title="T",
        soap={"s": "a", "o": "b", "a": "c", "p": "d"}, orders=[], images=[],
    )
    assert set(bundle.files()) == {"12A03123345.xml", "12A03123345.html"}
    with pytest.raises(BundleError):
        eb.build_case_bundle(base_name="short", xml_payload={}, case_title="T", soap=None, orders=[], images=[])


def test_emr_bundle_endpoint_returns_zip_with_xml_and_html_per_case(make_api_app, facility_config):
    """端點：每案一組 XML＋HTML（11 碼檔名），ZIP 命名符合規範，且不含 SOAP 文字以外的捏造內容。"""
    from tests.test_monthly_package import BATCH, FAC, KEY, _sample_zip, _upload

    from config import settings

    settings.save_facility_config({"code": FAC})  # 醫事機構代碼須為 10 碼
    client = make_api_app().test_client()
    assert _upload(client, _sample_zip(FAC)).status_code == 200
    resp = client.get(f"/api/monthly/batch/{BATCH}/emr-bundle?roc=1151109", headers=KEY)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert resp.headers["Content-Disposition"].endswith('"' + f"{FAC}_1151109_001.zip" + '"')
    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        names = zf.namelist()
        assert len(names) == 4  # 2 案 × (XML + HTML)
        assert all(re.fullmatch(r"[A-Za-z0-9]{11}\.(xml|html)", n) for n in names)
        xml_names = [n for n in names if n.endswith(".xml")]
        for n in xml_names:
            txt = re.sub(r"^<\?xml[^>]*\?>\s*", "", zf.read(n).decode("big5"))
            assert "<ddata>" in txt and "<d3>" in txt and "<pdata>" in txt


def test_emr_bundle_endpoint_reports_incomplete_cases_without_zip(make_api_app, facility_config):
    """任一案件缺必要欄位 → 422 並列出案件，不產生殘缺 ZIP。"""
    from elc_audit_engine.monthly_package import build_emr_bundle
    from tests.test_monthly_package import BATCH, FAC, _sample_zip, _upload

    app = make_api_app()
    client = app.test_client()
    _upload(client, _sample_zip(FAC))
    store = app.extensions["elc"].case_store
    rec = store.list_by_batch(BATCH)[0]
    payload = dict(rec.payload)
    payload["record_no"] = ""  # 必要欄位 d3 缺漏
    store.update_payload(rec.case_id, payload)
    zips, failures = build_emr_bundle(store, BATCH, facility_code=FAC, roc_date="1151109")
    assert zips == []
    assert any(f["case_id"] == rec.case_id for f in failures)
