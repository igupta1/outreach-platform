"""The `Notifier` interface + a logging fallback + the default selector."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from system_b import config

log = logging.getLogger("system_b.notify")


class Notifier(ABC):
    @abstractmethod
    def notify(self, subject: str, body: str) -> bool:
        """Send an operator alert. Returns True on success. MUST NOT raise —
        a failed alert can never be allowed to break a reply-freeze."""


class LoggingNotifier(Notifier):
    """No external dependency: writes the alert to the log. Always the fallback
    when SMTP isn't configured."""

    def notify(self, subject: str, body: str) -> bool:
        log.warning("ALERT %s | %s", subject, body.replace("\n", " ")[:400])
        return True


def default_notifier() -> Notifier:
    """Preference order (B5): ntfy.sh push -> SMTP email -> logging."""
    if config.NTFY_TOPIC:
        from system_b.notify.ntfy import NtfyNotifier

        return NtfyNotifier()
    if config.SMTP_HOST and config.ALERT_EMAIL_TO and config.ALERT_EMAIL_FROM:
        from system_b.notify.email import EmailNotifier

        return EmailNotifier()
    return LoggingNotifier()
