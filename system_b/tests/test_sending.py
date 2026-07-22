"""B1 — EmailSender interface, FakeSender, and SmartleadSender (HTTP mocked)."""

from __future__ import annotations

import pytest

from system_b.sending import FakeSender, SmartleadError, SmartleadSender


# --- FakeSender -----------------------------------------------------------

def test_fake_sender_records_and_returns_ids():
    s = FakeSender()
    lid = s.add_lead("camp1", email="a@x.com", first_name="Al", subject="hi", email_1="body")
    assert lid == "fake-lead-1"
    assert s.added[0]["email"] == "a@x.com"
    assert s.find_lead_id("camp1", "A@X.com") == "fake-lead-1"

    s.set_followup("camp1", lid, step=2, body="more", email="a@x.com")
    assert s.followups[0] == {"campaign_id": "camp1", "lead_id": lid, "step": 2,
                              "body": "more", "email": "a@x.com"}
    s.pause_lead("camp1", lid)
    s.resume_lead("camp1", lid)
    assert s.paused == [("camp1", lid)] and s.resumed == [("camp1", lid)]


# --- SmartleadSender with a mocked httpx client ---------------------------

class _Resp:
    def __init__(self, status=200, data=None, text=""):
        self.status_code = status
        self._data = data
        self.text = text
        self.content = b"x" if (data is not None or text) else b""

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


class _Http:
    """Routes by (method, url-substring). Records every call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, json=None, params=None):
        self.calls.append({"method": method, "url": url, "json": json, "params": params})
        for (m, sub), resp in self.routes.items():
            if m == method and sub in url:
                return resp
        return _Resp(200, {})


def _sender(routes):
    return SmartleadSender(api_key="k", base_url="https://api.test/v1", client=_Http(routes))


def test_add_lead_posts_custom_fields_and_resolves_id():
    routes = {
        ("POST", "/campaigns/55/leads"): _Resp(200, {"ok": True}),
        ("GET", "/leads/"): _Resp(200, {"id": 777}),
    }
    s = _sender(routes)
    lid = s.add_lead("55", email="dora@x.com", first_name="Dora", subject="a subj", email_1="line1\nline2")
    assert lid == "777"
    post = next(c for c in s._client.calls if c["method"] == "POST")
    lead = post["json"]["lead_list"][0]
    assert lead["email"] == "dora@x.com" and lead["first_name"] == "Dora"
    assert lead["custom_fields"]["subject"] == "a subj"
    # newlines converted to <br> for the HTML body
    assert "<br>" in lead["custom_fields"]["email_1"]
    # api_key is passed as a query param, never in the path
    assert post["params"]["api_key"] == "k"


def test_add_lead_raises_when_id_unresolvable():
    routes = {
        ("POST", "/campaigns/55/leads"): _Resp(200, {"ok": True}),
        ("GET", "/leads/"): _Resp(200, {}),      # no id
    }
    with pytest.raises(SmartleadError):
        _sender(routes).add_lead("55", email="x@x.com", first_name=None, subject="s", email_1="b")


def test_add_lead_raises_when_upload_skipped():
    # Smartlead silently skips the add (cross-campaign dup / block list / unsub):
    # upload_count=0. The global id still resolves, so without the guard this would
    # be a false "sent" — assert it raises instead.
    routes = {
        ("POST", "/campaigns/55/leads"): _Resp(200, {"ok": True, "upload_count": 0,
                                                     "already_added_to_campaign": 0}),
        ("GET", "/leads/"): _Resp(200, {"id": 777}),
    }
    with pytest.raises(SmartleadError):
        _sender(routes).add_lead("55", email="dup@x.com", first_name=None, subject="s", email_1="b")


def test_set_followup_updates_email_variable():
    s = _sender({("POST", "/campaigns/55/leads/777"): _Resp(200, {"ok": True})})
    s.set_followup("55", "777", step=2, body="follow up body", email="dana@x.com")
    call = s._client.calls[-1]
    assert call["url"].endswith("/campaigns/55/leads/777")
    assert call["json"]["email"] == "dana@x.com"          # required by Smartlead
    assert "email_2" in call["json"]["custom_fields"]


def test_pause_and_resume_hit_right_paths():
    s = _sender({
        ("POST", "/pause"): _Resp(200, {"ok": True}),
        ("POST", "/resume"): _Resp(200, {"ok": True}),
    })
    s.pause_lead("55", "777")
    s.resume_lead("55", "777")
    assert s._client.calls[0]["url"].endswith("/campaigns/55/leads/777/pause")
    assert s._client.calls[1]["url"].endswith("/campaigns/55/leads/777/resume")


def test_error_status_raises_smartlead_error():
    s = _sender({("POST", "/campaigns/55/leads"): _Resp(422, text="bad payload")})
    with pytest.raises(SmartleadError):
        s.add_lead("55", email="x@x.com", first_name=None, subject="s", email_1="b")
