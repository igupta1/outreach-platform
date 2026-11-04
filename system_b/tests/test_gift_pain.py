"""The inventory's pain score in the gift (2026-11-03), offline.

Inside a strength band (and only there), a lead whose organization is in more
pain comes first, ahead of the type order; the level walk, the city-first rule
and the near-tie rotation are unchanged; a file without pain scores orders
exactly as before.
"""

from __future__ import annotations

from datetime import date

from system_b.clients.inventory import adapt_leadgen_lead
from system_b.clients.scraper_client import SnapshotScraper
from system_b.gift.engine import _best_lead, build_gift, strength
from system_b.gift.models import Prospect
from system_b.models import Lead, Signal

NP = "nonprofit_grant_no_finance_officer"
DB = "construction_federal_award_davis_bacon"
LIEN = "state_tax_lien"
NL = "construction_new_licensed_business"
PLAN = "plan_audit_first_due"
TODAY = date(2026, 11, 3)


def lead(name, signal_type, *, pain=None, score=50.0, city="Denver", state="CO",
         industry="other") -> Lead:
    return Lead(
        id=name, company=name, city=city, state=state, industry=industry,
        signal_type=signal_type, score=score, pain_score=pain, freshness="fresh",
        entity_id=f"uei:{name}",
        signals=[Signal(type=signal_type, date="2026-10-01", date_confidence="high",
                        plain_words_description="record", payload={})],
    )


def names(leads, target=3, firm="Ledger Books", city="Denver"):
    gift = build_gift(Prospect(firm_name=firm, city=city, state="CO"),
                      SnapshotScraper(leads, taxonomy={}), target=target)
    return [ld.company for ld in gift.leads] if gift else []


def test_more_pain_beats_the_type_order_inside_a_band():
    """Both STRONG: a kind of lead (here Davis-Bacon awards) whose orgs are in
    deep trouble beats charity audits with little else wrong."""
    audit = lead("Mild Audit", NP, pain=40, industry="nonprofit")
    award = lead("Troubled Builder", DB, pain=80)
    assert names([audit, award], target=1) == ["Troubled Builder"]


def test_a_gift_fills_from_the_kind_in_most_pain():
    """Three charity audits in real trouble beat one painful award: the gift
    stays one kind (one record opener), chosen by pain."""
    audits = [lead(f"Audit {i}", NP, pain=70, industry="nonprofit") for i in range(3)]
    award = lead("Award", DB, pain=90)
    assert sorted(names([award, *audits])) == ["Audit 0", "Audit 1", "Audit 2"]
    # ...and awards in more pain than the audits win the whole gift
    awards = [lead(f"Award {i}", DB, pain=85) for i in range(3)]
    assert sorted(names([*awards, *audits])) == ["Award 0", "Award 1", "Award 2"]


def test_pain_never_crosses_a_band():
    """A tax lien (WEAK) with pain 99 never beats a MEDIUM or STRONG lead."""
    lien = lead("Big Lien", LIEN, pain=99)
    plan = lead("First Plan Audit", PLAN, pain=30)
    award = lead("Award", DB, pain=20)
    assert names([lien, plan, award]) == ["Award", "First Plan Audit", "Big Lien"]


def test_the_city_still_comes_first_inside_a_band():
    here = lead("Denver Award", DB, pain=30)
    there = lead("Boulder Award", DB, pain=90, city="Boulder")
    assert names([there, here], target=1) == ["Denver Award"]


def test_within_a_pain_band_the_type_order_then_the_score():
    """Kinds whose pain falls in one band: the stronger type first."""
    audit = lead("Audit", NP, pain=81, industry="nonprofit")
    award = lead("Award", DB, pain=84)
    assert names([award, audit], target=2) == ["Audit", "Award"]


def test_near_ties_in_pain_rotate_per_firm_and_never_beat_more_pain():
    band = [lead(f"Award {i}", DB, pain=70 + i % 5) for i in range(10)]
    top = lead("Most Pain", DB, pain=90)
    firms = ("Acme CPA", "Ledger Bridge", "Peach CFO", "Denman & Co", "Apex Books")
    gifts = [names([*band, top], firm=f) for f in firms]
    assert all(g[0] == "Most Pain" for g in gifts)
    assert len({tuple(g[1:]) for g in gifts}) > 1
    assert names([*band, top], firm="Acme CPA") == gifts[0]          # deterministic


def test_without_pain_the_old_order_holds():
    """No pain score: type order, then the percentile score, as before."""
    audit = lead("Audit", NP, score=10, industry="nonprofit")
    award = lead("Award", DB, score=99)
    assert names([award, audit], target=2) == ["Audit", "Award"]
    assert strength(lead("X", NP, score=60)) == 60


def test_the_subject_speaks_for_the_most_pain_inside_the_band():
    gift = [lead("Audit", NP, pain=40, industry="nonprofit"), lead("Award", DB, pain=85),
            lead("Lien", LIEN, pain=99)]
    best = _best_lead(gift, Prospect(firm_name="Ledger Books", city="Denver", state="CO"))
    assert best.company == "Award"


def test_the_adapter_reads_pain_beside_score():
    row = {"id": "x1", "name": "Acme Builders Inc", "signal_type": NL, "city": "Denver",
           "state": "CO", "domain": "acme.example", "score": 42, "pain_score": 63,
           "pain_reasons": ["newly licensed contractor", "also federal tax lien filed"],
           "status": "active", "expires_at": "2099-01-01",
           "signals": [{"type": NL, "event_date": "2026-10-01", "payload": {}}]}
    ld = adapt_leadgen_lead(row, today=TODAY)
    assert (ld.score, ld.pain_score) == (42, 63.0)
    assert ld.pain_reasons[1] == "also federal tax lien filed"
    assert adapt_leadgen_lead({**row, "pain_score": None}, today=TODAY).pain_score is None
    assert adapt_leadgen_lead({**row, "pain_score": "high"}, today=TODAY).pain_score is None
