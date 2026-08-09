"""B3/B4/B4a — follow-up email copy: blank subject, no signoff, honesty."""

from __future__ import annotations

import pytest

from system_b.copy.email import build_followup_email
from system_b.copy.honesty import strip_em_dashes
from system_b.gift.models import Prospect
from system_b.tests.test_copy import TODAY
from system_b.tests.test_gift import mk

DASHES = "‒–—―"


def _prospect(**kw):
    base = dict(firm_name="Acme CFOs", city="Denver", state="CO",
                classification="generalist", first_name="dana")
    base.update(kw)
    return Prospect(**base)


def test_strip_em_dashes_rules():
    s = strip_em_dashes
    # a real separator comma the dash didn't introduce is preserved verbatim
    assert s("Lawson Co Inc., san francisco: x") == "Lawson Co Inc., san francisco: x"
    # word -> comma; after existing punctuation -> just a space (no stacking)
    assert s("surface — want me to?") == "surface, want me to?"
    assert s("inc. — form d filed") == "inc. form d filed"
    # en dash handled; hyphen-minus (dates) and paragraph breaks untouched
    assert s("a–b") == "a, b"
    assert s("filed 2026-07-17 ok") == "filed 2026-07-17 ok"
    assert s("line one —\n\nline two") == "line one,\n\nline two"
    assert not any(c in s("x — y – z ― w") for c in DASHES)
    assert s(s("surface — want me to?")) == s("surface — want me to?")   # idempotent


def test_followups_never_contain_em_dashes():
    lead = mk("l1", "funding_form_d", city="Denver", state="CO")
    lead.value_prop = "acme inc. — form d filed 2026-07-17 — offering"   # dashes from lead data
    for step in (2, 3):
        with_lead = build_followup_email(lead, _prospect(), step=step, today=TODAY)
        dry = build_followup_email(None, _prospect(), step=step, today=TODAY)
        assert not any(c in with_lead.body for c in DASHES)
        assert not any(c in dry.body for c in DASHES)


def test_followup_subject_is_blank_and_no_signoff():
    lead = mk("l1", "job_fractional_cfo", city="Denver", state="CO")
    d = build_followup_email(lead, _prospect(),
                             step=2, today=TODAY)
    assert d.subject == ""                       # threads under Email #1 (B4)
    assert "best," not in d.body.lower()         # signoff owned by mailbox (B4a)
    assert "found one more" in d.body


def test_step3_is_final_and_distinct():
    lead = mk("l1", "job_fractional_cfo", city="Denver", state="CO")
    d = build_followup_email(lead, _prospect(), step=3, today=TODAY)
    assert "last one from me" in d.body


def test_step_must_be_2_or_3():
    with pytest.raises(ValueError):
        build_followup_email(None, _prospect(), step=1, today=TODAY)


def test_followup_lead_carries_no_date_even_high_confidence():
    # Option A: follow-ups (#2/#3) send days later on Smartlead's timers, so a
    # baked-in relative date would drift — the copy never dates a follow-up lead.
    lead = mk("l1", "job_finance_lead", city="Denver", state="CO",
              date="2026-07-01", date_confidence="high")
    d = build_followup_email(lead, _prospect(), step=2, today=TODAY)
    assert "ago" not in d.body and "week" not in d.body


def test_low_confidence_lead_gets_no_date():
    lead = mk("l1", "job_fractional_cfo", city="Denver", state="CO",
              date="2026-07-01", date_confidence="low")
    d = build_followup_email(lead, _prospect(), step=2, today=TODAY)
    assert "ago" not in d.body and "week" not in d.body


def test_followup_lead_line_is_templated_no_dollar():
    lead = mk("l1", "job_finance_lead", city="Denver", state="CO", evidence="Controller")
    d = build_followup_email(lead, _prospect(), step=2, today=TODAY)
    assert "is looking for a controller" in d.body
    assert "$" not in d.body and "5,000,000" not in d.body


def test_fallback_has_no_lead_line():
    d = build_followup_email(None, _prospect(city="Denver"), step=2, today=TODAY)
    assert "circling back" in d.body
    assert d.subject == ""


def test_qualifier_is_honest_when_lead_city_differs():
    # Prospect in Denver, lead in Austin -> no "in denver" claim in the copy.
    lead = mk("l1", "job_fractional_cfo", city="Austin", state="TX")
    d = build_followup_email(lead, _prospect(city="Denver", state="CO"),
                             step=2, today=TODAY)
    assert "in denver" not in d.body.lower()


# --- honesty lint over human edits (H edit action) ------------------------

def test_lint_free_text_strips_dollar_and_warns_on_date():
    from system_b.copy.honesty import lint_free_text

    clean, warnings = lint_free_text("they raised $5,000,000 yesterday")
    assert "$" not in clean and "5,000,000" not in clean
    assert any("dollar" in w for w in warnings)
    assert any("date" in w for w in warnings)


def test_lint_free_text_clean_input_no_warnings():
    from system_b.copy.honesty import lint_free_text

    clean, warnings = lint_free_text("hey, thought this might be useful for you")
    assert warnings == [] and clean == "hey, thought this might be useful for you"


def test_followups_prefer_same_niche_lead():
    """A niched sequence stays on-theme: Email #2/#3 pull from the SAME niche as
    Email #1, never the off-niche geo lead — even when that geo lead is fresher."""
    from datetime import date

    from system_b.gift.engine import build_gift
    from system_b.niches.base import default_pack
    from system_b.sequence.generate import _followup_drafts
    from system_b.tests.test_gift import FakeScraper

    pack = default_pack()
    prospect = Prospect(firm_name="Acme CFOs", city="Denver", state="CO",
                        classification="niched", match_param=("industry", "construction"),
                        first_name="dana")
    leads = [
        mk("c1", "job_finance_lead", industry="construction", city="Denver", state="CO", date="2026-07-06", finance_grade="medium"),
        mk("c2", "job_finance_lead", industry="construction", city="Denver", state="CO", date="2026-07-05", finance_grade="medium"),
        mk("c3", "job_finance_lead", industry="construction", city="Denver", state="CO", date="2026-07-04", finance_grade="medium"),
        mk("c4", "job_finance_lead", industry="construction", city="Denver", state="CO", date="2026-07-03", finance_grade="medium"),
        mk("c5", "job_finance_lead", industry="construction", city="Denver", state="CO", date="2026-07-02", finance_grade="medium"),
        # off-niche but FRESHEST + same city -> the geo path would pick this first
        mk("x1", "funding_form_d", industry="manufacturing", city="Denver", state="CO", date="2026-07-07"),
    ]
    sc = FakeScraper(leads)
    gift = build_gift(prospect, sc, niche_only=True, pack=pack)      # Email #1: construction
    assert gift is not None and gift.all_niche
    _drafts, extra, leads = _followup_drafts(prospect, gift, sc, pack, date(2026, 7, 8))
    assert extra                                                     # follow-ups pulled leads
    assert "x1" not in extra                                         # never the off-niche lead
    assert all(eid.startswith("c") for eid in extra)                # all same-niche
    assert [ld.id for ld in leads if ld] == extra                   # leads align with the pulled ids


# --- follow-ups: a different KIND of value, and the same ask as email 1 ------

def test_step2_carries_the_segment_note_and_step3_does_not():
    """Step 2 gets market context — a different value type from 'one more lead',
    which is what stops a follow-up reading as a bump. Step 3 is the breakup and
    stays short."""
    lead = mk("l1", "job_finance_lead", city="Denver", state="CO", company="Acme")
    note = "14 came through in colorado this month, 9 at companies under 50 people."
    d2 = build_followup_email(lead, _prospect(), step=2, today=TODAY, segment_note=note)
    d3 = build_followup_email(lead, _prospect(), step=3, today=TODAY, segment_note=note)
    assert note in d2.body
    assert note not in d3.body


def test_thin_segment_degrades_to_the_plain_shape():
    lead = mk("l1", "job_finance_lead", city="Denver", state="CO", company="Acme")
    d = build_followup_email(lead, _prospect(), step=2, today=TODAY, segment_note="")
    assert "Acme" in d.body
    assert "came through" not in d.body


def test_followups_ask_for_the_same_thing_email_1_does():
    """A sequence whose steps chase different outcomes converts on the easiest
    one. The old tails recruited a subscriber ('want me to keep sending these?');
    every step now points at the 15 minutes."""
    lead = mk("l1", "job_finance_lead", city="Denver", state="CO", company="Acme")
    d2 = build_followup_email(lead, _prospect(), step=2, today=TODAY)
    d3 = build_followup_email(lead, _prospect(), step=3, today=TODAY)
    assert "15 min" in d2.body and "15 min" in d3.body
    for banned in ("keep sending these as they surface", "i'll keep them coming"):
        assert banned not in d2.body and banned not in d3.body
    # step 3 still gives an easy out
    assert "no worries" in d3.body and "i'll stop here" in d3.body


def test_fallback_followup_still_asks_for_the_call():
    d = build_followup_email(None, _prospect(), step=2, today=TODAY)
    assert "15 min" in d.body
    assert "want me to send them your way" not in d.body
