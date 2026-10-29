import io
import zipfile
import pytest
from elc_audit_engine.api.app import create_app
from elc_audit_engine.case_store import CaseStore

@pytest.fixture
def app_client(tmp_path):
    app = create_app({
        "TESTING": True,
        "ELC_DB_PATH": str(tmp_path / "cases.sqlite3"),
        "ELC_RAW_DIR": str(tmp_path / "raw"),
        "ELC_UPLOAD_DIR": str(tmp_path / "uploads"),
        "ELC_OUTPUT_DIR": str(tmp_path / "output"),
    })
    client = app.test_client()
    return client

def test_sampling_import_zip_csv(app_client):
    csv_content = "醫令代碼,醫令名稱,病歷號\n14050B,糖化血色素,M1001\n"
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("cases.csv", csv_content)
    zip_buf.seek(0)

    res = app_client.post(
        "/api/sampling/import",
        data={"file": (zip_buf, "cases.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["imported"] == 1

def test_sampling_import_totfa_zip(app_client):
    # Test uploading actual data/TOTFA.zip to sampling import
    with open("data/TOTFA.zip", "rb") as f:
        data = f.read()
    res = app_client.post(
        "/api/sampling/import",
        data={"file": (io.BytesIO(data), "TOTFA.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["status"] == "success"
    assert body["imported"] > 0
    assert body["imported"] <= 50

def test_appeal_import_totfa_zip(app_client):
    with open("data/TOTFA.zip", "rb") as f:
        data = f.read()
    res = app_client.post(
        "/api/appeal/import",
        data={"file": (io.BytesIO(data), "TOTFA.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["status"] == "success"
    assert body["imported"] > 0
    assert body["imported"] <= 50
