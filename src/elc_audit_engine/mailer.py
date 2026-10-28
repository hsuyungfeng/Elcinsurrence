"""郵寄報告：以標準庫 smtplib／email 寄出自包含 HTML 報告。

SMTP 設定來自環境變數：
- `SMTP_HOST`：未設定即為「開發模式」——不連線，改把郵件寫成 `.eml` 檔（永不因缺設定而失敗）。
- `SMTP_PORT`：預設 587（STARTTLS）；465 使用 SMTP over SSL。
- `SMTP_USER`／`SMTP_PASSWORD`：有 user 才登入。
- `SMTP_FROM`：預設 `noreply@elcinsurrence.local`。

隱私：郵件內容含身分證字號、姓名與出生日期。日誌只記錄批次與動作，**不記錄收件人與內容**。
"""

from __future__ import annotations

import logging
import os
import re
import smtplib
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage

logger = logging.getLogger(__name__)

DEFAULT_SMTP_PORT = 587
DEFAULT_FROM = "noreply@elcinsurrence.local"
SMTP_TIMEOUT_SECONDS = 30

# 保守的信箱格式檢查（同時擋換行與分隔符，避免標頭注入）。
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


class MailError(Exception):
    """寄信失敗（SMTP 連線、認證或傳送錯誤）；訊息不含收件人或內容。"""


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    user: str | None
    password: str | None
    sender: str


def smtp_config_from_env(env: Mapping[str, str] | None = None) -> SmtpConfig | None:
    """讀取 SMTP 設定；未設定 `SMTP_HOST` 回 None（開發模式）。"""
    source = os.environ if env is None else env
    host = (source.get("SMTP_HOST") or "").strip()
    if not host:
        return None
    raw_port = (source.get("SMTP_PORT") or "").strip()
    try:
        port = int(raw_port) if raw_port else DEFAULT_SMTP_PORT
    except ValueError:
        logger.warning("SMTP_PORT 不是整數，改用預設 %s", DEFAULT_SMTP_PORT)
        port = DEFAULT_SMTP_PORT
    return SmtpConfig(
        host=host,
        port=port,
        user=(source.get("SMTP_USER") or "").strip() or None,
        password=source.get("SMTP_PASSWORD") or None,
        sender=(source.get("SMTP_FROM") or "").strip() or DEFAULT_FROM,
    )


def is_valid_email(address: str) -> bool:
    return len(address) <= 254 and bool(_EMAIL_RE.match(address))


def build_report_email(*, to: str, sender: str, batch: str, html_report: str) -> EmailMessage:
    """建立郵件：純文字說明＋HTML 報告附件（可直接用瀏覽器開啟）。"""
    message = EmailMessage()
    message["Subject"] = f"當月申報預審報告 {batch}"
    message["From"] = sender
    message["To"] = to
    message.set_content(
        f"您好，\n\n附件為 {batch} 當月申報預審報告（自包含 HTML，可直接以瀏覽器開啟）。\n"
        "本報告含身分證字號、姓名與出生日期等個人資料，請依院內規範保管，勿轉寄至未授權人員。\n"
        "報告為比對輔助工具，不構成給付判定。\n"
    )
    message.add_attachment(
        html_report.encode("utf-8"),
        maintype="text",
        subtype="html",
        filename=f"monthly_report_{batch}.html",
    )
    return message


def send_message(config: SmtpConfig, message: EmailMessage) -> None:
    """透過 SMTP 寄出。失敗一律轉為 MailError（不外洩收件人與內容）。"""
    try:
        if config.port == 465:
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                config.host, config.port, timeout=SMTP_TIMEOUT_SECONDS, context=ssl.create_default_context()
            )
        else:
            client = smtplib.SMTP(config.host, config.port, timeout=SMTP_TIMEOUT_SECONDS)
        with client:
            client.ehlo()
            if config.port != 465:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if config.user:
                client.login(config.user, config.password or "")
            client.send_message(message)
    except (smtplib.SMTPException, OSError, ValueError) as exc:
        raise MailError(type(exc).__name__) from exc


def write_eml(message: EmailMessage, out_dir: str, batch: str) -> str:
    """開發模式：把郵件寫入 `out_dir/mail_{batch}_{timestamp}.eml`，回傳檔名（不含路徑）。"""
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    name = f"mail_{batch}_{stamp}.eml"
    with open(os.path.join(out_dir, name), "wb") as f:
        f.write(message.as_bytes())
    return name
