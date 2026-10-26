"""Plain SMTP email. Optional: without ``SPENDWISE_SMTP_HOST`` nothing is ever sent."""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import get_settings


class MailError(RuntimeError):
    """The mail server refused or could not be reached."""


def mail_enabled() -> bool:
    return bool(get_settings().smtp_host)


def _header(value: str) -> str:
    # User-controlled text (item names) must never add headers.
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())[:200]


def build_message(to: str, subject: str, text: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = get_settings().smtp_from
    msg["To"] = _header(to)
    msg["Subject"] = _header(subject)
    msg.set_content(text)
    return msg


def _send_sync(msg: EmailMessage) -> None:
    s = get_settings()
    assert s.smtp_host is not None
    context = ssl.create_default_context()
    try:
        if s.smtp_port == 465:
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                s.smtp_host, s.smtp_port, timeout=20, context=context
            )
        else:
            server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20)
        with server:
            if s.smtp_port != 465 and s.smtp_starttls:
                server.starttls(context=context)
            password = s.smtp_password.get_secret_value() if s.smtp_password else ""
            if s.smtp_username and password:
                server.login(s.smtp_username, password)
            server.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"Could not send email: {type(exc).__name__}") from exc


async def send_email(to: str, subject: str, text: str) -> None:
    if not mail_enabled():
        raise MailError("Email is not configured on this server")
    await asyncio.to_thread(_send_sync, build_message(to, subject, text))
