"""Helper per i test delle email: SMTP finto che cattura i messaggi."""

from __future__ import annotations

import re
import smtplib
from email.message import EmailMessage
from typing import List, Optional

# Importati qui, prima che un test patchi ``engine.get_async_session_maker``:
# importati dopo, legherebbero per sempre il loro nome alla sessione del test.
import src.api.admin  # noqa: F401
import src.api.admin_auth_mode  # noqa: F401
import src.api.admin_smtp  # noqa: F401
import src.auth.password_setup as ps
import src.data.audit as audit
import src.notifications.smtp_settings as smtp_settings

TOKEN_RE = re.compile(r"/set-password#token=([A-Za-z0-9_\-]+)")


class FakeSMTP:
    """Sostituto di ``smtplib.SMTP``: registra i messaggi in ``FakeSMTP.sent``."""

    sent: List[EmailMessage] = []
    logins: List[tuple] = []
    fail_with: Optional[Exception] = None

    def __init__(self, host, port, timeout=None, **_kw):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        pass

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        FakeSMTP.logins.append((user, password))

    def send_message(self, msg):
        if FakeSMTP.fail_with is not None:
            raise FakeSMTP.fail_with
        FakeSMTP.sent.append(msg)


def install_fake_smtp(monkeypatch) -> type[FakeSMTP]:
    FakeSMTP.sent = []
    FakeSMTP.logins = []
    FakeSMTP.fail_with = None
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def patch_session_makers(monkeypatch, sm) -> None:
    """I moduli email importano ``get_async_session_maker`` per nome."""
    for mod in (ps, audit, smtp_settings):
        monkeypatch.setattr(mod, "get_async_session_maker", lambda: sm)


async def configure_smtp(
    tenant_id: str = "default", *, username: Optional[str] = None, password=None
) -> None:
    from src.notifications.smtp_settings import invalidate_cache, upsert_smtp_settings

    await upsert_smtp_settings(
        tenant_id,
        enabled=True,
        host="smtp.test",
        port=587,
        security="starttls",
        username=username,
        password=password,
        clear_password=False,
        from_address="noreply@aion.test",
        from_name="AION",
        reply_to=None,
        email_language="it",
        actor_user_id=None,
    )
    invalidate_cache(tenant_id)


def body_of(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain",))
    return part.get_content() if part is not None else ""


def token_from(msg: EmailMessage) -> str:
    m = TOKEN_RE.search(body_of(msg))
    assert m, "link /set-password non trovato nell'email"
    return m.group(1)
