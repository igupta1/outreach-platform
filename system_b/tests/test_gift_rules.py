"""The user's gift rules (2026-10-18), offline:

1. industry + area always take precedence (the match-level walk is unchanged);
2. a firm's CLEAR focus is a tiebreak among leads at the SAME match level;
3. Row 8 (new_business_*) only fills places nothing else could;
4. within a signal type by score, across types by strength order;
and the standing ones: never a firm's own audit client, never an organization
already handed to another firm in the region.
"""

from __future__ import annotations

from system_b.clients.scraper_client import SnapshotScraper
from system_b.gift.engine import TYPE_ORDER, build_gift
from system_b.gift.models import Prospect
from system_b.models import Lead, Signal
from system_b.research.rung import clear_focus, detect_rung

NP = "nonprofit_grant_no_finance_officer"
DB = "construction_federal_award_davis_bacon"
CR = "federal_cost_reimbursement_contract"
FG = "federal_first_time_grant"
UP = "construction_license_upgrade"
NL = "construction_new_licensed_business"
NB = "new_business_formed"

TAGS = {
    NP: ["controls_remediation", "bookkeeping", "fractional_cfo"],
    DB: ["construction_accounting", "payroll_setup", "bookkeeping"],
    CR: ["govcon_accounting", "bookkeeping", "fractional_cfo"],
    FG: ["grant_accounting", "bookkeeping"],
    NL: ["construction_accounting", "bookkeeping_setup", "payroll_setup", "bookkeeping"],
    NB: ["bookkeeping_setup", "tax_setup", "payroll_setup"],
}


def lead(name, signal_type, *, city="Denver", state="CO", industry="construction",
         score=50.0, tags=None, payload=None) -> Lead:
    return Lead(
        id=name, company=name, city=city, state=state, industry=industry,
        signal_type=signal_type, score=score, freshness="fresh", entity_id=f"uei:{name}",
        service_tags=TAGS.get(signal_type, []) if tags is None else tags,
        signals=[Signal(type=signal_type, date="2026-10-01", date_confidence="high",
                        plain_words_description="record", payload=dict(payload or {}))],
    )


def names(prospect, leads, **kw):
    gift = build_gift(prospect, SnapshotScraper(leads, taxonomy={}), **kw)
    return [ld.company for ld in gift.leads] if gift else []


def geo(**kw) -> Prospect:
    return Prospect(firm_name="Ledger Books", city="Denver", state="CO", **kw)


# --- 1. precedence -----------------------------------------------------------


def test_a_closer_match_level_beats_a_stronger_signal_type():
    city_new_license = lead("City License Llc", NL)                          # L1 city
    state_audit = lead("State Charity", NP, city="Boulder", industry="nonprofit")  # L2
    assert names(geo(), [state_audit, city_new_license], target=2) == \
        ["City License Llc", "State Charity"]


def test_the_industry_levels_come_before_any_geography():
    p = geo(classification="niched", match_param=("industry", "construction"))
    on_niche_far = lead("Far Builders", NL, city="Tampa", state="FL")        # L3
    off_niche_here = lead("Here Charity", NP, industry="nonprofit")          # L4
    assert names(p, [off_niche_here, on_niche_far], target=2) == \
        ["Far Builders", "Here Charity"]


# --- 2. focus: a tiebreak at the SAME level, only when clear ----------------


def test_a_clear_focus_prefers_suited_leads_at_the_same_level():
    award = lead("Award Builders", DB)          # stronger type, construction tags
    contract = lead("Contract Labs", CR)        # weaker type, fractional_cfo tag
    assert names(geo(), [award, contract], target=1) == ["Award Builders"]
    assert names(geo(focus="cfo"), [award, contract], target=1) == ["Contract Labs"]
    assert names(geo(focus="accounting"), [award, contract], target=1) == ["Award Builders"]


def test_focus_never_crosses_a_match_level():
    award_here = lead("Award Builders", DB)                          # L1, unsuited
    contract_state = lead("Contract Labs", CR, city="Boulder")       # L2, suited
    assert names(geo(focus="cfo"), [contract_state, award_here], target=1) == \
        ["Award Builders"]


def test_focus_never_limits_the_gift():
    only_unsuited = [lead(f"Builder {i}", DB) for i in range(3)]
    assert len(names(geo(focus="cfo"), only_unsuited)) == 3


def test_focus_is_set_only_when_the_site_is_plainly_one_kind_of_work():
    books = {"x": "Bookkeeping for small business: QuickBooks cleanup, accounts payable, "
                  "monthly reconciliations and catch-up bookkeeping."}
    mixed = {"x": "Bookkeeping, QuickBooks and reconciliations, plus fractional CFO "
                  "services, FP&A and board reporting."}
    assert clear_focus(books) == "bookkeeping"
    assert clear_focus(mixed) is None
    assert detect_rung(mixed)[0] is not None        # the voice is still chosen
    assert clear_focus({}) is None


def test_the_focus_reaches_the_prospect_from_research():
    from system_b.gift.tiering import _base_prospect
    from system_b.research.models import ResearchResult
    r = ResearchResult(classification="generalist", match_param=None, niche_phrase=None,
                       niche_source=None)
    r.rung_focus = "accounting"
    p = _base_prospect({"firm_name": "Ledger"}, r, classification="generalist")
    assert p.focus == "accounting"


# --- 3. Row 8 only as fill ---------------------------------------------------


def test_new_businesses_only_fill_places_nothing_else_could():
    new_here = [lead(f"New {i} Llc", NB, industry="other", score=99) for i in range(3)]
    charity_far = lead("Far Charity", NP, city="Boulder", industry="nonprofit", score=1)
    got = names(geo(), [*new_here, charity_far])
    assert got[0] == "Far Charity"                  # L2, still before an L1 new business
    assert len(got) == 3 and all(n.startswith("New ") for n in got[1:])


def test_no_new_business_when_other_leads_can_fill_the_gift():
    others = [lead("A Builders", NL), lead("B Labs", CR, city="Boulder"),
              lead("C Charity", NP, city="Aurora", state="CO", industry="nonprofit")]
    new = lead("New Llc", NB, industry="other", score=100)
    assert "New Llc" not in names(geo(), [new, *others])


def test_row_8_fills_a_niche_gift_only_after_the_niche_runs_dry():
    p = geo(classification="niched", match_param=("industry", "real_estate"))
    re_new = lead("Perry Ave Llc", NB, industry="real_estate")
    assert names(p, [re_new], niche_only=True) == ["Perry Ave Llc"]


def test_the_fill_keeps_the_off_limits_rules():
    blocked = lead("Taken Llc", NB, industry="other")
    free = lead("Free Llc", NB, industry="other")
    p = geo(blocked_identities=frozenset({"uei:taken llc"}))
    assert names(p, [blocked, free]) == ["Free Llc"]
    audit_client = lead("Client Charity", NP, industry="nonprofit",
                        payload={"fac_auditor_firm": "Denman & Company, LLP"})
    mine = Prospect(firm_name="Denman & Co CPAs", city="Denver", state="CO")
    assert names(mine, [audit_client, free]) == ["Free Llc"]


# --- 4. order -----------------------------------------------------------------


def test_types_follow_the_strength_order_and_score_orders_within_a_type():
    leads = [
        lead("New License 99", NL, score=99), lead("Upgrade", UP, score=1),
        lead("Award 10", DB, score=10), lead("Grant", FG, score=5),
        lead("Award 50", DB, score=50), lead("Charity", NP, industry="nonprofit", score=1),
        lead("Contract", CR, score=1),
    ]
    assert names(geo(), leads, target=7) == [
        "Charity", "Award 50", "Award 10", "Contract", "Grant", "Upgrade", "New License 99"]


def test_the_strength_order_is_the_users():
    order = sorted((t for t in (NP, DB, CR, FG, UP, NL, NB)), key=TYPE_ORDER.__getitem__)
    assert order == [NP, DB, CR, FG, UP, NL, NB]


def test_the_subject_speaks_for_the_strongest_lead():
    gift = build_gift(geo(), SnapshotScraper(
        [lead("New License", NL, score=99), lead("Award", DB, score=1)], taxonomy={}))
    assert gift.best_lead.company == "Award"
