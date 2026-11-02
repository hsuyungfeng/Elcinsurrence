"""Phase 21-01 測試：健保送審檔案打包器（11 碼命名、格式過濾、單案整包）。

測試資料為合成案件，佐證庫與附件目錄指向暫存路徑。
"""

from __future__ import annotations

import io
import zipfile

import pytest

from config import settings
from elc_audit_engine import attachment_store
from elc_audit_engine.packagers import (
    PackagerError,
    build_base_name,
    build_case_package,
    check_extension,
    plan_evidence_names,
)

KEY = {"X-API-Key": "valid-key-123"}
BATCH = "MONTHLY-202307"


# ── 11 碼命名 ────────────────────────────────────────────────


def test_base_name_is_eleven_characters_matching_spec_example():
    # 規格範例 13B190123451 = 13 + B + 19 + 012345 + 序號 1
    base = build_base_name("13", "B", "19", "12345")
    assert base == "13B19012345"
    assert len(base) == 11
    assert base + "1" == "13B190123451"


def test_base_name_pads_class_and_sequence():
    assert build_base_name("13", "B", "3", "7") == "13B03000007"


@pytest.mark.parametrize(
    "stage1, stage2, case_class, case_seq, message",
    [
        ("1", "B", "19", "1", "第一階層代碼"),
        ("13", "BB", "19", "1", "第二階層代碼"),
        ("13", "b", "19", "1", "第二階層代碼"),
        ("13", "B", "123", "1", "案件分類"),
        ("13", "B", "19", "1234567", "流水號"),
        ("13", "B", "", "1", "案件分類"),
    ],
)
def test_base_name_rejects_malformed_parts(stage1, stage2, case_class, case_seq, message):
    with pytest.raises(PackagerError, match=message):
        build_base_name(stage1, stage2, case_class, case_seq)


# ── 格式過濾 ────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["scan.JPG", "scan.jpeg", "scan.png", "scan.bmp", "scan.tif", "scan.tiff", "report.pdf", "note.txt"])
def test_allowed_formats_pass(name):
    assert check_extension(name) == name[name.rfind("."):].lower()


@pytest.mark.parametrize("name", ["bundle.zip", "bundle.RAR", "setup.exe"])
def test_archives_and_executables_are_blocked(name):
    with pytest.raises(PackagerError, match="禁止上傳"):
        check_extension(name)


def test_dicom_is_rejected_with_reason():
    with pytest.raises(PackagerError, match="DICOM"):
        check_extension("image.dcm")


def test_unknown_format_is_rejected():
    with pytest.raises(PackagerError, match="非白名單"):
        check_extension("doc.docx")


def test_single_accepted_file_uses_base_name_without_number():
    accepted, rejected = plan_evidence_names("13B19012345", ["scan.jpg"])
    assert accepted == [("scan.jpg", "13B19012345.jpg")]
    assert rejected == []


def test_multiple_files_get_sequence_numbers():
    accepted, _ = plan_evidence_names("13B19012345", ["a.jpg", "b.png", "c.pdf"])
    assert [new for _, new in accepted] == ["13B190123451.jpg", "13B190123452.png", "13B190123453.pdf"]


def test_rejected_files_do_not_consume_sequence_numbers():
    accepted, rejected = plan_evidence_names("13B19012345", ["a.jpg", "evil.exe", "b.jpg"])
    assert [new for _, new in accepted] == ["13B190123451.jpg", "13B190123452.jpg"]
    assert [name for name, _ in rejected] == ["evil.exe"]


# ── 單案整包 ────────────────────────────────────────────────


def test_case_package_contains_xml_renamed_evidence_and_manifest():
    package, report = build_case_package(
        base_name="13B19012345",
        xml_bytes=b"<outpatient/>",
        evidence=[("scan.jpg", b"JPGDATA"), ("bundle.zip", b"ZIPDATA"), ("note.txt", b"TXT")],
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        names = set(archive.namelist())
        assert "13B19012345/13B19012345.xml" in names
        assert "13B19012345/13B190123451.jpg" in names  # 2 accepted → numbered
        assert "13B19012345/13B190123452.txt" in names
        assert not any(n.endswith(".zip") and "bundle" in n for n in names)
        assert archive.read("13B19012345/13B190123451.jpg") == b"JPGDATA"
        manifest = archive.read("13B19012345/MANIFEST.txt").decode("utf-8")
        assert "[拒收] bundle.zip" in manifest
    assert report["rejected"][0]["original"] == "bundle.zip"
    assert len(report["accepted"]) == 2


# ── 端點 ───────────────────────────────────────────────────


def _monthly_payload(index: int) -> dict:
    return {
        "batch": BATCH,
        "case_class": "3",
        "case_seq": f"{index:04d}",
        "record_no": f"A{index:09d}",
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
    for index in range(1, 6):
        store.create(case_id=f"MON-{index:03d}", kind="monthly", payload=_monthly_payload(index))
    return app


@pytest.fixture
def client(api):
    with api.test_client() as c:
        yield c


@pytest.fixture
def sampled(client):
    res = client.post(
        "/api/sampling/sample-batch",
        json={"batch": BATCH, "random_count": 5, "intentional_count": 0, "seed": 1},
        headers=KEY,
    )
    assert res.status_code == 200
    return [case["id"] for case in res.get_json()["cases"]]


@pytest.fixture
def nhi_codes(monkeypatch):
    monkeypatch.setattr(settings, "NHI_STAGE1_CODE", "13")
    monkeypatch.setattr(settings, "NHI_STAGE2_CODE", "B")


def _put_vault_files(files: dict[str, bytes]) -> None:
    """依 settings.DATA_DIR 寫入佐證庫檔案：files 為 {"images/a.jpg": bytes, ...}。"""
    import os

    for relative, data in files.items():
        target = os.path.join(settings.DATA_DIR, "evidence_vault", "A000000001-2307", relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)


def test_export_package_returns_503_when_stage_codes_unset(client, sampled, monkeypatch):
    monkeypatch.setattr(settings, "NHI_STAGE1_CODE", "")
    monkeypatch.setattr(settings, "NHI_STAGE2_CODE", "")
    res = client.get(f"/api/sampling/cases/{sampled[0]}/export-package", headers=KEY)
    assert res.status_code == 503
    assert "NHI_STAGE1_CODE" in res.get_json()["message"]


def test_export_package_is_zip_with_eleven_digit_xml(client, sampled, nhi_codes):
    res = client.get(f"/api/sampling/cases/{sampled[0]}/export-package", headers=KEY)
    assert res.status_code == 200
    assert res.mimetype == "application/zip"
    assert "attachment" in res.headers["Content-Disposition"]
    store = client.application.extensions["elc"].case_store
    source_seq = store.get(sampled[0]).payload["monthly_source"]["case_seq"]
    with zipfile.ZipFile(io.BytesIO(res.data)) as archive:
        xml_entries = [n for n in archive.namelist() if n.endswith(".xml")]
        assert len(xml_entries) == 1
        base = xml_entries[0].split("/")[-1][:-4]
        assert len(base) == 11
        assert base.startswith("13B03")  # 第一階 13、第二階 B、案件分類 3→03
        assert base.endswith(f"{int(source_seq):06d}")  # 流水號定寬 6 碼
        assert archive.read(xml_entries[0]).startswith(b'<?xml version="1.0" encoding="Big5"?>')


def test_export_package_filters_blocked_evidence_and_numbers_accepted(client, sampled, nhi_codes):
    _put_vault_files({
        "images/wound.jpg": b"J",
        "reports/lab.pdf": b"P",
        "records/bad.exe": b"E",
        "reports/bundle.rar": b"R",
    })
    # 此案的身分證與就醫日必須對應 A000000001-2307
    store = client.application.extensions["elc"].case_store
    payload = dict(store.get(sampled[0]).payload)
    payload["record_no"] = "A000000001"
    payload["visit_date"] = "1120718"
    store.update_payload(sampled[0], payload)

    res = client.get(f"/api/sampling/cases/{sampled[0]}/export-package", headers=KEY)
    assert res.status_code == 200
    assert res.headers["X-Package-Accepted"] == "2"
    assert res.headers["X-Package-Rejected"] == "2"
    with zipfile.ZipFile(io.BytesIO(res.data)) as archive:
        names = archive.namelist()
        manifest = archive.read(next(n for n in names if n.endswith("MANIFEST.txt"))).decode("utf-8")
    assert any(n.endswith(".jpg") for n in names)
    assert not any(n.endswith((".exe", ".rar")) for n in names)
    assert "[拒收] bad.exe" in manifest
    assert "[拒收] bundle.rar" in manifest


def test_export_package_rejects_case_without_monthly_source(client, api, sampled, nhi_codes):
    store = api.extensions["elc"].case_store
    payload = dict(store.get(sampled[0]).payload)
    payload.pop("monthly_source", None)
    store.update_payload(sampled[0], payload)
    res = client.get(f"/api/sampling/cases/{sampled[0]}/export-package", headers=KEY)
    assert res.status_code == 422


def test_export_package_unknown_case_is_404(client, nhi_codes):
    res = client.get("/api/sampling/cases/NOPE-1/export-package", headers=KEY)
    assert res.status_code == 404
