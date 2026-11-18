"""WR-01～WR-09 回歸測試（32.1 程式碼審查警告等級發現）。"""

from __future__ import annotations

import ipaddress
from pathlib import Path

import pytest

from elc_audit_engine import lan_trust
from elc_audit_engine.lan_trust import TrustConfigError, is_acceptable_trust_network, parse_trusted_subnets

KEY = {"X-API-Key": "valid-key-123"}


@pytest.fixture
def api(make_api_app):
    return make_api_app()


@pytest.fixture
def client(api):
    with api.test_client() as c:
        yield c


# ── WR-01：月報不得含 inline style 屬性（CSP style-src 'self' 會擋下） ──


def test_monthly_report_module_has_no_inline_style_attributes():
    src = Path("src/elc_audit_engine/monthly_report_html.py").read_text(encoding="utf-8")
    assert 'style="' not in src
    assert "style='" not in src


def test_monthly_report_stylesheet_defines_classes_used_by_markup():
    css = Path("static/css/monthly-report.css").read_text(encoding="utf-8")
    assert ".vault-link" in css
    assert ".soap-modal-wrap" in css


# ── WR-07：信任網段僅限私有 IPv4 且遮罩不短於 /16（WR-02 確認閘門見 install.sh） ──


@pytest.mark.parametrize("bad", ["0.0.0.0/0", "10.0.0.0/8", "8.8.8.8/32", "172.16.0.0/12"])
def test_overly_broad_or_public_trust_subnet_is_rejected(bad):
    with pytest.raises(TrustConfigError):
        parse_trusted_subnets(bad)


@pytest.mark.parametrize("ok", ["192.168.1.0/24", "192.168.2.0/23", "192.168.0.0/16"])
def test_private_trust_subnet_within_limit_is_accepted(ok):
    assert parse_trusted_subnets(ok) == [ipaddress.ip_network(ok)]


def test_detection_drops_non_acceptable_networks(monkeypatch):
    monkeypatch.setattr(
        lan_trust,
        "_detect_local_subnets_raw",
        lambda *a, **k: [ipaddress.ip_network("8.8.8.0/24"), ipaddress.ip_network("192.168.1.0/24")],
    )
    nets = lan_trust.detect_local_subnets()
    assert nets == [ipaddress.ip_network("192.168.1.0/24")]


def test_is_acceptable_rejects_public_even_if_narrow():
    assert is_acceptable_trust_network(ipaddress.ip_network("192.168.1.0/24"))
    assert not is_acceptable_trust_network(ipaddress.ip_network("8.8.8.0/24"))
    assert not is_acceptable_trust_network(ipaddress.ip_network("10.0.0.0/8"))


def test_install_script_requires_confirmation_for_non_24_auto_trust():
    src = Path("deploy/install.sh").read_text(encoding="utf-8")
    assert '*/24) ;;' in src


# ── WR-08：院所機構代碼必須為 10 碼數字 ──


def test_facility_code_must_be_ten_digits(client):
    res = client.post("/api/facility", json={"code": "FAC001", "name": "測試診所"}, headers=KEY)
    assert res.status_code == 400
    assert "10 碼" in res.get_json()["message"]


# ── WR-09：HIS 已寫入但讀回不符 → NEEDS_REVIEW（終態，不自動重送） ──


def _create_job(client):
    res = client.post(
        "/api/bridge/jobs",
        json={"s_type_code": "15", "target_id": "MONTHLY-202307"},
        headers=KEY,
    )
    assert res.status_code == 201
    return res.get_json()["job"]["job_id"]


def test_needs_review_is_terminal_and_not_requeued(client):
    job_id = _create_job(client)
    client.post(f"/api/bridge/jobs/{job_id}/status", json={"status": "SENDING"}, headers=KEY)
    res = client.post(f"/api/bridge/jobs/{job_id}/status", json={"status": "NEEDS_REVIEW"}, headers=KEY)
    assert res.status_code == 200
    job = res.get_json()["job"]
    assert job["status"] == "NEEDS_REVIEW"

    # 不得回到待送清單，也不得由 NEEDS_REVIEW 再轉為 FAILED／SENDING
    pending_ids = [j["job_id"] for j in client.get("/api/bridge/jobs/pending", headers=KEY).get_json()["jobs"]]
    assert job_id not in pending_ids
    again = client.post(f"/api/bridge/jobs/{job_id}/status", json={"status": "FAILED"}, headers=KEY)
    assert again.status_code == 409


# ── WR-06 上線前檢查：預設設定下，新輸出目錄必須等同舊版既有封包位置 ──


def test_default_emr_output_dir_matches_legacy_package_location(api):
    """WR-06：舊版以相對路徑 data/output/emr_packages 存放封包（服務 WorkingDirectory=專案根目錄）。
    新版預設必須指向同一目錄，既有封包不需搬移。"""
    from elc_audit_engine.api.routes.emr_packaging import _get_emr_output_dir

    legacy = (Path("data") / "output" / "emr_packages").resolve()
    with api.app_context():
        assert _get_emr_output_dir() == legacy
