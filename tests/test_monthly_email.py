"""郵寄報告：SMTP 設定、信箱驗證、郵件結構、寄送流程（假 SMTP，不連網路）、開發模式寫 .eml、
錯誤不外洩收件人；以及報告納入門檻（醫療總點數 > 1000、須有給付規定）。
"""

from __future__ import annotations

import email
import io
import smtplib
import zipfile
from email.message import EmailMessage
from pathlib import Path
from typing import ClassVar

import pytest

from elc_audit_engine import mailer
from elc_audit_engine.monthly_audit import (
    BatchAudit,
    aggregate_batch,
    audit_case,
    report_view,
)
from elc_audit_engine.rule_repository.models import RuleResult, not_found

KEY = {"X-API-Key": "valid-key-123"}
BATCH = "MONTHLY-202307"
RECIPIENT = "doctor@hospital.example.org"


# ── 設定與驗證 ───────────────────────────────────────────────────


def test_no_smtp_host_means_dev_mode():
    assert mailer.smtp_config_from_env({}) is None
    assert mailer.smtp_config_from_env({"SMTP_HOST": "   "}) is None


def test_smtp_config_defaults_and_overrides():
    cfg = mailer.smtp_config_from_env({"SMTP_HOST": "smtp.example.org"})
    assert (cfg.host, cfg.port, cfg.user, cfg.password, cfg.sender) == (
        "smtp.example.org", 587, None, None, "noreply@elcinsurrence.local",
    )
    cfg = mailer.smtp_config_from_env({
        "SMTP_HOST": "h", "SMTP_PORT": "2525", "SMTP_USER": "u", "SMTP_PASSWORD": "p", "SMTP_FROM": "me@x.org",
    })
    assert (cfg.port, cfg.user, cfg.password, cfg.sender) == (2525, "u", "p", "me@x.org")


def test_invalid_smtp_port_falls_back_to_default():
    cfg = mailer.smtp_config_from_env({"SMTP_HOST": "h", "SMTP_PORT": "not-a-number"})
    assert cfg.port == 587


@pytest.mark.parametrize("address", ["doctor@hospital.org.tw", "a.b+c@x.io"])
def test_valid_addresses_accepted(address):
    assert mailer.is_valid_email(address)


@pytest.mark.parametrize("address", [
    "", "no-at-sign", "a@b", "x@y.z\nBcc: evil@x.org", "a b@x.org", "a@x.org,evil@x.org", "<a@x.org>",
])
def test_invalid_or_injection_addresses_rejected(address):
    assert not mailer.is_valid_email(address)


# ── 郵件結構 ─────────────────────────────────────────────────────


def test_report_email_has_html_attachment_and_plain_body():
    message = mailer.build_report_email(
        to=RECIPIENT, sender="noreply@elcinsurrence.local", batch=BATCH, html_report="<!doctype html><p>報告</p>",
    )
    assert message["To"] == RECIPIENT
    assert message["From"] == "noreply@elcinsurrence.local"
    assert BATCH in message["Subject"]

    parsed = email.message_from_bytes(message.as_bytes())
    attachments = [part for part in parsed.walk() if part.get_content_type() == "text/html"]
    assert len(attachments) == 1
    assert attachments[0].get_filename() == f"monthly_report_{BATCH}.html"
    assert "<p>報告</p>" in attachments[0].get_payload(decode=True).decode("utf-8")
    body = next(part for part in parsed.walk() if part.get_content_type() == "text/plain")
    assert "個人資料" in body.get_payload(decode=True).decode("utf-8")


# ── 寄送流程（假 SMTP） ──────────────────────────────────────────


class FakeSMTP:
    """記錄呼叫順序；不建立任何網路連線。"""

    instances: ClassVar[list[FakeSMTP]] = []
    fail_with: Exception | None = None

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.calls: list = []
        self.sent: EmailMessage | None = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user))

    def send_message(self, message):
        if FakeSMTP.fail_with is not None:
            raise FakeSMTP.fail_with
        self.sent = message
        self.calls.append("send")


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTP.instances = []
    FakeSMTP.fail_with = None
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def _message() -> EmailMessage:
    return mailer.build_report_email(to=RECIPIENT, sender="noreply@x.org", batch=BATCH, html_report="<p>x</p>")


def test_send_uses_starttls_and_login_on_port_587(fake_smtp):
    cfg = mailer.SmtpConfig(host="smtp.example.org", port=587, user="u", password="p", sender="noreply@x.org")
    mailer.send_message(cfg, _message())
    client = fake_smtp.instances[0]
    assert client.host == "smtp.example.org" and client.port == 587
    assert client.calls == ["ehlo", "starttls", "ehlo", ("login", "u"), "send"]
    assert client.sent["To"] == RECIPIENT


def test_send_without_user_skips_login(fake_smtp):
    cfg = mailer.SmtpConfig(host="h", port=587, user=None, password=None, sender="noreply@x.org")
    mailer.send_message(cfg, _message())
    assert ("login", None) not in fake_smtp.instances[0].calls


def test_smtp_failure_becomes_mail_error_without_recipient(fake_smtp):
    fake_smtp.fail_with = smtplib.SMTPAuthenticationError(535, b"bad credentials")
    cfg = mailer.SmtpConfig(host="h", port=587, user="u", password="p", sender="noreply@x.org")
    with pytest.raises(mailer.MailError) as info:
        mailer.send_message(cfg, _message())
    assert RECIPIENT not in str(info.value)
    assert "SMTPAuthenticationError" in str(info.value)


def test_write_eml_creates_file_in_output_dir(tmp_path):
    name = mailer.write_eml(_message(), str(tmp_path / "out"), BATCH)
    assert name.startswith(f"mail_{BATCH}_") and name.endswith(".eml")
    content = (tmp_path / "out" / name).read_bytes()
    assert b"Subject:" in content and BATCH.encode() in content


# ── 端點 ─────────────────────────────────────────────────────────


def _ddata(seq: int, *, total: str, orders: list[tuple[str, str]]) -> str:
    pdatas = "".join(
        f"<pdata><p1>0</p1><p3>2</p3><p4>{code}</p4><p10>1.0</p10><p11>1</p11>"
        f"<p12>{points}</p12><p13>{i + 1}</p13></pdata>"
        for i, (code, points) in enumerate(orders)
    )
    return (
        f"<ddata><dhead><d1>02</d1><d2>{seq}</d2></dhead><dbody><d3>A123456789</d3>"
        f"<d8>03</d8><d9>1120718</d9><d19>S00123A</d19><d30>DOC</d30><d39>{total}</d39>"
        f"<d49>測試病患</d49>{pdatas}</dbody></ddata>"
    )


def _zip_bytes() -> bytes:
    text = (
        '<?xml version="1.0" encoding="Big5"?>\r\n<outpatient>\r\n'
        "<tdata><t1>10</t1><t3>11207</t3></tdata>\r\n"
        + _ddata(1, total="2000", orders=[("TSTX", "400")])
        + "\r\n</outpatient>\r\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("TOTFA.xml", text.encode("big5"))
    return buf.getvalue()


@pytest.fixture
def app(make_api_app, tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    rules_db = str(tmp_path / "rules.sqlite3")
    import sqlite3

    from elc_audit_engine.rule_repository.db import (
        SCHEMA_DRUG,
        SCHEMA_PAYMENT,
        SCHEMA_RULE_MAPPING,
    )

    conn = sqlite3.connect(rules_db)
    for ddl in (SCHEMA_PAYMENT, SCHEMA_DRUG, SCHEMA_RULE_MAPPING):
        conn.execute(ddl)
    conn.execute("INSERT INTO payment_rules VALUES ('TSTX','測試','限使用。','2023-01-01','2910-12-31')")
    conn.commit()
    conn.close()
    return make_api_app(
        ELC_RULES_DB_PATH=rules_db,
        ELC_OUTPUT_DIR=str(tmp_path / "output"),
    )


@pytest.fixture
def client(app):
    with app.test_client() as c:
        c.post(
            "/api/monthly/upload",
            data={"file": (io.BytesIO(_zip_bytes()), "TOTFA.zip")},
            headers=KEY,
            content_type="multipart/form-data",
        )
        yield c


def test_email_endpoint_allows_access_without_api_key_for_integration(client):
    """月申報郵寄端點免強制 X-API-Key（與 monthly 其他端點一致，方便前端直連）。"""
    resp = client.post(f"/api/monthly/batch/{BATCH}/email", json={"email": RECIPIENT})
    assert resp.status_code == 200


def test_email_dev_mode_writes_eml_and_warns(client, app, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    resp = client.post(f"/api/monthly/batch/{BATCH}/email", json={"email": RECIPIENT}, headers=KEY)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "dev_mode"
    assert "SMTP_HOST" in body["warning"]
    saved = Path(app.config["ELC_OUTPUT_DIR"]) / body["saved_as"]
    assert saved.exists()
    parsed = email.message_from_bytes(saved.read_bytes())
    attachment = next(p for p in parsed.walk() if p.get_content_type() == "text/html")
    assert "<!doctype html>" in attachment.get_payload(decode=True).decode("utf-8")


def test_email_sends_via_smtp_when_configured(client, fake_smtp, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("SMTP_USER", "mailer")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    resp = client.post(f"/api/monthly/batch/{BATCH}/email", json={"email": RECIPIENT}, headers=KEY)
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "sent", "batch": BATCH}
    sent = fake_smtp.instances[0].sent
    assert sent["To"] == RECIPIENT
    assert sent["From"] == "noreply@elcinsurrence.local"


def test_email_accepts_form_data(client, fake_smtp, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")
    resp = client.post(f"/api/monthly/batch/{BATCH}/email", data={"email": RECIPIENT}, headers=KEY)
    assert resp.status_code == 200


def test_email_rejects_invalid_address(client):
    resp = client.post(f"/api/monthly/batch/{BATCH}/email", json={"email": "x@y.z\nBcc: a@b.c"}, headers=KEY)
    assert resp.status_code == 400


def test_email_smtp_failure_is_502_without_leaking_recipient(client, fake_smtp, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")
    fake_smtp.fail_with = smtplib.SMTPServerDisconnected("gone")
    resp = client.post(f"/api/monthly/batch/{BATCH}/email", json={"email": RECIPIENT}, headers=KEY)
    assert resp.status_code == 502
    assert RECIPIENT not in resp.get_data(as_text=True)


def test_email_unknown_batch_is_404(client):
    resp = client.post("/api/monthly/batch/MONTHLY-209901/email", json={"email": RECIPIENT}, headers=KEY)
    assert resp.status_code == 404


def test_email_bad_batch_id_is_400(client):
    resp = client.post("/api/monthly/batch/MONTHLY-2023/email", json={"email": RECIPIENT}, headers=KEY)
    assert resp.status_code == 400


# ── 報告納入門檻（report_view） ─────────────────────────────────────


def _rule(code: str) -> RuleResult:
    if code in ("TSTX", "TSTP"):
        text = "限使用。" if code == "TSTX" else "一般說明文字。"
        return RuleResult(code=code, source="payment", name=code, payment_text=text,
                          effective_from="2023-01-01", effective_to="2910-12-31",
                          article_location=None, article_full_text=None, article_source=None, found=True)
    return not_found(code)


def _case(case_id: str, *, total: str | None, codes: list[str]):
    orders = [
        {"p3": "2", "p4": code, "p10": "1.0", "p11": "1", "p12": "400", "p13": str(i + 1)}
        for i, code in enumerate(codes)
    ]
    payload = {"batch": BATCH, "case_seq": case_id, "visit_date": "1120718", "total_points": total,
               "primary_diagnosis": "S00123A", "secondary_diagnoses": [], "orders": orders}
    return audit_case(case_id, payload, lookup=_rule)


def _view(*cases):
    flagged = tuple(c for c in cases if c.findings)
    batch = BatchAudit(batch=BATCH, cases_total=len(cases), cases=flagged, report=aggregate_batch(len(cases), flagged))
    return report_view(batch)


def test_total_points_must_be_strictly_greater_than_1000():
    assert [c.case_id for c in _view(_case("A", total="1000", codes=["TSTX"])).cases] == []
    assert [c.case_id for c in _view(_case("B", total="1000.5", codes=["TSTX"])).cases] == ["B"]


def test_non_numeric_or_missing_total_points_excluded():
    assert _view(_case("C", total=None, codes=["TSTX"])).cases == ()
    assert _view(_case("D", total="n/a", codes=["TSTX"])).cases == ()


def test_only_regulation_findings_kept_inside_included_case():
    view = _view(_case("E", total="2000", codes=["TSTX", "TSTNONE"]))
    assert [f.code for f in view.cases[0].findings] == ["TSTX"]


def test_case_without_regulation_findings_is_dropped():
    assert _view(_case("F", total="2000", codes=["TSTNONE"])).cases == ()


def test_report_totals_recomputed_after_view():
    view = _view(_case("G", total="2000", codes=["TSTX", "TSTNONE"]), _case("H", total="10", codes=["TSTX"]))
    assert view.report["totals"]["cases_flagged"] == 1
    assert view.report["totals"]["findings"] == 1
    assert view.cases_total == 2  # 批次總數仍為全部案件
