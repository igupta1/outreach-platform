"""Leads no small finance firm could win, records too old to say anything
current, addresses outside the US, and HUD owners placed where the property
is (2026-11-05, the user). Offline."""

from __future__ import annotations

from datetime import date

from system_b.clients.inventory import _not_a_buyer, _property_location
from system_b.gift.engine import not_a_buyer_for
from system_b.gift.models import Prospect
from system_b.models import Lead, Signal

TODAY = date(2026, 11, 5)


def _lead(t="construction_federal_award_davis_bacon", name="Acme Llc", payload=None,
          d="2026-10-01", **kw):
    return Lead(id=f"{t}:{name}", company=name, signal_type=t, city="Austin", state="TX",
                signals=[Signal(type=t, date=d, date_confidence="high",
                                plain_words_description="r", source_url="https://x.gov",
                                payload=dict(payload or {}))], **kw)


def _why(lead, state="TX"):
    return _not_a_buyer({"state": state}, lead, TODAY)


def test_big_companies_shells_gses_and_big_plans_are_not_buyers():
    assert _why(_lead("late_filing_notice", payload={"filer_category": "Large Accelerated Filer"})) \
        == "large_public_company"
    assert _why(_lead("late_filing_notice", payload={"filer_category": "Accelerated Filer"})) \
        == "large_public_company"
    assert _why(_lead("late_filing_notice", payload={"filer_category": "Non-accelerated Filer"})) is None
    assert _why(_lead("late_filing_notice", payload={"sic": "6770"})) == "blank_check_shell"
    assert _why(_lead("hud_new_owner", name="Fannie Mae")) == "gse"
    assert _why(_lead("plan_late_contributions", payload={"participants_eoy": 4543})) == "large_plan"
    assert _why(_lead("plan_audit_first_due", payload={"participants_eoy": 164})) is None


def test_old_events_go_and_annual_filings_get_two_years():
    assert _why(_lead("new_practice_medicare_enrollment", d="2025-09-01")) == "too_old"
    assert _why(_lead("new_practice_medicare_enrollment", d="2026-01-01")) is None
    assert _why(_lead("nonprofit_grant_no_finance_officer", d="2025-03-01")) is None
    assert _why(_lead("nonprofit_grant_no_finance_officer", d="2024-06-01")) == "too_old"
    assert _why(_lead("nonprofit_first_990", d="2025-06-01")) == "too_old"    # an event


def test_outside_the_us_is_dropped():
    assert _why(_lead(), state="BAJA CALIFORNIA") == "outside_us"
    assert _why(_lead(), state="-") == "outside_us"
    assert _why(_lead(), state="NEW YORK") is None
    assert _why(_lead(), state="D.C.") is None


def test_a_hud_owner_is_placed_where_its_property_is():
    one = _lead("hud_new_owner", payload={"properties": [{"city": "Detroit", "state": "MI"}]})
    _property_location({}, one)
    assert (one.city, one.state) == ("Detroit", "MI")
    two = _lead("hud_new_owner", payload={"properties": [{"city": "Greenville", "state": "SC"},
                                                         {"city": "Providence", "state": "RI"}]})
    _property_location({}, two)
    assert (two.city, two.state) == (None, None)


def test_government_and_accounting_firms_only_for_firms_that_serve_them():
    gov = _lead(name="County of St. Louis Division of Fiscal Management", org_type="government")
    cpa = _lead("ny_new_cpa_firm", name="Kramer & Associates CPAs")
    plain = Prospect(firm_name="Ledger", city="Austin", state="TX")
    assert not_a_buyer_for(gov, plain) and not_a_buyer_for(cpa, plain)
    serves_cpas = Prospect(firm_name="X", match_param=("niche", "accounting_bookkeeping"))
    assert not not_a_buyer_for(cpa, serves_cpas)
    assert not not_a_buyer_for(_lead(), plain)
