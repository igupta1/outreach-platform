"""NtfyNotifier — ntfy.sh push alert (build-plan B5, operator-chosen).

Free and account-less: an HTTP POST to {server}/{topic} pushes to any device
subscribed to that topic in the ntfy app. Never raises — on any failure it logs
and returns False so the reply-freeze proceeds regardless.
"""

from __future__ import annotations

import logging

import httpx

from system_b import config
from system_b.notify.base import Notifier

log = logging.getLogger("system_b.notify")


class NtfyNotifier(Notifier):
    def __init__(
        self,
        *,
        topic: str | None = None,
        server: str | None = None,
        priority: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.topic = topic or config.NTFY_TOPIC
        self.server = (server or config.NTFY_SERVER).rstrip("/")
        self.priority = priority or config.NTFY_PRIORITY
        self._client = client

    def notify(self, subject: str, body: str) -> bool:
        if not self.topic:
            log.warning("NtfyNotifier not configured (no NTFY_TOPIC); alert dropped: %s", subject)
            return False
        # ntfy headers must be latin-1 safe; strip the emoji/non-ascii from the
        # Title (it stays in the body) so the request can't fail on encoding.
        title = subject.encode("ascii", "ignore").decode().strip() or "System B alert"
        headers = {"Title": title, "Priority": str(self.priority), "Tags": "email,warning"}
        try:
            client = self._client or httpx.Client(timeout=15)
            try:
                r = client.post(f"{self.server}/{self.topic}",
                                content=body.encode("utf-8"), headers=headers)
                r.raise_for_status()
                return True
            finally:
                if self._client is None:
                    client.close()
        except Exception as exc:  # noqa: BLE001 — alert must never crash a freeze
            log.error("NtfyNotifier failed (%s): %s", type(exc).__name__, exc)
            return False
