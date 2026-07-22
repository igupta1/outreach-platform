"""Track H — the operator API service (auth, upload, queue, generate, cards,
actions, LinkedIn). All offline: fake Airtable + FakeSender, scheduler off."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from system_b.api.app import create_app
from system_b.sending import FakeSender
from system_b.tests.test_sequence import FakeAirtable

TOKEN = "testtoken"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

_CSV = (
    "Company Name for Emails,Website,City,State,First Name,Email,Person Linkedin Url,# Employees\n"
    "Acme CFO,https://acme.com,Denver,CO,Dana,dana@acme.com,http://linkedin.com/in/dana,5\n"
    "Big Co,https://bigco.com,Austin,TX,Sam,sam@bigco.com,,50\n"        # headcount>10 -> skip
    "No Site,,,,,,\n"                                                    # no website -> skip
).encode()


@pytest.fixture
def client(monkeypatch):
    import system_b.config as config
    monkeypatch.setattr(config, "UI_AUTH_TOKEN", TOKEN)
    at, sender = FakeAirtable(), FakeSender()
    app = create_app(lambda: (at, sender, None), enable_scheduler=False)
    c = TestClient(app)
    c.at, c.sender = at, sender
    return c


# --- auth -----------------------------------------------------------------

def test_health_needs_no_auth(client):
    assert client.get("/health").json() == {"ok": True}


def test_api_requires_bearer(client):
    assert client.get("/api/prospects").status_code == 401


# --- H1 upload + queue ----------------------------------------------------

def test_upload_creates_and_dedups(client):
    r = client.post("/api/prospects/upload",
                    files={"file": ("a.csv", _CSV, "text/csv")},
                    data={"niche": "cfo"}, headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 1 and body["niche_pack"] == "cfo"
    reasons = {s["reason"].split()[0] for s in body["skipped_rows"]}
    assert "headcount" in " ".join(s["reason"] for s in body["skipped_rows"])
    assert "no" in " ".join(s["reason"] for s in body["skipped_rows"])

    # re-upload -> Acme now a duplicate domain -> 0 created
    r2 = client.post("/api/prospects/upload", files={"file": ("a.csv", _CSV, "text/csv")},
                     data={"niche": "cfo"}, headers=AUTH)
    assert r2.json()["created"] == 0


def test_queue_reports_status(client):
    client.at.create_prospect({"firm_name": "A", "website": "https://a.com", "stage": "researched"})
    client.at.create_prospect({"firm_name": "B", "website": "https://b.com", "stage": "email_1_sent"})
    client.at.create_prospect({"firm_name": "C", "website": "https://c.com", "stage": "do_not_contact"})
    body = client.get("/api/prospects", headers=AUTH).json()
    assert body["counts"]["pending"] == 1
    assert body["counts"]["in_sequence"] == 1
    assert body["counts"]["do_not_contact"] == 1


# --- H2 generate ----------------------------------------------------------

def test_generate_starts_job(client, monkeypatch):
    import system_b.api.routes as routes

    class _Job:
        def as_dict(self):
            return {"job_id": "j1", "status": "running"}

    monkeypatch.setattr(routes, "start_generate", lambda at, **kw: _Job())
    r = client.post("/api/generate", json={"emails": 5, "pack": "cfo"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["job_id"] == "j1"


def test_generate_status_unknown_job(client):
    assert client.get("/api/generate/status", params={"job_id": "nope"}, headers=AUTH).status_code == 404


# --- H3 cards + actions ---------------------------------------------------

def _seed_card(at, *, channel="email", step=1, review="pending"):
    payload = {"channel": channel, "step": step, "step_label": f"Email {step} of 3",
               "prospect": {"firm_name": "Acme"}, "message": {"subject": "s", "body": "b"},
               "gift_leads": [], "flags": [], "history": []}
    rec = at.create_prospect({
        "firm_name": "Acme", "email": "dana@acme.com", "stage": "researched",
        "current_step": str(step), "smartlead_campaign_id": "99", "eligible_for_send": True,
        "queued_message": "Subject: s\n\nhey dana,\n\nbody", "pending_lead_ids": "p1",
        "review_status": review, "card_json": json.dumps(payload),
    })
    return rec["id"]


def test_cards_lists_pending_with_total(client):
    rid = _seed_card(client.at)
    body = client.get("/api/cards", headers=AUTH).json()
    assert body["count"] == 1 and body["total"] == 1
    assert body["cards"][0]["record_id"] == rid
    assert body["cards"][0]["step_label"] == "Email 1 of 3"


def test_cards_channel_filter(client):
    _seed_card(client.at, channel="email")
    _seed_card(client.at, channel="linkedin")
    email = client.get("/api/cards", params={"channel": "email"}, headers=AUTH).json()
    assert email["count"] == 1 and email["total"] == 2       # filtered 1, overall 2
    assert email["cards"][0]["channel"] == "email"
    bad = client.get("/api/cards", params={"channel": "sms"}, headers=AUTH)
    assert bad.status_code == 400


def test_approve_email_card_reports_approved_and_pushed(client):
    rid = _seed_card(client.at)
    r = client.post(f"/api/cards/{rid}/approve", json={}, headers=AUTH).json()
    assert r["approved"] is True and r["pushed"] is True
    assert client.sender.added and client.sender.added[0]["email"] == "dana@acme.com"
    assert client.at.records[rid]["stage"] == "email_1_sent"


def test_approve_blocked_when_not_eligible(client):
    # HARD send-safety gate: a card whose prospect isn't eligible cannot push —
    # approve returns approved=false and nothing hits Smartlead.
    rid = _seed_card(client.at)
    client.at.update(rid, {"eligible_for_send": False})
    r = client.post(f"/api/cards/{rid}/approve", json={}, headers=AUTH).json()
    assert r["approved"] is False and "NotEligible" in r["error"]
    assert not client.sender.added
    assert client.at.records[rid]["stage"] == "researched"       # unchanged

    # flip eligible -> now it pushes
    client.post(f"/api/prospects/{rid}/eligible", params={"eligible": True}, headers=AUTH)
    r2 = client.post(f"/api/cards/{rid}/approve", json={}, headers=AUTH).json()
    assert r2["approved"] is True and r2["pushed"] is True


def test_approve_push_failure_keeps_card_pending(client, monkeypatch):
    rid = _seed_card(client.at)

    def boom(*a, **k):
        raise RuntimeError("smartlead 500")
    monkeypatch.setattr(client.sender, "add_lead", boom)

    r = client.post(f"/api/cards/{rid}/approve", json={}, headers=AUTH).json()
    assert r["approved"] is False and r["pushed"] is False and "smartlead 500" in r["error"]
    # unchanged: still pending, no stage advance (never approved-but-unsent)
    assert client.at.records[rid].get("review_status") == "pending"
    assert client.at.records[rid]["stage"] == "researched"


def test_edit_lints_dollar_and_warns_on_date(client):
    rid = _seed_card(client.at)
    r = client.post(f"/api/cards/{rid}/edit",
                    json={"subject": "x", "body": "they raised $5,000,000 yesterday"},
                    headers=AUTH).json()
    assert r["status"] == "edited"
    assert "$" not in r["cleaned_body"] and "5,000,000" not in r["cleaned_body"]
    assert any("dollar" in w for w in r["warnings"])
    assert any("date" in w for w in r["warnings"])
    stored = client.at.records[rid]["queued_message"]
    assert "$" not in stored and stored.startswith("Subject: x")


def test_reject_and_skip(client):
    rid = _seed_card(client.at)
    assert client.post(f"/api/cards/{rid}/reject", headers=AUTH).json()["status"] == "rejected"
    assert client.at.records[rid]["stage"] == "do_not_contact"
    rid2 = _seed_card(client.at)
    assert client.post(f"/api/cards/{rid2}/skip", headers=AUTH).json()["status"] == "skipped"


# --- H4 LinkedIn ----------------------------------------------------------

def test_linkedin_queue_empty_and_connection_toggle(client):
    assert client.get("/api/linkedin/queue", headers=AUTH).json()["count"] == 0
    rid = client.at.create_prospect({"firm_name": "Z"})["id"]
    r = client.post(f"/api/linkedin/{rid}/connection", params={"accepted": True}, headers=AUTH)
    assert r.json()["connection_accepted"] is True
    assert client.at.records[rid]["connection_accepted"] is True


def _seed_li_card(at):
    payload = {"channel": "linkedin", "step": "dm_1", "step_label": "DM 1 of 2",
               "prospect": {"firm_name": "Acme"}, "message": {"subject": "", "body": "hey, spam check"},
               "gift_leads": [], "flags": [], "history": []}
    import json
    rec = at.create_prospect({
        "firm_name": "Acme", "stage": "email_1_sent", "eligible_for_send": True,
        "li_review_status": "pending", "li_step": "dm_1", "li_message": "hey, spam check",
        "li_card_json": json.dumps(payload),
    })
    return rec["id"]


def test_linkedin_card_appears_and_approve_routes_to_queue(client):
    rid = _seed_li_card(client.at)
    # shows under the linkedin channel, not email
    li_cards = client.get("/api/cards", params={"channel": "linkedin"}, headers=AUTH).json()
    assert li_cards["count"] == 1 and li_cards["cards"][0]["channel"] == "linkedin"
    assert client.get("/api/cards", params={"channel": "email"}, headers=AUTH).json()["count"] == 0
    # approve with channel=linkedin -> queue, email stage untouched
    r = client.post(f"/api/cards/{rid}/approve", params={"channel": "linkedin"}, json={}, headers=AUTH).json()
    assert r["approved"] is True and r["pushed"] is False and r["channel"] == "linkedin"
    assert client.at.records[rid]["li_review_status"] == "approved"
    assert client.at.records[rid]["stage"] == "email_1_sent"


def test_linkedin_queue_lists_connect_and_dm(client):
    client.at.create_prospect({"firm_name": "C1", "li_connect_pending": True})
    rid = _seed_li_card(client.at)
    client.at.update(rid, {"li_review_status": "approved"})
    items = client.get("/api/linkedin/queue", headers=AUTH).json()["items"]
    kinds = sorted(it["kind"] for it in items)
    assert kinds == ["connect", "dm_1"]
