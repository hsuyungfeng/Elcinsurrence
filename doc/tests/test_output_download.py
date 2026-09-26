"""A-CR-05：列印端點回傳的 pdf_url 必須可下載，且需認證。"""
import pytest


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    from config import settings

    d = tmp_path / "output"
    d.mkdir()
    (d / "核減明細_abc.pdf").write_bytes(b"%PDF-1.4 test")
    (d / "secret.txt").write_text("x")
    monkeypatch.setattr(settings, "OUTPUT_DIR", str(d))
    return d


def test_download_pdf_with_key(client, out_dir):
    resp = client.get("/api/output/核減明細_abc.pdf", headers={"X-API-Key": "valid-key-123"})
    assert resp.status_code == 200
    assert resp.data == b"%PDF-1.4 test"


def test_download_requires_api_key(client, out_dir):
    assert client.get("/api/output/核減明細_abc.pdf").status_code == 401


def test_download_rejects_non_pdf_and_missing(client, out_dir):
    h = {"X-API-Key": "valid-key-123"}
    assert client.get("/api/output/secret.txt", headers=h).status_code == 404
    assert client.get("/api/output/nope.pdf", headers=h).status_code == 404
    assert client.get("/api/output/..%2Fsecret.pdf", headers=h).status_code == 404


def test_print_endpoint_url_matches_route(client, out_dir, monkeypatch):
    import server

    assert server._output_url(str(out_dir / "核減明細_abc.pdf")) == "/api/output/核減明細_abc.pdf"
