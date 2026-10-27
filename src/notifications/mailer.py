"""Invio email via SMTP (stdlib ``smtplib``), eseguito in un thread."""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Optional

from .smtp_settings import SmtpConfig, get_smtp_config

logger = logging.getLogger("aion.notifications.mailer")

SMTP_TIMEOUT_SEC = 15


class EmailSendError(Exception):
    """Invio fallito. ``code`` e' uno tra ``smtp_not_configured``,
    ``smtp_auth_failed``, ``smtp_connection_failed``, ``smtp_send_failed``."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


def build_message(
    cfg: SmtpConfig, *, to: str, subject: str, text: str, html: Optional[str]
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = (
        formataddr((cfg.from_name, cfg.from_address))
        if cfg.from_name
        else cfg.from_address
    )
    msg["To"] = to
    if cfg.reply_to:
        msg["Reply-To"] = cfg.reply_to
    domain = cfg.from_address.rsplit("@", 1)[-1] if "@" in cfg.from_address else None
    msg["Message-ID"] = make_msgid(domain=domain)
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def _send_sync(cfg: SmtpConfig, msg: EmailMessage) -> None:
    ctx = ssl.create_default_context()
    try:
        if cfg.security == "ssl":
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(
                cfg.host, cfg.port, timeout=SMTP_TIMEOUT_SEC, context=ctx
            )
        else:
            smtp = smtplib.SMTP(cfg.host, cfg.port, timeout=SMTP_TIMEOUT_SEC)
        with smtp:
            smtp.ehlo()
            if cfg.security == "starttls":
                smtp.starttls(context=ctx)
                smtp.ehlo()
            if cfg.username:
                smtp.login(cfg.username, cfg.password or "")
            smtp.send_message(msg)
    # SMTPException deriva da OSError: le sottoclassi vanno intercettate prima.
    except smtplib.SMTPAuthenticationError as e:
        raise EmailSendError("smtp_auth_failed", str(e)) from e
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected) as e:
        raise EmailSendError("smtp_connection_failed", str(e)) from e
    except smtplib.SMTPException as e:
        raise EmailSendError("smtp_send_failed", str(e)) from e
    except (OSError, ssl.SSLError) as e:
        raise EmailSendError("smtp_connection_failed", str(e)) from e


async def send_email(
    tenant_id: str,
    *,
    to: str,
    subject: str,
    text: str,
    html: Optional[str] = None,
    cfg: Optional[SmtpConfig] = None,
) -> None:
    """Invia un'email; solleva :class:`EmailSendError` in caso di errore."""
    cfg = cfg or await get_smtp_config(tenant_id)
    if cfg is None:
        raise EmailSendError("smtp_not_configured")
    msg = build_message(cfg, to=to, subject=subject, text=text, html=html)
    await asyncio.to_thread(_send_sync, cfg, msg)
    logger.info("Email '%s' inviata (tenant %s)", subject, tenant_id)
