"""Track F — unified cadence, lifted LinkedIn copy, LinkedIn generation in the
quota run, and the LinkedIn card lifecycle."""

from __future__ import annotations

from datetime import date

import pytest

from system_b.cadence import DEFAULT_CADENCE, day_for, next_dm_step
from system_b.copy.linkedin import build_dm, cfo_dm_1, cfo_dm_2, connection_request
from system_b.gift.models import Prospect
from system_b.niches.cfo import CFO_PACK
from system_b.sending import FakeSender
from system_b.sequence import linkedin as li
from system_b.sequence.scheduler import find_due_linkedin, quota_run
from system_b.sequence.send import approve_and_send
from system_b.tests.test_gift import FakeScraper
from system_b.tests.test_sequence import FakeAirtable

TODAY = date(2026, 7, 8)


# --- F1 cadence -----------------------------------------------------------

def test_cadence_days_and_progression():
    # day_for is used for the unique LinkedIn kinds; email_1/connect at day 0.
    assert day_for("email_1") == 0 and day_for("connect") == 0
    assert day_for("dm_1") == 5 and day_for("dm_2") == 10
    assert next_dm_step("") == "dm_1" and next_dm_step("connect") == "dm_1"
    assert next_dm_step("dm_1") == "dm_2" and next_dm_step("dm_2") is None
    # the pack carries the cadence, tunable per pack
    assert CFO_PACK.cadence == DEFAULT_CADENCE


# --- F2 lifted copy (honesty gate) ----------------------------------------

def _p():
    return Prospect(firm_name="Acme", first_name="Dana", classification="niched",
                    match_param=("niche", "dental"))


def test_connection_request_is_blank():
    assert connection_request() == ""


def test_dm1_niche_gate_and_cfo_addon():
    ctx = {"n": 3, "all_niche": True, "niche": "dental", "best_cfo_company": "Aspero"}
    t = cfo_dm_1(_p(), ctx)
    assert "sent you 3 dental companies over email" in t
    assert "did it land in spam? happy to resend here." in t
    assert "Aspero is even hiring a fractional cfo." in t
    assert "hey dana," in t


def test_dm1_drops_niche_when_not_all_niche():
    ctx = {"n": 2, "all_niche": False, "niche": "dental", "best_cfo_company": None}
    t = cfo_dm_1(_p(), ctx)
    assert "sent you 2 companies over email" in t     # no niche word
    assert "dental" not in t
    assert "even hiring" not in t                       # no cfo addon


def test_dm2_close():
    t = cfo_dm_2(_p())
    assert "no stress if this isn't a priority" in t and "good luck with the pipeline" in t


def test_build_dm_dispatch():
    ctx = {"n": 1, "all_niche": False, "niche": None, "best_cfo_company": None}
    assert build_dm("dm_1", _p(), ctx, pack=CFO_PACK).startswith("hey dana,")
    assert "no stress" in build_dm("dm_2", _p(), ctx, pack=CFO_PACK)


# --- email #1 send seeds the LinkedIn track -------------------------------

def test_email1_send_sets_anchor_and_connect_pending():
    at = FakeAirtable({"r": {
        "firm_name": "Acme", "email": "d@acme.com", "stage": "researched",
        "current_step": "1", "smartlead_campaign_id": "99", "eligible_for_send": True,
        "queued_message": "Subject: s\n\nhey d,\n\nbody", "pending_lead_ids": "p1",
    }})
    approve_and_send(at, FakeSender(), "r", today=TODAY)
    f = at.records["r"]
    assert f["sequence_started_at"] == "2026-07-08" and f["li_connect_pending"] is True


# --- F2 scheduling: due LinkedIn DMs --------------------------------------

def _li_row(**over):
    row = {"firm_name": "Acme", "sequence_started_at": "2026-07-01",
           "connection_accepted": True, "li_progress": "connect",
           "all_niche": True, "match_param": "niche=dental", "sent_lead_ids": "a\nb\nc"}
    row.update(over)
    return row


def test_find_due_linkedin_gating():
    recs = {
        "due": _li_row(),                                          # dm_1 due (day5, started 07-01)
        "not_connected": _li_row(connection_accepted=False),       # gate fails
        "frozen": _li_row(frozen=True),                            # reply freeze
        "not_started": _li_row(sequence_started_at=""),            # email#1 not sent
        "pending": _li_row(li_review_status="pending"),            # LI card already in flight
        "done": _li_row(li_progress="dm_2"),                       # sequence complete
        "not_due": _li_row(sequence_started_at="2026-07-06"),      # dm_1 would be 07-11 > today
    }
    at = FakeAirtable(recs)
    due = find_due_linkedin([{"id": k, "fields": v} for k, v in recs.items()], TODAY)
    assert [r["id"] for r, _ in due] == ["due"]
    assert due[0][1] == "dm_1"


def test_quota_run_generates_linkedin_dms():
    at = FakeAirtable({"due": _li_row(li_best_cfo="Aspero")})
    summary = quota_run(at, email_quota=0, linkedin_quota=5, today=TODAY,
                        scraper_override=FakeScraper([]), taxonomy_override={})
    assert summary["linkedin_generated"] == 1
    f = at.records["due"]
    assert f["li_review_status"] == "pending" and f["li_step"] == "dm_1"
    assert "3 dental companies" in f["li_message"] and "Aspero is even hiring" in f["li_message"]


# --- LinkedIn card lifecycle (never touches the email stage) --------------

def test_linkedin_approve_refuses_non_eligible():
    from system_b.sequence.rows import NotEligibleError
    at = FakeAirtable({"r": {"firm_name": "Acme", "li_step": "dm_1",
                             "li_review_status": "pending"}})   # not eligible
    with pytest.raises(NotEligibleError):
        li.approve_linkedin(at, "r")
    assert at.records["r"]["li_review_status"] == "pending"     # unchanged


def test_linkedin_actions():
    at = FakeAirtable({"r": {"firm_name": "Acme", "stage": "email_1_sent",
                             "li_step": "dm_1", "li_review_status": "pending", "eligible_for_send": True,
                             "li_card_json": '{"message":{"body":"hi"}}', "li_message": "hi"}})
    # approve -> queue, email stage untouched
    assert li.approve_linkedin(at, "r")["approved"] is True
    assert at.records["r"]["li_review_status"] == "approved"
    assert at.records["r"]["stage"] == "email_1_sent"

    # edit -> lint + store
    r = li.edit_linkedin(at, "r", "resend? we raised $5,000,000")
    assert "$" not in at.records["r"]["li_message"] and any("dollar" in w for w in r["warnings"])

    # mark DM sent -> progress advances, card cleared (singleSelect cleared to None)
    li.mark_dm_sent(at, "r")
    assert at.records["r"]["li_progress"] == "dm_1" and at.records["r"]["li_review_status"] is None

    # reject a fresh DM -> skip only, progress advances, email untouched
    at.records["r2"] = {"li_step": "dm_2", "li_review_status": "pending", "stage": "email_2_sent"}
    li.reject_linkedin(at, "r2")
    assert at.records["r2"]["li_progress"] == "dm_2" and at.records["r2"]["stage"] == "email_2_sent"


def test_mark_connect_sent():
    at = FakeAirtable({"r": {"li_connect_pending": True}})
    li.mark_connect_sent(at, "r")
    assert at.records["r"]["li_connect_pending"] is False and at.records["r"]["li_progress"] == "connect"
