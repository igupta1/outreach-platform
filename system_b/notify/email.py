"""EmailNotifier — the email-to-self alert (build-plan B5, operator-chosen).

Plain SMTP (stdlib), configured from env (SMTP_HOST/PORT/USER/PASSWORD,
ALERT_EMAIL_FROM/TO). Never raises: on any failure it logs and returns False so
the caller (reply-freeze) proceeds regardless.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from system_b import config
from system_b.notify.base import Notifier

log = logging.getLogger("system_b.notify")


class EmailNotifier(Notifier):
    def __init__(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        sender: str | None = None,
        recipient: str | None = None,
    ) -> None:
        self.host = host or config.SMTP_HOST
        self.port = port or config.SMTP_PORT
        self.user = user or config.SMTP_USER
        self.password = password or config.SMTP_PASSWORD
        self.sender = sender or config.ALERT_EMAIL_FROM
        self.recipient = recipient or config.ALERT_EMAIL_TO

    def notify(self, subject: str, body: str) -> bool:
        if not (self.host and self.sender and self.recipient):
            log.warning("EmailNotifier not configured; alert dropped: %s", subject)
            return False
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.sender
        msg["To"] = self.recipient
        msg.set_content(body)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=20) as smtp:
                smtp.ehlo()
                if self.port in (587, 25):
                    smtp.starttls()
                    smtp.ehlo()
                if self.user and self.password:
                    smtp.login(self.user, self.password)
                smtp.send_message(msg)
            return True
        except Exception as exc:  # noqa: BLE001 — alert must never crash a freeze
            log.error("EmailNotifier failed (%s): %s", type(exc).__name__, exc)
            return False
