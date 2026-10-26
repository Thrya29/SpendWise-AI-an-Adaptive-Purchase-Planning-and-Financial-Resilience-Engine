import smtplib
from typing import Any, ClassVar

import pytest

from app.core import mailer
from app.core.config import get_settings


def test_headers_cannot_be_injected() -> None:
    msg = mailer.build_message("a@example.com", "Buy Shoes\r\nBcc: evil@example.com", "body")
    assert msg["Subject"] == "Buy Shoes Bcc: evil@example.com" and msg["Bcc"] is None


class FakeSMTP:
    instances: ClassVar[list["FakeSMTP"]] = []

    def __init__(self, host: str, port: int, timeout: float, **_: Any) -> None:
        self.calls: list[str] = [f"connect {host}:{port}"]
        FakeSMTP.instances.append(self)

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *_: object) -> None:
        self.calls.append("quit")

    def starttls(self, context: Any) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login {user}:{password}")

    def send_message(self, msg: Any) -> None:
        self.calls.append(f"send {msg['To']}")


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SPENDWISE_SMTP_HOST", "smtp.example")
    monkeypatch.setenv("SPENDWISE_SMTP_USERNAME", "bot")
    monkeypatch.setenv("SPENDWISE_SMTP_PASSWORD", "s3cret")
    get_settings.cache_clear()
    FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    yield
    get_settings.cache_clear()


async def test_send_uses_starttls_and_login(configured: None) -> None:
    await mailer.send_email("a@example.com", "Hi", "Hello")
    assert FakeSMTP.instances[0].calls == [
        "connect smtp.example:587", "starttls", "login bot:s3cret", "send a@example.com", "quit",
    ]  # fmt: skip


async def test_failures_become_mail_errors(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: Any, **__: Any) -> None:
        raise ConnectionRefusedError

    monkeypatch.setattr(smtplib, "SMTP", refuse)
    with pytest.raises(mailer.MailError, match="ConnectionRefusedError"):
        await mailer.send_email("a@example.com", "Hi", "Hello")


async def test_disabled_without_a_host() -> None:
    get_settings.cache_clear()
    assert not mailer.mail_enabled()
    with pytest.raises(mailer.MailError, match="not configured"):
        await mailer.send_email("a@example.com", "Hi", "Hello")
