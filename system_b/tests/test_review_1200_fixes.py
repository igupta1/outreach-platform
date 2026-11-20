"""2026-11-15: fixes from reading every email of the 1,200 batch."""

from __future__ import annotations

from datetime import date

from system_b.clients import inventory as inv
from system_b.copy.lex import spoken_name
from system_b.models import Lead, Signal
from system_b.prospects import row_from_apollo

TODAY = date(2026, 11, 16)


def _lead(t, payload, name="Acme Widgets", state="CO", city="Denver"):
    return Lead(id=f"{t}:{name}", company=name, city=city, state=state, industry=None,
                signal_type=t, entity_id=f"x:{name}",
                signals=[Signal(type=t, date="2026-10-01", date_confidence="high",
                                plain_words_description="x", source_url="https://example.gov",
                                payload=payload)])


def _why(lead):
    return inv._not_a_buyer({"name": lead.company, "state": lead.state}, lead, TODAY)


def test_expanding_into_its_own_state_is_dropped():
    assert _why(_lead("new_business_expanding", {"state": "CO"})) == "not_expanding"
    assert _why(_lead("new_business_expanding", {"state": "CO"}, state="TX")) is None


def test_a_takeover_long_after_the_last_licence_lapsed_is_no_sale():
    pay = {"issue_date": "2026-09-14", "prior_licensee": {"expired": "2025-10-31"}}
    assert _why(_lead("liquor_license_new_owner_ny", pay)) == "not_a_sale"
    pay = {"issue_date": "2026-09-14", "prior_licensee": {"expired": "2026-08-31"}}
    assert _why(_lead("liquor_license_new_owner_ny", pay)) is None


def test_a_late_report_already_filed_is_dropped():
    assert _why(_lead("late_filing_notice", {"late_report_filed_on": "2026-10-20"})) \
        == "already_filed"


def test_vehicles_competitors_and_government_are_dropped():
    assert _why(_lead("hud_new_owner", {}, name="Norwalk Towers CA Owner")) == "holding_or_hotel"
    assert _why(_lead("sba_7a_loan_approved", {}, name="Innovative Tax Solutions")) \
        == "competitor"
    assert _why(_lead("medicare_new_part_a_provider", {},
                      name="Comanche County Hospital Authority")) == "government"
    assert _why(_lead("local_gov_financial_report_late", {},
                      name="Wayne County Transit Authority")) is None


def test_names_lose_registry_leftovers():
    assert spoken_name("Najmy Thompson, PL") == "Najmy Thompson"
    assert spoken_name("Tiny Tot Learning Center FS") == "Tiny Tot Learning Center"
    assert spoken_name("MC Dermott Center") == "McDermott Center"
    assert spoken_name("MILNER Restaurants") == "Milner Restaurants"
    assert spoken_name("Grace House of Memphis Tennessee") == "Grace House of Memphis"
    assert spoken_name("Bank of Texas") == "Bank of Texas"
    assert spoken_name("Fresh Coat Location #91718") == "Fresh Coat"


def test_greeting_uses_the_mailbox_nickname_and_drops_stray_marks():
    base = {"Website": "acme.com", "Company Name": "Acme CPA", "Last Name": "Smith"}
    assert row_from_apollo({**base, "Email": "mike@acme.com", "First Name": "Michael"})[
        "first_name"] == "Mike"
    assert row_from_apollo({**base, "Email": "j@acme.com", "First Name": "Jeorgia'"})[
        "first_name"] == "Jeorgia"
    assert row_from_apollo({**base, "Email": "lead2@acme.com", "First Name": "Ann"}) is None
    assert row_from_apollo({**base, "Email": "marketing@acme.com", "First Name": "Ann"}) is None


def test_public_competitor_and_audited_plans_are_dropped():
    assert _why(_lead("auditor_change", {"tickers": ["BATL"]})) == "public_company"
    assert _why(_lead("plan_audit_first_due", {"naics": "541211"})) == "competitor"
    full = {"form": "Form 5500", "participants_boy": 119, "plan_year": 2025}
    assert _why(_lead("plan_audit_first_due", full)) == "already_audited"
    old = {"form": "Form 5500-SF", "participants_boy": 90, "plan_year": 2024}
    assert _why(_lead("plan_audit_first_due", old)) == "stale"


def test_a_credentialed_person_is_no_business():
    assert _why(_lead("sba_7a_loan_approved", {}, name="Hankla, DMD")) == "person_name"
    assert _why(_lead("sam_new_entity_registration", {}, name="Mustansir Barma")) == "person_name"
    assert _why(_lead("sba_7a_loan_approved", {}, name="Ridge Road Dental")) is None


def test_money_rounds_halves_up():
    from system_b.copy.facts import money
    assert money(3650000) == "$3.7m" and money(68500) == "$69k"


def test_spot_read_name_and_greeting_fixes():
    assert spoken_name("Transit Fixed/ON-Demand") == "Transit Fixed/On-Demand"
    assert spoken_name("MI Tierra Pupuseria & Bakery") == "Mi Tierra Pupuseria & Bakery"
    assert spoken_name("Iv Purpose") == "IV Purpose"
    assert spoken_name("Raptor Manufacturing LC") == "Raptor Manufacturing"
    base = {"Website": "a.com", "Company Name": "A", "Last Name": "Daly"}
    assert row_from_apollo({**base, "Email": "jimdaly@a.com", "First Name": "James"})[
        "first_name"] == "Jim"
    assert row_from_apollo({**base, "Email": "seb@a.com", "First Name": "Sebastian"})[
        "first_name"] == "Seb"


def test_owners_are_drafted_before_partners_at_bigger_firms():
    """2026-11-19, the user: prefer firm owners over partners at bigger CPA firms."""
    from system_b.run import owner_rank
    assert owner_rank("Founder & CEO") == 0
    assert owner_rank("Managing Partner") == 0
    assert owner_rank("Owner") == 0
    assert owner_rank("Controller") == 1
    assert owner_rank(None) == 1
    assert owner_rank("Tax Partner") == 2
    assert owner_rank("Partner") == 2
