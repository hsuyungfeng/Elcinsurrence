"""Unit tests for Phase 28 Plan 28-02: EMR Batch Packaging & 11-Code Standard Naming."""

from __future__ import annotations

import io
import zipfile
import pytest

from elc_audit_engine.packagers.emr_batch_packager import (
    BatchZipPackager,
    Emr11CodeNaming,
    EmrClassifier,
    EmrPackagingError,
    SourceQualityValidator,
    StructuredSoapPdfBuilder,
)


def test_emr_11code_naming_standard():
    # 規格：[第1階 2碼 11] + [第2階 1碼 A] + [案件分類 2碼 09] + [流水號 6碼 001352] = 11A09001352
    base = Emr11CodeNaming.build_base_name("11", "A", "09", 1352)
    assert base == "11A09001352"

    # 單一檔案直接加上 .pdf
    fname = Emr11CodeNaming.format_filename(base, ".pdf")
    assert fname == "11A09001352.pdf"

    # 多張同類檔案擴充 -1, -2
    fname_img1 = Emr11CodeNaming.format_filename(base, ".jpg", sub_index=1)
    assert fname_img1 == "11A09001352-1.jpg"

    # 驗證不合規參數拋出 EmrPackagingError
    with pytest.raises(EmrPackagingError):
        Emr11CodeNaming.build_base_name("1", "A", "09", 1)  # 第1階不足2碼
    with pytest.raises(EmrPackagingError):
        Emr11CodeNaming.build_base_name("11", "X", "09", 1)  # 第2階非ABCD


def test_emr_classifier_four_tiers():
    assert EmrClassifier.classify(category="records") == "A"
    assert EmrClassifier.classify(filename="門診處方箋.pdf") == "A"

    assert EmrClassifier.classify(category="images") == "B"
    assert EmrClassifier.classify(filename="xray_chest.jpg") == "B"

    assert EmrClassifier.classify(category="labs") == "C"
    assert EmrClassifier.classify(filename="hba1c_lab_report.pdf") == "C"

    assert EmrClassifier.classify(category="consents") == "D"
    assert EmrClassifier.classify(filename="手術同意書.pdf") == "D"


def test_source_quality_validator_rules():
    # 嚴格半形英數字 11 碼檢查
    valid, _ = SourceQualityValidator.validate_filename("11A09001352.pdf")
    assert valid is True

    valid_sub, _ = SourceQualityValidator.validate_filename("11B09001352-1.jpg")
    assert valid_sub is True

    # 包含中文字、全形字、特殊符號皆阻斷
    invalid_cn, err = SourceQualityValidator.validate_filename("11A09001352病歷.pdf")
    assert invalid_cn is False
    assert "不符合健保 11 碼標準編碼格式" in err

    # 白名單與阻斷副檔名
    valid_ext, _ = SourceQualityValidator.validate_extension("11A09001352.pdf")
    assert valid_ext is True

    blocked_zip, err_zip = SourceQualityValidator.validate_extension("11A09001352.zip")
    assert blocked_zip is False
    assert "禁止上傳" in err_zip

    # DICOM 需含 DICOMDIR
    dicom_no_dir, _ = SourceQualityValidator.validate_dicom_bundle(["image1.dcm", "image2.dcm"])
    assert dicom_no_dir is False

    dicom_with_dir, _ = SourceQualityValidator.validate_dicom_bundle(["image1.dcm", "DICOMDIR"])
    assert dicom_with_dir is True


def test_structured_soap_pdf_builder_with_tree_bookmarks():
    case_info = {
        "facility_code": "3503250461",
        "patient_name": "王大明",
        "id_card": "A123456789",
        "visit_date": "2023-07-15",
        "primary_diagnosis": "E11.9 第二型糖尿病",
        "total_points": 100,
        "orders": [
            {"code": "14050B", "points": "100", "name": "糖化血色素檢驗 HbA1c"}
        ]
    }
    soap_raw = {
        "s": "定期回診追蹤糖尿病",
        "o": "Fasting glucose: 138 mg/dL, HbA1c: 7.2%",
        "a": "E11.9 第二型糖尿病",
        "p": "Metformin 500mg bid續用",
    }
    pdf_bytes = StructuredSoapPdfBuilder.build_soap_pdf(case_info, soap_raw)
    assert len(pdf_bytes) > 500
    assert pdf_bytes.startswith(b"%PDF")

    # 驗證 PDF 樹狀書籤
    has_bookmarks, titles = SourceQualityValidator.validate_pdf_has_bookmarks(pdf_bytes)
    assert has_bookmarks is True
    assert "病歷首頁" in titles
    assert "門診處方箋" in titles
    assert "門診 SOAP 紀錄單" in titles


def test_batch_zip_packager_dynamic_splitting():
    # 模擬案件資料
    cases_files = [
        {
            "case_id": "CASE-1",
            "base_11code": "11A09000001",
            "files": [
                {"filename": "11A09000001.pdf", "data": b"PDF content 1", "tier": "A", "original_name": "c1.pdf"},
                {"filename": "11B09000001-1.jpg", "data": b"IMG content 1", "tier": "B", "original_name": "c1.jpg"},
            ],
        },
        {
            "case_id": "CASE-2",
            "base_11code": "11A09000002",
            "files": [
                {"filename": "11A09000002.pdf", "data": b"PDF content 2", "tier": "A", "original_name": "c2.pdf"},
            ],
        },
    ]

    # 設定較小的分割臨界值 (例如 10 bytes)，以驗證動態分包機制
    packages = BatchZipPackager.package_emr_batch(
        cases_files,
        facility_code="3503250461",
        system_date_roc="1120715",
        submission_type=1,
        split_threshold=10,
    )

    # 驗證動態切割出多個封包
    assert len(packages) >= 2
    for seq, (zip_name, zip_bytes, report) in enumerate(packages, start=1):
        assert zip_name == f"3503250461_1120715_{seq:03d}.zip"
        assert report["file_count"] > 0

        # 解壓縮驗證 MANIFEST.txt 與 SHA256_CHECKSUM.txt
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as z:
            namelist = z.namelist()
            assert "MANIFEST.txt" in namelist
            assert "SHA256_CHECKSUM.txt" in namelist
            manifest_text = z.read("MANIFEST.txt").decode("utf-8")
            assert "醫事機構代碼：3503250461" in manifest_text
            assert "初審送核" in manifest_text


def test_emr_batch_package_api_endpoint(make_api_app):
    app = make_api_app()
    client = app.test_client()
    auth_headers = {"X-API-Key": "valid-key-123"}
    # 測試 POST /api/emr/batch-package
    resp = client.post(
        "/api/emr/batch-package",
        json={"target": "sampling", "facility_code": "3503250461"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert len(data["packages"]) >= 1
    pkg = data["packages"][0]
    assert pkg["filename"].startswith("3503250461_")
    assert pkg["filename"].endswith(".zip")
    assert pkg["file_count"] >= 1

    # 測試 GET /api/emr/packages
    resp_list = client.get("/api/emr/packages", headers=auth_headers)
    assert resp_list.status_code == 200
    list_data = resp_list.get_json()
    assert len(list_data["packages"]) >= 1

    # 測試 GET /api/emr/download/<filename>
    filename = pkg["filename"]
    resp_dl = client.get(f"/api/emr/download/{filename}", headers=auth_headers)
    assert resp_dl.status_code == 200
    assert resp_dl.data.startswith(b"PK")
