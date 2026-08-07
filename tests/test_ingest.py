"""攝入（ingest）套件測試：抽樣 CSV 解析／OCR 行解析／型別偵測／匯入端點。

- parse_sampling_csv：欄位契約對映、必填拒絕、編碼、日期正規化
- parse_sampling_ocr_text：醫令代碼錨點、重複行、無代碼
- detect_media_type / 工具缺失錯誤語意
- /api/sampling/import、/api/appeal/import 端點契約（test_client）
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from elc_audit_engine.ingest import (
    MediaExtractError,
    SamplingImportError,
    detect_media_type,
    parse_sampling_csv,
    parse_sampling_ocr_text,
)
from elc_audit_engine.ingest.media import _run

# ---------------------------------------------------------------------------
# parse_sampling_csv
# ---------------------------------------------------------------------------

_SAMPLE_CSV = (
    "流水號,病歷號,病患姓名,醫令代碼,醫令名稱,就醫日期,科別,SOAP\n"
    "101,M1001,林聰明,14050B,糖化血色素檢驗 HbA1c,20260710,家醫科,S: 糖尿病追蹤\n"
    "102,M1002,黃淑芬,33084B,胸部X光攝影,20260712,胸腔內科,\n"
)


def test_sampling_csv_utf8():
    result = parse_sampling_csv(_SAMPLE_CSV.encode("utf-8-sig"))
    assert result.encoding_used == "utf-8-sig"
    assert len(result.records) == 2
    assert len(result.rejected) == 0
    r0 = result.records[0]
    assert r0.order_code == "14050B"
    assert r0.patient_name == "林聰明"
    assert r0.visit_date == "2026-07-10"  # 8 碼西元 → ISO
    assert r0.source == "csv"


def test_sampling_csv_big5():
    raw = _SAMPLE_CSV.encode("big5")
    result = parse_sampling_csv(raw)
    assert result.encoding_used == "big5"
    assert result.records[1].order_name == "胸部X光攝影"


def test_sampling_csv_missing_order_code_rejected():
    raw = "醫令代碼,醫令名稱\n,無碼醫令\n14110B,正常\n".encode("utf-8")
    result = parse_sampling_csv(raw)
    assert len(result.records) == 1
    assert len(result.rejected) == 1
    assert "醫令代碼" in result.rejected[0].reason


def test_sampling_csv_no_header_raises():
    with pytest.raises(SamplingImportError, match="表頭"):
        parse_sampling_csv("14050B,糖化血色素\n".encode("utf-8"))


def test_sampling_csv_undecodable_raises():
    with pytest.raises(SamplingImportError, match="解碼"):
        parse_sampling_csv(b"\xff\xfe\x00\x80")


# ---------------------------------------------------------------------------
# parse_sampling_ocr_text
# ---------------------------------------------------------------------------

def test_ocr_text_extracts_order_codes():
    text = "西醫基層總額門診抽樣清單\n14050B 糖化血色素檢驗 HbA1c\n33084B 胸部X光攝影\n總計 2 筆"
    result = parse_sampling_ocr_text(text)
    codes = [(r.order_code, r.order_name) for r in result.records]
    assert ("14050B", "糖化血色素檢驗 HbA1c") in codes
    assert ("33084B", "胸部X光攝影") in codes
    assert all(r.source == "ocr" for r in result.records)
    assert all(r.ocr_line for r in result.records)


def test_ocr_text_duplicate_code_rejected():
    text = "14050B 糖化血色素\n14050B 糖化血色素（重複）"
    result = parse_sampling_ocr_text(text)
    assert len(result.records) == 1
    assert len(result.rejected) == 1
    assert "重複" in result.rejected[0].reason


def test_ocr_text_no_code_returns_empty():
    result = parse_sampling_ocr_text("這是沒有醫令代碼的文字\n純中文內容\n")
    assert len(result.records) == 0


def test_ocr_text_lowercase_code_normalized():
    result = parse_sampling_ocr_text("14050b 糖化血色素")
    assert result.records[0].order_code == "14050B"


# ---------------------------------------------------------------------------
# detect_media_type / 工具缺失
# ---------------------------------------------------------------------------

def test_detect_media_type():
    assert detect_media_type("list.csv") == "csv"
    assert detect_media_type("scan.pdf") == "pdf"
    assert detect_media_type("photo.jpg") == "image"
    assert detect_media_type("photo.JPEG") == "image"
    assert detect_media_type("photo.png") == "image"


def test_detect_media_type_unsupported():
    with pytest.raises(MediaExtractError, match="不支援"):
        detect_media_type("notes.txt")


def test_missing_tool_raises_media_error(monkeypatch):
    def fake_subprocess_run(*args, **kwargs):
        raise FileNotFoundError(args[0][0])

    monkeypatch.setattr("subprocess.run", fake_subprocess_run)
    with pytest.raises(MediaExtractError, match="系統工具"):
        _run("pdftotext", ["x"])


# ---------------------------------------------------------------------------
# 匯入端點（test_client，落盤路徑導向 tmp_path 避免污染 data/uploads）
# ---------------------------------------------------------------------------

#: Phase 9-01：本檔測試的是匯入/清單端點的業務邏輯，非認證本身
#: （認證測試在 tests/test_auth.py），故以固定測試 key 通過 before_request。
_TEST_API_KEY = "0000000000TESTKEY0000"


@pytest.fixture()
def api(monkeypatch, tmp_path):
    import server as server_mod

    monkeypatch.setattr(server_mod, "_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(server_mod, "_RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setattr(server_mod, "_sampling_cases", None)
    monkeypatch.setattr(server_mod, "_appeal_cases", None)
    monkeypatch.setitem(server_mod.app.config, "ELC_API_KEYS", {_TEST_API_KEY: "test-suite"})
    client = server_mod.app.test_client()
    client.environ_base["HTTP_X_API_KEY"] = _TEST_API_KEY
    return client, tmp_path


def test_security_headers_present_on_all_responses(api):
    """P1-5 縱深防禦：CSP 等安全標頭須套用於頁面與 API 回應。"""
    client, _ = api
    for path in ("/", "/api/sampling/cases"):
        r = client.get(path)
        csp = r.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp, path
        assert "frame-ancestors 'none'" in csp, path
        assert r.headers.get("X-Content-Type-Options") == "nosniff", path
        assert r.headers.get("Referrer-Policy") == "no-referrer", path


def test_csp_has_no_external_host_allowance(api):
    """外鏈字型已移除（D2）；CSP 不得再放行任何外部主機。"""
    client, _ = api
    csp = client.get("/").headers.get("Content-Security-Policy", "")
    assert "http://" not in csp
    assert "https://" not in csp


def test_frontend_has_no_external_resource_links():
    """回歸：static/index.html 不得重新引入外鏈資源（字型/CDN）。"""
    from pathlib import Path

    html = Path("static/index.html").read_text(encoding="utf-8")
    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html


def test_frontend_case_list_does_not_use_innerhtml_templating():
    """回歸：P1-5 修復後 renderCaseList 不得再以 innerHTML 拼接 API 欄位。"""
    from pathlib import Path

    import re

    html = Path("static/index.html").read_text(encoding="utf-8")
    # 只看「賦值」給 innerHTML 的位置（註解中提及 innerHTML 不算注入點）；
    # 僅允許賦成空字串字面值（清空子節點）。
    assignments = re.findall(r"\.innerHTML\s*=\s*(.+)", html)
    for rhs in assignments:
        assert rhs.strip().startswith(("''", '""')), f"疑似 HTML 注入點: {rhs.strip()}"


def test_sampling_import_csv_endpoint(api):
    client, tmp_path = api
    r = client.post(
        "/api/sampling/import",
        data={"file": (io.BytesIO(_SAMPLE_CSV.encode("utf-8-sig")), "sample.csv")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "success"
    assert data["imported"] == 2
    assert data["source"] == "csv"
    assert data["media_type"] == "csv"
    # GET 案例清單優先回導入資料
    cases = client.get("/api/sampling/cases").get_json()
    assert len(cases) == 2
    assert cases[0]["order_code"] == "14050B"
    assert cases[0]["demo"] is False
    # 落盤檔案存在
    assert list(Path(tmp_path).glob("sampling_*.json"))


def test_sampling_import_unsupported_ext(api):
    client, _ = api
    r = client.post(
        "/api/sampling/import",
        data={"file": (io.BytesIO(b"x"), "notes.txt")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 400
    assert "不支援" in r.get_json()["message"]


def test_sampling_import_missing_file(api):
    client, _ = api
    r = client.post("/api/sampling/import", data={})
    assert r.status_code == 400


def test_sampling_import_ocr_no_result(api, monkeypatch):
    """OCR 無可識別醫令代碼 → 400 + 誠實訊息，不覆蓋清單。"""
    client, _ = api
    # server 以 from-import 直接引用 extract_text，需替身 server 命名空間的符號。
    import server as server_mod

    def fake_extract(path, *, media_type=None):
        return "純文字，沒有醫令代碼", "tesseract"

    monkeypatch.setattr(server_mod, "extract_text", fake_extract)
    r = client.post(
        "/api/sampling/import",
        data={"file": (io.BytesIO(b"\xff\xd8\xff\xe0"), "scan.jpg")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 400
    assert "未匯入任何案件" in r.get_json()["message"]


def test_appeal_import_csv_endpoint(api):
    client, tmp_path = api
    row = (
        "0000000300,0000000001,11507,20260701,01,201,20260620,19800101,"
        "****1234,001,64140C,20260620,01,300,20260715,"
        "病歷未記載甲床損傷範圍,A-檢驗結果確實於時效內上傳,補上影像"
    )
    r = client.post(
        "/api/appeal/import",
        data={"file": (io.BytesIO(row.encode("big5")), "ded.csv")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["imported"] == 1
    cases = client.get("/api/appeal/cases").get_json()
    assert cases[0]["order_code"] == "64140C"
    assert cases[0]["deduct_amount"] == 300
    assert cases[0]["demo"] is False
    assert list(Path(tmp_path).glob("appeal_*.json"))
