"""B3/B4/B4a — follow-up email copy: blank subject, no signoff, honesty."""

from __future__ import annotations

import pytest

from system_b.copy.email import build_followup_email
from system_b.gift.models import Prospect
from system_b.tests.test_copy import TODAY
from system_b.tests.test_gift import mk


def _prospect(**kw):
    base = dict(firm_name="Acme CFOs", city="Denver", state="CO",
                classification="generalist", first_name="dana")
    base.update(kw)
    return Prospect(**base)


def test_followup_subject_is_blank_and_no_signoff():
    lead = mk("l1", "job_fractional_cfo", city="Denver", state="CO")
    d = build_followup_email(lead, _prospect(), "posted a fractional cfo role",
                             step=2, today=TODAY)
    assert d.subject == ""                       # threads under Email #1 (B4)
    assert "best," not in d.body.lower()         # signoff owned by mailbox (B4a)
    assert "found one more" in d.body


def test_step3_is_final_and_distinct():
    lead = mk("l1", "job_fractional_cfo", city="Denver", state="CO")
    d = build_followup_email(lead, _prospect(), "posted a role", step=3, today=TODAY)
    assert "last one from me" in d.body


def test_step_must_be_2_or_3():
    with pytest.raises(ValueError):
        build_followup_email(None, _prospect(), "", step=1, today=TODAY)


def test_high_confidence_lead_carries_a_date():
    lead = mk("l1", "job_finance_lead", city="Denver", state="CO",
              date="2026-07-01", date_confidence="high")
    d = build_followup_email(lead, _prospect(), "hired a controller", step=2, today=TODAY)
    assert "week ago" in d.body


def test_low_confidence_lead_gets_no_date():
    lead = mk("l1", "job_fractional_cfo", city="Denver", state="CO",
              date="2026-07-01", date_confidence="low")
    d = build_followup_email(lead, _prospect(), "advertising for a cfo", step=2, today=TODAY)
    assert "ago" not in d.body and "week" not in d.body


def test_funding_lead_is_templated_no_dollar():
    lead = mk("l1", "funding_form_d", city="Denver", state="CO")
    d = build_followup_email(lead, _prospect(), "raised $5,000,000 seed", step=2, today=TODAY)
    assert "just filed to raise" in d.body or "crowdfunding" in d.body
    assert "$" not in d.body and "5,000,000" not in d.body


def test_fallback_has_no_lead_line():
    d = build_followup_email(None, _prospect(city="Denver"), "", step=2, today=TODAY)
    assert "circling back" in d.body
    assert d.subject == ""


def test_qualifier_is_honest_when_lead_city_differs():
    # Prospect in Denver, lead in Austin -> no "in denver" claim in the copy.
    lead = mk("l1", "job_fractional_cfo", city="Austin", state="TX")
    d = build_followup_email(lead, _prospect(city="Denver", state="CO"),
                             "posted a role", step=2, today=TODAY)
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
