"""B5 — operator-alert notifiers."""

from __future__ import annotations

from system_b.notify import EmailNotifier, LoggingNotifier, NtfyNotifier
from system_b.notify.base import default_notifier


def test_logging_notifier_always_succeeds():
    assert LoggingNotifier().notify("subj", "body") is True


def test_email_notifier_unconfigured_returns_false_never_raises():
    # No host/sender/recipient -> must degrade gracefully (a freeze can't depend
    # on the alert succeeding).
    n = EmailNotifier(host="", sender="", recipient="")
    assert n.notify("subj", "body") is False


def test_email_notifier_send_failure_is_swallowed():
    # Configured but the SMTP host is bogus -> returns False, does not raise.
    n = EmailNotifier(host="smtp.invalid.localhost", port=2525,
                      sender="a@x.com", recipient="me@x.com")
    assert n.notify("subj", "body") is False


def test_default_notifier_is_logging_without_any_channel(monkeypatch):
    import system_b.config as config
    monkeypatch.setattr(config, "NTFY_TOPIC", "")
    monkeypatch.setattr(config, "SMTP_HOST", "")
    assert isinstance(default_notifier(), LoggingNotifier)


def test_default_notifier_prefers_ntfy(monkeypatch):
    import system_b.config as config
    monkeypatch.setattr(config, "NTFY_TOPIC", "systemb-alerts-abc")
    assert isinstance(default_notifier(), NtfyNotifier)


class _FakeHttp:
    def __init__(self, status=200):
        self.status = status
        self.calls = []

    def post(self, url, content=None, headers=None):
        self.calls.append({"url": url, "content": content, "headers": headers})
        return _FakeResp(self.status)


class _FakeResp:
    def __init__(self, status):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_ntfy_posts_to_topic():
    http = _FakeHttp()
    n = NtfyNotifier(topic="mytopic", server="https://ntfy.sh", priority="high", client=http)
    assert n.notify("🔔 Reply from Acme", "someone replied") is True
    call = http.calls[0]
    assert call["url"] == "https://ntfy.sh/mytopic"
    assert call["content"] == b"someone replied"
    # emoji stripped from the ascii-only Title header, body untouched
    assert "Reply from Acme" in call["headers"]["Title"]
    assert call["headers"]["Priority"] == "high"


def test_ntfy_unconfigured_returns_false(monkeypatch):
    import system_b.config as config
    monkeypatch.setattr(config, "NTFY_TOPIC", "")   # nothing to fall back to
    assert NtfyNotifier(topic="", client=_FakeHttp()).notify("s", "b") is False


def test_ntfy_http_error_is_swallowed():
    n = NtfyNotifier(topic="t", client=_FakeHttp(status=500))
    assert n.notify("s", "b") is False
