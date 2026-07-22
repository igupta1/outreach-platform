"""B5 — reply-freeze handler + the FastAPI receiver (token guard, routing)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from system_b.sending import FakeSender
from system_b.tests.test_sequence import FakeAirtable
from system_b.webhooks.app import create_app
from system_b.webhooks.reply import handle_reply_event, handle_unsubscribe_event


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def notify(self, subject, body):
        self.sent.append((subject, body))
        return True


def _row():
    return {"rec1": {"firm_name": "Acme", "email": "dana@acme.com",
                     "stage": "email_1_sent", "smartlead_lead_id": "L1",
                     "smartlead_campaign_id": "99"}}


_REPLY = {
    "event_type": "EMAIL_REPLY", "to_email": "dana@acme.com", "subject": "Re: hi",
    "reply_body": "<p>interested, tell me more</p>", "preview_text": "interested, tell me more",
    "time_replied": "2026-07-11T10:00:00Z", "campaign_id": 99,
}


def test_reply_freezes_pauses_and_alerts():
    at, s, n = FakeAirtable(_row()), FakeSender(), FakeNotifier()
    res = handle_reply_event(_REPLY, at, s, n)
    assert res["status"] == "frozen" and res["paused"] is True
    f = at.records["rec1"]
    assert f["stage"] == "replied" and f["frozen"] is True
    assert f["replied_at"] == "2026-07-11" and "interested" in f["last_reply"]
    assert s.paused == [("99", "L1")]
    assert n.sent and "Acme" in n.sent[0][0]


def test_reply_from_unknown_lead():
    at, s, n = FakeAirtable(_row()), FakeSender(), FakeNotifier()
    res = handle_reply_event({**_REPLY, "to_email": "stranger@x.com"}, at, s, n)
    assert res["status"] == "unknown_lead"
    assert not s.paused and not n.sent


def test_reply_without_smartlead_ids_still_freezes():
    at = FakeAirtable({"rec1": {"firm_name": "Acme", "email": "dana@acme.com",
                                "stage": "email_1_sent"}})
    res = handle_reply_event(_REPLY, at, FakeSender(), FakeNotifier())
    assert res["status"] == "frozen" and res["paused"] is False
    assert at.records["rec1"]["frozen"] is True


def test_unsubscribe_marks_do_not_contact():
    at, s = FakeAirtable(_row()), FakeSender()
    res = handle_unsubscribe_event({"event_type": "LEAD_UNSUBSCRIBED", "to_email": "dana@acme.com"},
                                   at, s, FakeNotifier())
    assert res["status"] == "do_not_contact"
    assert at.records["rec1"]["stage"] == "do_not_contact"
    assert s.paused == [("99", "L1")]


# --- FastAPI receiver -----------------------------------------------------

def _client(at, s, n):
    return TestClient(create_app(lambda: (at, s, n)))


def test_endpoint_routes_reply(monkeypatch):
    import system_b.config as config
    monkeypatch.setattr(config, "WEBHOOK_TOKEN", "secret")
    at, s, n = FakeAirtable(_row()), FakeSender(), FakeNotifier()
    r = _client(at, s, n).post("/webhooks/smartlead", params={"token": "secret"}, json=_REPLY)
    assert r.status_code == 200 and r.json()["status"] == "frozen"


def test_endpoint_rejects_bad_token(monkeypatch):
    import system_b.config as config
    monkeypatch.setattr(config, "WEBHOOK_TOKEN", "secret")
    at, s, n = FakeAirtable(_row()), FakeSender(), FakeNotifier()
    r = _client(at, s, n).post("/webhooks/smartlead", params={"token": "wrong"}, json=_REPLY)
    assert r.status_code == 401
    assert not at.records["rec1"].get("frozen")


def test_endpoint_ignores_unknown_event(monkeypatch):
    import system_b.config as config
    monkeypatch.setattr(config, "WEBHOOK_TOKEN", "")
    at, s, n = FakeAirtable(_row()), FakeSender(), FakeNotifier()
    r = _client(at, s, n).post("/webhooks/smartlead", json={"event_type": "EMAIL_OPEN"})
    assert r.status_code == 200 and r.json()["status"] == "ignored"


def test_health():
    r = _client(FakeAirtable(), FakeSender(), FakeNotifier()).get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True
