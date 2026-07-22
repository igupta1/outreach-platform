"""Operator alerts (build-plan B5). On a reply the sequence freezes and the
operator is 'phone pinged' to take the thread — here, an email-to-self alert.

`Notifier` is pluggable; `EmailNotifier` sends via SMTP, `LoggingNotifier` is
the safe fallback when SMTP isn't configured (a freeze must never depend on the
alert succeeding).
"""

from __future__ import annotations

from system_b.notify.base import LoggingNotifier, Notifier, default_notifier
from system_b.notify.email import EmailNotifier
from system_b.notify.ntfy import NtfyNotifier

__all__ = ["Notifier", "LoggingNotifier", "EmailNotifier", "NtfyNotifier", "default_notifier"]
