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


def test_the_offer_is_weekly_leads_with_one_ask_and_no_sales_words():
    a = offer.cta("A", offer.scope("construction companies", "florida"))
    assert a == "happy to send 3 like these every monday, matched to the clients you want, with who to contact. want next week's?"
    b = offer.cta("B", "")
    for line in (a, b):
        assert line.count("?") == 1 and "every monday" in line and "$" not in line
        assert "free" not in line and "trial" not in line and "then you decide" not in line
        assert "set it up" not in line


def test_each_prospect_keeps_one_variant_and_only_a_runs_for_now():
    emails = [f"owner{i}@firm{i}.com" for i in range(400)]
    got = [offer.variant_for(e) for e in emails]
    assert got == [offer.variant_for(e) for e in emails]          # stable
    assert got.count("A") == 400                                   # one version for now (2026-11-06)
    assert offer.variant_for(None) == "A"


def test_the_fixed_sentences_vary_by_prospect_but_keep_the_engineer():
    lines = {offer.engineer_line(f"x{i}@y.com", "companies", "finance") for i in range(60)}
    assert len(lines) == 3 and all(ln.startswith("i'm an engineer") for ln in lines)
    finals = {offer.final_note(f"x{i}@y.com") for i in range(60)}
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


# --- 2026-11-06: the second copy pass ---------------------------------------

def test_one_call_to_action():
    assert offer.ACTIVE == ("A",)
    assert {offer.variant_for(f"a{i}@b.com") for i in range(50)} == {"A"}
    for key in ("a@b.com", "c@d.com", None):    # a builder asking, not a pitch
        assert "trying to see" in offer.engineer_line(key, "companies", "finance") or \
            "seeing if" in offer.engineer_line(key, "companies", "finance")


def test_email_3_names_no_firm_and_is_not_a_jab():
    finals = {offer.final_note(f"x{i}@y.com") for i in range(60)}
    assert all("matter" not in f and " at " not in f for f in finals)


def test_email_2_asks_about_their_state_only_when_email_1_was_from_it():
    assert "keep these to ohio" in offer.followup_question(None, "ohio", cfo=False)
    assert all("keep these" not in offer.followup_question(f"k{i}", None, cfo=True)
               for i in range(20))


def test_a_no_niche_email_opens_on_what_they_do():
    from system_b.copy.email import record_opener
    from system_b.gift.models import Gift
    from system_b.niches.base import pack_for

    leads = [mk(f"d{i}", "construction_federal_award_davis_bacon", city=c, state="CO")
             for i, c in enumerate(("Boulder", "Pueblo", "Aurora"))]
    g = Gift(leads=leads, best_lead=leads[0], gift_size=3, all_niche=False, geo_level="state",
             subject_shape="plural", what_category="davis_bacon", best_lead_level=2)
    p = Prospect(firm_name="Peak Books", city="Denver", state="CO")
    assert record_opener(g, p, pack_for("bookkeeping"))[0].startswith(
        "saw you do bookkeeping in denver. these 3")
    assert record_opener(g, p, pack_for("finance"))[0].startswith(
        "saw you help companies with their finances in denver.")
    away = Gift(leads=leads, best_lead=leads[0], gift_size=3, all_niche=False, geo_level="none",
                subject_shape="plural", what_category="davis_bacon", best_lead_level=4)
    assert record_opener(away, Prospect(firm_name="X", city="Lincoln", state="NE"),
                         pack_for("cfo"))[0].startswith("saw you do fractional cfo work. ")


def test_names_a_reader_would_trip_on_never_reach_a_gift():
    from system_b.clients.inventory import _unusable_reason

    def lead(name, t="federal_cost_reimbursement_contract"):
        return Lead(id=name, company=name, signal_type=t, city="Austin", state="TX",
                    signals=[Signal(type=t, date="2026-10-01", payload={})])
    assert _unusable_reason({}, lead("The Alabama Coalition Against", "nonprofit_new_501c3")) \
        == "name_cut_off"
    assert _unusable_reason({}, lead("Alan S. Gassman, P.A")) == "person_name"
    assert _unusable_reason({}, lead("Channel Robotics")) is None
    assert _unusable_reason({}, lead("Simplify 401(k) Pooled Employer Plan",
                                     "plan_late_contributions")) == "plan_name"
    assert _unusable_reason({}, lead("Peas Research")) is None


def test_a_first_plan_audit_is_cpa_work_and_new_york_registrations_stay_in_new_york():
    from system_b.gift.engine import _licensed_elsewhere, cpa_only
    plan = mk("p", "plan_audit_first_due", city="Austin", state="TX")
    plan.service_tags = []
    assert cpa_only(plan)
    law = mk("l", "ny_new_law_firm", city="Palm Beach", state="FL")
    assert _licensed_elsewhere(law, Prospect(firm_name="X", city="Tampa", state="FL"))
    assert not _licensed_elsewhere(law, Prospect(firm_name="X", city="Albany", state="NY"))


# --- 2026-11-11: the person on the record, and a fresh date -------------------

def _contact_lead(signal_type="construction_new_licensed_business", *, when="2026-10-23",
                  name="Edward Alex Polevoy", title="Principal", company="Alderlis Construction"):
    from system_b.models import Lead, Signal
    return Lead(id=f"x:{company}", company=company, city="Bothell", state="WA",
                signal_type=signal_type, contact_name=name, contact_title=title,
                signals=[Signal(type=signal_type, date=when, date_confidence="high",
                                plain_words_description="Licensed.", payload={})])


def test_contact_reads_role_first_and_drops_initials():
    from system_b.copy.facts import contact
    assert contact(_contact_lead()) == "principal Edward Polevoy"            # no middle name
    assert contact(_contact_lead(name="Maria Luisa de la Cruz Jr.")) == "principal Maria de la Cruz"
    assert contact(_contact_lead(name="DOUGLAS K BARDIN", title="PRINCIPAL")) == \
        "principal Douglas Bardin"
    assert contact(_contact_lead(title="Registered agent")) == ""       # not a role
    assert contact(_contact_lead(title="CFO")) == ""                    # has finance help
    assert contact(_contact_lead(name="Alderlis", title="Owner")) == ""  # the org's own name
    assert contact(_contact_lead(title="Authorized Official")) == "contact Edward Polevoy"


def test_fresh_date_only_when_recent_and_the_date_is_the_news():
    from datetime import date

    from system_b.copy.facts import fresh_date
    today = date(2026, 11, 11)
    assert fresh_date(_contact_lead(), today) == "oct 23"
    assert fresh_date(_contact_lead(when="2026-10-12"), today) == "oct 12"     # 30 days
    assert fresh_date(_contact_lead(when="2026-10-11"), today) == ""           # 31: too old
    assert fresh_date(_contact_lead("plan_late_contributions", when="2026-10-31"), today) == ""
    assert fresh_date(_contact_lead("adv_no_fund_administrator"), today) == ""
    assert fresh_date(_contact_lead("sba_7a_loan_approved"), today) == "oct 23"


def test_email_1_lines_carry_the_fact_date_and_person():
    from datetime import date

    from system_b.copy.email import record_opener
    from system_b.gift.models import Gift, Prospect
    leads = [_contact_lead(company=c, name=n) for c, n in
             (("Alderlis Construction", "Edward Alex Polevoy"),
              ("Paragon Home Services", "Matthew Donald Flores"))]
    g = Gift(leads=leads, best_lead=leads[0], gift_size=2, all_niche=False, geo_level="city",
             subject_shape="plural", what_category="construction", best_lead_level=1)
    p = Prospect(firm_name="Match", city="Bothell", state="WA", first_name="Terry")
    _, lines = record_opener(g, p, today=date(2026, 11, 11))
    assert lines[0] == "Alderlis Construction (oct 23, principal Edward Polevoy)"
    _, note = record_opener(g, p)          # the LinkedIn note: as before, no date
    assert note[0] == "Alderlis Construction (Edward Polevoy, principal)"


def test_a_named_lead_wins_a_tie():
    from system_b.gift.engine import sort_key
    named = _contact_lead(company="Named Co")
    bare = _contact_lead(company="Bare Co", name="")
    assert sort_key(named, salt="firm") < sort_key(bare, salt="firm")
    assert sort_key(named) < sort_key(bare)
