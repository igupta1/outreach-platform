"""One fact per lead from its own record (copy.facts, 2026-11-05)."""

from __future__ import annotations

from system_b.copy.facts import agency, money, record_fact
from system_b.models import Lead, Signal


def _lead(t, payload, **kw):
    return Lead(id="x", company="Acme", signal_type=t, city="Austin", state="TX",
                signals=[Signal(type=t, date="2026-10-01", date_confidence="high",
                                plain_words_description="r", source_url="https://x.gov",
                                payload=payload)], **kw)


def test_money_is_short_and_only_from_a_real_number():
    assert money(988_000) == "$988k" and money(1_240_000) == "$1.2m" and money(10_400_000) == "$10.4m"
    assert money(2_000_000) == "$2m" and money(900) == "$900"
    assert money(None) == money("n/a") == money(0) == money(True) == ""


def test_agency_names_the_department_plainly():
    assert agency({"awarding_agency": "Department of Veterans Affairs"}) == "va"
    assert agency({"awarding_agency": "Department of Transportation"}) == "dot"
    assert agency({"awarding_agency": "Securities and Exchange Commission"}) == "sec"
    assert agency({"awarding_agency": "SOUND TRANSIT"}) == ""        # unknown: the $ alone
    assert agency({"awarding_agency": "Department of Defense",
                   "awarding_sub_agency": "Department of the Army"}) == "army"


def test_the_fact_follows_the_record_in_order():
    assert record_fact(_lead("construction_federal_award_davis_bacon",
                             {"award_amount": 988000.0,
                              "awarding_agency": "Department of Veterans Affairs"})) \
        == "$988k"                          # 2026-11-12: no agency
    assert record_fact(_lead("sba_7a_loan_approved", {"loan_amount": 3740000.0})) == "$3.7m loan"
    assert record_fact(_lead("plan_late_contributions", {"amount": 56108.0,
                                                         "participants_eoy": 208})) \
        == "$56k in late contributions"
    assert record_fact(_lead("nonprofit_going_concern", {"total_revenue": 18448862.0})) \
        == "$18.4m in revenue"
    assert record_fact(_lead("plan_audit_first_due", {"participants_eoy": 121})) == "121 in the plan"
    assert record_fact(_lead("hud_new_owner", {"units_total": 472})) == "472 units"


def test_a_contact_is_printed_only_with_a_plain_role():
    named = _lead("tx_late_sales_tax_registration", {}, contact_name="VICKIE SMITH",
                  contact_title="Executive Director")
    assert record_fact(named) == "Vickie Smith, executive director"
    # 2026-11-11: the source's wording becomes a plain role; an unknown one prints nothing.
    signer = _lead("tx_late_sales_tax_registration", {}, contact_name="Pat Lee",
                   contact_title="Signed the Form 5500 as plan administrator")
    assert record_fact(signer) == "Pat Lee, plan administrator"
    for odd in ("Registered agent", "Attorney (firm named for them)", "Treasurer"):
        assert record_fact(_lead("tx_late_sales_tax_registration", {}, contact_name="Pat Lee",
                                 contact_title=odd)) == ""
    assert record_fact(_lead("tx_late_sales_tax_registration", {})) == ""
