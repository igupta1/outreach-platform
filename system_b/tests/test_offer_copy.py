"""The 2026-11-05 copy pass: one offer and one ask, an A/B call to action,
varied fixed sentences, single-kind gifts, no city opener, sane revenue
claims, a size floor for CFO firms and no leads that are not companies."""

from __future__ import annotations

from datetime import date

from system_b.clients.inventory import _not_a_buyer
from system_b.copy import offer
from system_b.copy.email import _sane_revenue
from system_b.copy.facts import record_fact
from system_b.gift.engine import not_a_buyer_for, single_kind_gift
from system_b.gift.models import Prospect
from system_b.models import Lead, Signal
from system_b.tests.test_gift import FakeScraper, mk

TODAY = date(2026, 11, 5)


def _lead(t, name="Acme Llc", payload=None, **kw):
    return Lead(id=f"{t}:{name}", company=name, signal_type=t, city="Austin", state="TX",
                signals=[Signal(type=t, date="2026-10-01", date_confidence="high",
                                plain_words_description="r", source_url="https://x.gov",
                                payload=dict(payload or {}))], **kw)


def test_the_offer_is_free_weekly_leads_with_one_ask_and_no_price():
    a = offer.cta("A", offer.scope("construction companies", "florida"))
    assert a == ('want 3 like these every monday, only construction companies in florida? '
                 'free for 2 weeks. just reply "yes".')
    b = offer.cta("B", "")
    for line in (a, b):
        assert line.count("?") == 1 and "free for 2 weeks" in line and "$" not in line
        assert "set it up" not in line


def test_each_prospect_keeps_one_variant_and_the_two_split_the_batch():
    emails = [f"owner{i}@firm{i}.com" for i in range(400)]
    got = [offer.variant_for(e) for e in emails]
    assert got == [offer.variant_for(e) for e in emails]          # stable
    assert 150 < got.count("A") < 250                              # about half each
    assert offer.variant_for(None) == "A"


def test_the_fixed_sentences_vary_by_prospect_but_keep_the_engineer():
    lines = {offer.engineer_line(f"x{i}@y.com", "companies", "finance") for i in range(60)}
    assert len(lines) == 3 and all(ln.startswith("i'm an engineer") for ln in lines)
    finals = {offer.final_note(f"x{i}@y.com", "Peak Books") for i in range(60)}
    assert len(finals) == 2 and all(f.startswith("last one from me.") for f in finals)
    assert all("custom tools" not in f for f in finals)


def test_a_mixed_gift_gives_way_to_three_of_one_kind():
    db = "construction_federal_award_davis_bacon"
    sba = "sba_7a_loan_approved"
    leads = [mk("d1", db, city="Austin", state="TX"), mk("s1", sba, city="Austin", state="TX"),
             mk("d2", db, city="Dallas", state="TX"), mk("s2", sba, city="Austin", state="TX"),
             mk("d3", db, city="Houston", state="TX")]
    g = single_kind_gift(Prospect(firm_name="Books", city="Austin", state="TX"), FakeScraper(leads))
    assert g and len({ld.signal_type for ld in g.leads}) == 1 and g.gift_size == 3


def test_revenue_claims_only_when_they_mean_something():
    assert _sane_revenue((250_000, 5_000_000))
    assert _sane_revenue((100_000_000, None))
    assert not _sane_revenue((None, 250_000))                      # "sub-$250k"
    assert not _sane_revenue((100_000, 130_000_000))               # "$100k-$130m"


def test_a_cfo_firm_never_gets_a_lead_too_small_to_afford_one():
    cfo = Prospect(firm_name="Peak CFO", city="Austin", state="TX", rung="cfo")
    books = Prospect(firm_name="Peak Books", city="Austin", state="TX", rung="bookkeeping")
    small = _lead("sba_7a_loan_approved", payload={"loan_amount": 50_000})
    big = _lead("sba_7a_loan_approved", payload={"loan_amount": 500_000})
    assert not_a_buyer_for(small, cfo) and not not_a_buyer_for(big, cfo)
    assert not not_a_buyer_for(small, books)
    tiny_np = _lead("nonprofit_going_concern", payload={"total_revenue": 31_000})
    assert not_a_buyer_for(tiny_np, Prospect(firm_name="X", is_cpa=True, rung="cfo"))


def test_names_that_are_not_companies_and_finance_contacts_are_left_out():
    why = lambda ld: _not_a_buyer({"state": "TX"}, ld, TODAY)  # noqa: E731
    assert why(_lead("hud_new_owner", "1027 E Pleasant St")) == "not_a_company"
    assert why(_lead("sba_7a_loan_approved", "TowneBank")) == "not_a_company"
    assert why(_lead("college_heightened_cash_monitoring", "Florida Atlantic University")) == "not_a_company"
    assert why(_lead("nonprofit_going_concern", "Regional Food Bank")) is None
    cfo_contact = _lead("hrsa_new_health_center", contact_name="Tony Duong", contact_title="CFO")
    assert record_fact(cfo_contact) == ""
