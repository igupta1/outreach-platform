"""B3/B6/B7 — the sequence layer: row parsing, approve-and-send, the quota
scheduler, the timing guard, and follow-up generation."""

from __future__ import annotations

from datetime import date

import pytest

from system_b.clients.airtable_client import STAGES
from system_b.sending import FakeSender
from system_b.sequence import rows
from system_b.sequence.scheduler import (
    find_due_followups,
    find_new_prospects,
    guard_unready_followups,
    quota_run,
)
from system_b.sequence.send import approve_and_send
from system_b.tests.test_gift import FakeScraper, mk

TODAY = date(2026, 7, 8)


class FakeAirtable:
    """Rich enough for the sequence layer: records, table.all, find_by_email."""

    def __init__(self, rows_=None):
        self.records: dict[str, dict] = {r: dict(f) for r, f in (rows_ or {}).items()}
        self._n = 0

    def update(self, rid, fields):
        self.records.setdefault(rid, {}).update(fields)
        return {"id": rid, "fields": self.records[rid]}

    def set_stage(self, rid, stage):
        assert stage in STAGES, stage
        return self.update(rid, {"stage": stage})

    def get(self, rid):
        return {"id": rid, "fields": self.records.get(rid, {})}

    def create_prospect(self, fields):
        self._n += 1
        rid = f"auto{self._n}"
        self.records[rid] = dict(fields)
        return {"id": rid, "fields": self.records[rid]}

    def find_by_email(self, email):
        for rid, f in self.records.items():
            if (f.get("email") or "").lower() == email.lower():
                return {"id": rid, "fields": f}
        return None

    def ensure_schema(self):
        return {}

    class _T:
        def __init__(self, outer):
            self.outer = outer

        def all(self, **kw):
            return [{"id": r, "fields": f} for r, f in self.outer.records.items()]

    @property
    def table(self):
        return FakeAirtable._T(self)


# --- rows.py --------------------------------------------------------------

def test_parse_match_param():
    assert rows.parse_match_param("niche=dental") == ("niche", "dental")
    assert rows.parse_match_param("industry=healthcare") == ("industry", "healthcare")
    assert rows.parse_match_param("") is None
    assert rows.parse_match_param("garbage") is None


def test_id_list_roundtrip_dedup():
    assert rows.parse_id_list("a\nb, c\n\n") == ["a", "b", "c"]
    assert rows.join_id_list(["a", "a", "b", ""]) == "a\nb"


def test_parse_queued_message_subject_and_blank():
    assert rows.parse_queued_message("Subject: hi\n\nhey there\n\nbody") == ("hi", "hey there\n\nbody")
    assert rows.parse_queued_message("Subject: \n\njust body") == ("", "just body")
    assert rows.parse_queued_message("no header here") == ("", "no header here")


def test_next_step_for():
    assert rows.next_step_for("email_1_sent") == 2
    assert rows.next_step_for("email_2_sent") == 3
    assert rows.next_step_for("email_3_sent") is None
    assert rows.next_step_for("researched") is None


def test_history_roundtrip():
    h = rows.append_history(None, rows.history_entry(1, "subj", "body one", "2026-07-08"))
    h = rows.append_history(h, rows.history_entry(2, "", "body two", "2026-07-11"))
    parsed = rows.parse_history(h)
    assert len(parsed) == 2 and "body one" in parsed[0] and "Email 2" in parsed[1]


def test_prospect_from_row_rebuilds_niche_and_sent():
    p = rows.prospect_from_row({
        "firm_name": "X", "city": "Denver", "state": "CO",
        "classification": "niched", "match_param": "niche=dental",
        "sent_lead_ids": "s1\ns2", "first_name": "dana",
    })
    assert p.match_param == ("niche", "dental")
    assert p.sent_lead_ids == ["s1", "s2"] and p.first_name == "dana"


# --- approve_and_send -----------------------------------------------------

def _first_touch_row():
    return {
        "rec1": {
            "firm_name": "Acme", "email": "dana@acme.com", "first_name": "dana",
            "stage": "researched", "current_step": "1", "niche_pack": "cfo",
            "smartlead_campaign_id": "99", "eligible_for_send": True,
            "queued_message": "Subject: a subj\n\nhey dana,\n\nline one",
            "pending_lead_ids": "p1\np2", "sent_lead_ids": "",
        }
    }


def test_approve_first_touch_adds_lead_and_advances():
    at = FakeAirtable(_first_touch_row())
    s = FakeSender()
    res = approve_and_send(at, s, "rec1", today=TODAY)
    assert res["step"] == 1 and res["stage"] == "email_1_sent"
    f = at.records["rec1"]
    assert f["stage"] == "email_1_sent" and f["review_status"] == "approved"
    assert f["smartlead_lead_id"] == "fake-lead-1"
    assert f["sent_lead_ids"] == "p1\np2" and f["pending_lead_ids"] == ""
    assert f["due_date"] == "2026-07-11"           # +3 days for step 2
    add = s.added[0]
    assert add["email"] == "dana@acme.com" and add["subject"] == "a subj"
    assert add["email_1"].startswith("hey dana,")


def test_approve_followup_updates_variable_and_advances():
    at = FakeAirtable({
        "rec2": {
            "firm_name": "Acme", "email": "dana@acme.com", "stage": "email_1_sent",
            "current_step": "2", "niche_pack": "cfo", "smartlead_campaign_id": "99",
            "smartlead_lead_id": "L7", "eligible_for_send": True,
            "queued_message": "Subject: \n\nfound one more\n\nbody",
            "pending_lead_ids": "p3", "sent_lead_ids": "p1\np2",
        }
    })
    s = FakeSender()
    res = approve_and_send(at, s, "rec2", today=TODAY)
    assert res["step"] == 2 and res["stage"] == "email_2_sent"
    assert s.followups[0]["lead_id"] == "L7" and s.followups[0]["step"] == 2
    assert not s.added                                  # NOT a new lead
    f = at.records["rec2"]
    assert f["sent_lead_ids"] == "p1\np2\np3" and f["due_date"] == "2026-07-12"  # +4


def test_approve_refuses_frozen_row():
    at = FakeAirtable({"rec3": {"frozen": True, "current_step": "1", "email": "x@x.com"}})
    with pytest.raises(RuntimeError):
        approve_and_send(at, FakeSender(), "rec3", today=TODAY)


def test_approve_refuses_non_eligible_prospect():
    # HARD send-safety gate: no eligible_for_send -> the push is refused and
    # NOTHING is sent, even though every other field is valid.
    from system_b.sequence.rows import NotEligibleError
    row = _first_touch_row()
    row["rec1"].pop("eligible_for_send")          # not marked eligible
    at, s = FakeAirtable(row), FakeSender()
    with pytest.raises(NotEligibleError):
        approve_and_send(at, s, "rec1", today=TODAY)
    assert not s.added                            # never touched Smartlead
    assert at.records["rec1"]["stage"] == "researched"   # unchanged


# --- scheduler ------------------------------------------------------------

def _sched_records():
    return {
        "due_a": {"firm_name": "A", "stage": "email_1_sent", "review_status": "approved",
                  "due_date": "2026-07-06", "website": "http://a.com"},
        "due_b": {"firm_name": "B", "stage": "email_2_sent", "review_status": "approved",
                  "due_date": "2026-07-01", "website": "http://b.com"},
        "not_due": {"firm_name": "C", "stage": "email_1_sent", "review_status": "approved",
                    "due_date": "2026-07-20", "website": "http://c.com"},
        "frozen": {"firm_name": "D", "stage": "email_1_sent", "review_status": "approved",
                   "due_date": "2026-07-01", "frozen": True, "website": "http://d.com"},
        "new1": {"firm_name": "E", "stage": "researched", "website": "http://e.com"},
        "new2": {"firm_name": "F", "stage": "researched", "website": "http://f.com"},
        "pending_new": {"firm_name": "G", "stage": "researched", "review_status": "pending",
                        "website": "http://g.com"},
    }


def test_find_due_followups_orders_and_filters():
    recs = [{"id": r, "fields": f} for r, f in _sched_records().items()]
    due = find_due_followups(recs, TODAY)
    ids = [r["id"] for r in due]
    assert ids == ["due_b", "due_a"]         # most overdue first; not_due/frozen excluded


def test_find_new_prospects_excludes_drafted():
    recs = [{"id": r, "fields": f} for r, f in _sched_records().items()]
    new = {r["id"] for r in find_new_prospects(recs)}
    assert new == {"new1", "new2"}           # pending_new already has a draft


def test_quota_run_followups_first_then_new(monkeypatch):
    import system_b.sequence.scheduler as sched

    calls = []
    monkeypatch.setattr(sched, "generate_followup",
                        lambda at, sc, r, today: (calls.append(("f", r["id"])) or
                                                  {"firm": r["id"], "status": "ok", "step": 2}))
    monkeypatch.setattr(sched, "generate_first_touch",
                        lambda at, sc, tax, row, today, pack_key="cfo": (calls.append(("n", row["record_id"])) or
                                                                        {"firm": row["firm_name"], "status": "ok", "step": 1}))
    at = FakeAirtable(_sched_records())
    summary = quota_run(at, email_quota=3, today=TODAY,
                        scraper_override=FakeScraper([]), taxonomy_override={})
    assert summary["generated"] == 3
    # first two are the due follow-ups (ordered), third is a new first-touch
    assert calls[0][0] == "f" and calls[1][0] == "f" and calls[2][0] == "n"
    assert summary["followups"] == 2 and summary["first_touches"] == 1


def test_quota_run_respects_send_cap(monkeypatch):
    import system_b.sequence.scheduler as sched
    monkeypatch.setattr(sched, "generate_followup",
                        lambda *a, **k: {"status": "ok", "step": 2})
    monkeypatch.setattr(sched, "generate_first_touch",
                        lambda *a, **k: {"status": "ok", "step": 1})
    at = FakeAirtable(_sched_records())
    summary = quota_run(at, email_quota=100, today=TODAY, send_cap=2,
                        scraper_override=FakeScraper([]), taxonomy_override={})
    assert summary["generated"] == 2 and summary["quota"] == 2


def test_guard_pauses_unready_followups():
    at = FakeAirtable({
        "unready": {"stage": "email_1_sent", "review_status": "pending",
                    "due_date": "2026-07-06", "smartlead_lead_id": "L1",
                    "smartlead_campaign_id": "99"},
        "ready": {"stage": "email_1_sent", "review_status": "approved",
                  "due_date": "2026-07-06", "smartlead_lead_id": "L2",
                  "smartlead_campaign_id": "99"},
        "not_due": {"stage": "email_1_sent", "review_status": "pending",
                    "due_date": "2026-07-20", "smartlead_lead_id": "L3",
                    "smartlead_campaign_id": "99"},
    })
    s = FakeSender()
    paused = guard_unready_followups(at, s, TODAY)
    assert paused == ["unready"]
    assert s.paused == [("99", "L1")]
    assert at.records["unready"]["frozen"] is True


# --- follow-up generation (real copy, LLM stubbed) ------------------------

def test_generate_followup_value_and_fallback(monkeypatch):
    import system_b.sequence.generate as gen
    monkeypatch.setattr(gen, "describe_leads",
                        lambda gift, prospect, **kw: {l.id: "did a thing" for l in gift.leads})

    lead = mk("newlead", "job_fractional_cfo", city="Denver", state="CO")
    sc = FakeScraper([lead])
    at = FakeAirtable({
        "rec": {"firm_name": "Acme", "city": "Denver", "state": "CO",
                "classification": "generalist", "stage": "email_1_sent",
                "niche_pack": "cfo", "email": "d@acme.com", "sent_lead_ids": ""},
    })
    res = gen.generate_followup(at, sc, at.get("rec"), TODAY)
    assert res["status"] == "ok" and res["step"] == 2 and res["kind"] == "value"
    f = at.records["rec"]
    assert f["current_step"] == "2" and f["pending_lead_ids"] == "newlead"
    assert f["review_status"] == "pending"
    assert f["queued_message"].startswith("Subject: \n\n")     # blank subject

    # Now mark that lead already sent -> the well is dry -> fallback bump.
    at.records["rec"]["sent_lead_ids"] = "newlead"
    res2 = gen.generate_followup(at, sc, at.get("rec"), TODAY)
    assert res2["kind"] == "fallback" and at.records["rec"]["pending_lead_ids"] == ""


def test_generate_followup_skips_frozen_and_complete():
    at = FakeAirtable({"f": {"frozen": True, "stage": "email_1_sent"},
                       "done": {"stage": "email_3_sent"}})
    assert gen_status(at, "f") == "skipped_frozen"
    assert gen_status(at, "done") == "sequence_complete"


def gen_status(at, rid):
    import system_b.sequence.generate as gen
    return gen.generate_followup(at, FakeScraper([]), at.get(rid), TODAY)["status"]
