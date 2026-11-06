"""The 2026-11-05 lead-quality pass: sensitive industries, chains and holding
companies, needs already met, trade names, full registry names, better facts,
email 2 in the firm's own state, and the exact niche before its parent."""

from __future__ import annotations

from datetime import date

from system_b.clients.inventory import _clean_company_name, _full_name, _not_a_buyer, \
    _trade_name, adapt_leadgen_lead
from system_b.copy.email import _unrepeated
from system_b.copy.facts import record_fact
from system_b.gift.engine import build_gift, not_a_buyer_for, sensitive
from system_b.gift.models import Prospect
from system_b.gift.tiering import fit_label
from system_b.models import Lead, Signal
from system_b.tests.test_gift import FakeScraper, mk

TODAY = date(2026, 11, 5)


def _lead(t="sba_7a_loan_approved", name="Acme Llc", payload=None, **kw):
    return Lead(id=f"{t}:{name}", company=name, signal_type=t, city="Austin", state="TX",
                signals=[Signal(type=t, date="2026-10-01", date_confidence="high",
                                plain_words_description="r", source_url="https://x.gov",
                                payload=dict(payload or {}))], **kw)


def _row(t, name, payload=None, **kw):
    return {"name": name, "signal_type": t, "state": "TX", "city": "Austin",
            "signals": [{"type": t, "event_date": "2026-10-01", "payload": dict(payload or {})}], **kw}


def test_sensitive_industries_only_reach_firms_in_that_niche():
    shop = _lead("cannabis_new_license", "Back Porch Cannabis", industry="cannabis")
    church = _lead("church_990t_first", "Grace Church")
    grant = _lead("nsgp_security_grant_subaward", "Temple Beth")
    assert sensitive(shop) and sensitive(church) and sensitive(grant)
    plain = Prospect(firm_name="Books", city="Austin", state="TX")
    assert not_a_buyer_for(shop, plain) and not_a_buyer_for(church, plain)
    cannabis_cpa = Prospect(firm_name="Green CPA", city="Austin", state="TX",
                            classification="niched", match_param=("industry", "cannabis"))
    assert not not_a_buyer_for(shop, cannabis_cpa)


def test_chains_holding_companies_hotels_and_met_needs_are_dropped():
    why = lambda ld, row=None: _not_a_buyer(row or {"state": "TX"}, ld, TODAY)  # noqa: E731
    assert why(_lead(name="Pegasus Holdings Group")) == "holding_or_hotel"
    assert why(_lead(name="TFM Acquisition LLC")) == "holding_or_hotel"
    assert why(_lead(name="Hampton Inn & Suites Austin")) in ("chain", "holding_or_hotel")
    assert why(_lead("liquor_license_new_tx", "Walmart Inc #123")) == "chain"
    assert why(_lead("liquor_license_new_tx", "Valdivia Tacos")) is None
    assert why(_lead(name="Hilton Head Plumbing")) is None
    assert why(_lead(payload={"naics": "721110"})) == "holding_or_hotel"
    assert why(_lead("plan_audit_first_filed", "Acme")) == "need_met"
    assert why(_lead("new_business_expanding", "Big Co",
                     {"registered_agent_org": "C T CORPORATION SYSTEM"})) == "big_registered_agent"


def test_an_accounting_firm_borrower_is_never_a_lead_for_an_accounting_firm():
    borrower = _lead(name="Reyes Group", payload={"naics": "541211"})
    assert not_a_buyer_for(borrower, Prospect(firm_name="Books", city="Austin", state="TX"))


def test_licence_records_print_the_trade_name_and_restaurants_are_tagged():
    row = _row("liquor_license_new_tx", "OHANA FAMILY VENTURES INC",
               {"trade_name": "BIG AIR PLANO", "license_label": "On-Sale General Eating Place"})
    assert _trade_name(row) == "Big Air Plano"
    ld = adapt_leadgen_lead(row, today=TODAY)
    assert ld.company == "Big Air Plano" and ld.industry == "hospitality_food"
    assert _trade_name(_row("sba_7a_loan_approved", "Acme", {"trade_name": "X"})) is None


def test_a_cut_off_irs_name_takes_the_registry_name_that_extends_it():
    row = _row("nonprofit_first_990", "Arts And Letters 305 United Parent",
               {"state_name": "ARTS AND LETTERS 305 UNITED PARENT TEACHER ASSOCIATION"})
    assert _full_name(row) == "ARTS AND LETTERS 305 UNITED PARENT TEACHER ASSOCIATION"
    assert _full_name(_row("nonprofit_first_990", "Hope House", {"state_name": "Other Org"})) is None
    assert _clean_company_name("United Operations (DBA Newity LLC)") == "Newity LLC"


def test_facts_name_the_business_and_never_repeat_the_line():
    assert record_fact(_lead(payload={"loan_amount": 3740000.0,
                                      "naics_description": "Software Publishers"})) \
        == "$3.7m loan, software publishers"
    assert record_fact(_lead("liquor_license_new_ca", payload={
        "license_label": "On-Sale General Eating Place"})) == "restaurant license"
    assert record_fact(_lead("nsgp_security_grant_subaward", payload={"subaward_amount": 102690.0})) \
        == "$103k grant"
    assert record_fact(_lead("tx_new_sales_tax_permit", payload={
        "naics_label": "electronic shopping and mail-order"})) == "electronic shopping and mail-order"
    assert record_fact(_lead("tx_new_sales_tax_permit", contact_name="Pat Lee", contact_title="MGR")) \
        == "Pat Lee, manager"
    assert _unrepeated("$2.2m loan", "approved for an sba loan") == "$2.2m"
    assert _unrepeated("$2.2m loan, software publishers", "was approved for an sba loan") \
        == "$2.2m, software publishers"
    assert _unrepeated("$988k, army", "won a federal job") == "$988k, army"


def test_a_broad_industry_is_judged_against_the_firms_own_words():
    assert fit_label(("niche", "dental"), "dental", "dental practices") == "dental"
    label = fit_label(("industry", "healthcare"), "healthcare", "Biotech Startups")
    assert "Biotech Startups" in label and label.startswith("healthcare")
    assert fit_label(("industry", "healthcare"), "healthcare", "healthcare") == "healthcare"


def test_email_two_stays_in_the_firms_state_when_it_can():
    here = mk("h1", "construction_federal_award_davis_bacon", city="Austin", state="TX")
    there = mk("t1", "construction_federal_award_davis_bacon", city="Reno", state="NV")
    sc = FakeScraper([there, here])
    p = Prospect(firm_name="Books", city="Austin", state="TX")
    g = build_gift(p, sc, target=1, signal_types=frozenset({"construction_federal_award_davis_bacon"}),
                   in_state=True)
    assert g and g.leads[0].state == "TX"
    only_there = build_gift(p, FakeScraper([there]), target=1, in_state=True,
                            signal_types=frozenset({"construction_federal_award_davis_bacon"}))
    assert only_there is None
