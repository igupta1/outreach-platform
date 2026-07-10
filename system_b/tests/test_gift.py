"""M1 acceptance — all 16 Part-4 worked examples as fixtures.

Each example builds a small lead universe, runs the pure gift engine
against a FakeScraper (which filters/sorts exactly like the live
/api/leads), and asserts the gift shape + honesty values + subject-shape
inputs the spec calls out.

Field-name reality (see system_b/models.py): the live API has no
top-level `score`/`finance_grade`, so within-level re-sort is
signal-rank -> newest-date -> date_confidence, and best-lead is
signal-rank -> freshness -> match-level. The examples don't turn on
`score`, so this reproduces them exactly.

Run:  system_b/.venv/bin/python -m pytest system_b/tests/test_gift.py -q
"""

from __future__ import annotations

from typing import Any

from system_b.gift.engine import (
    build_gift,
    compute_match_level,
    norm_loc,
    norm_state,
    pull_one_lead,
    sort_key,
)
from system_b.gift.models import Prospect
from system_b.gift.taxonomy import map_prospect
from system_b.models import Lead, Signal


# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------

def mk(
    id: str,
    signal_type: str,
    *,
    city: str | None = None,
    state: str | None = None,
    industry: str | None = None,
    niche: str | None = None,
    freshness: str = "fresh",
    date: str = "2026-07-01",
    date_confidence: str = "high",
    company: str | None = None,
    domain: str | None = "example.com",
    finance_grade: str | None = None,
) -> Lead:
    return Lead(
        id=id,
        company=company or id,
        domain=domain,
        city=city,
        state=state,
        industry=industry,
        niche=niche,
        value_prop="does things",
        signal_type=signal_type,
        finance_grade=finance_grade,
        freshness=freshness,
        signals=[
            Signal(
                type=signal_type,
                date=date,
                date_confidence=date_confidence,
                plain_words_description="did a thing",
            )
        ],
    )


class FakeScraper:
    """Filters/sorts a fixed lead list the way the live API does: params
    AND-combined, freshest-first, exclude_ids honored, limit last."""

    def __init__(self, leads: list[Lead]) -> None:
        self._leads = leads

    def leads(self, **p: Any) -> list[Lead]:
        excl = p.get("exclude_ids") or []
        if isinstance(excl, str):
            excl = [x for x in excl.split(",") if x]
        excluded = set(excl)

        out: list[Lead] = []
        for l in self._leads:
            if l.id in excluded:
                continue
            if p.get("niche") is not None and l.niche != p["niche"]:
                continue
            if p.get("industry") is not None and l.industry != p["industry"]:
                continue
            if p.get("city") is not None and norm_loc(l.city) != norm_loc(p["city"]):
                continue
            if p.get("state") is not None and norm_state(l.state) != norm_state(p["state"]):
                continue
            if p.get("signal_type") is not None and l.signal_type != p["signal_type"]:
                continue
            if p.get("finance_grade") is not None and l.finance_grade != p["finance_grade"]:
                continue
            if p.get("freshness") is not None and l.freshness != p["freshness"]:
                continue
            out.append(l)

        out.sort(key=lambda l: l.newest_date, reverse=True)  # freshest-first
        limit = p.get("limit")
        if limit:
            out = out[:limit]
        return out


def ids(gift: Any) -> set[str]:
    return {l.id for l in gift.leads}


# --------------------------------------------------------------------------
# Example 1 — healthcare/Denver, 3 fresh L1 (funding, funding, hiring), mixed
# --------------------------------------------------------------------------

def test_example_1_healthcare_denver_mixed_l1():
    p = Prospect(
        firm_name="Denver Health CFOs", city="Denver", state="CO",
        classification="niched", match_param=("industry", "healthcare"),
    )
    leads = [
        mk("h1", "funding_only", industry="healthcare", city="Denver", state="CO", date="2026-07-03"),
        mk("h2", "funding_only", industry="healthcare", city="Denver", state="CO", date="2026-07-02"),
        mk("h3", "hiring_only", industry="healthcare", city="Denver", state="CO", date="2026-07-01", finance_grade="medium"),
    ]
    g = build_gift(p, FakeScraper(leads))
    assert g is not None
    assert g.gift_size == 3
    assert ids(g) == {"h1", "h2", "h3"}
    assert g.all_niche is True
    assert g.geo_level == "city"
    assert g.subject_shape == "plural"
    assert g.what_category == "mixed"


# --------------------------------------------------------------------------
# Example 2 — same prospect, leads double/funding/funding -> all raised
# --------------------------------------------------------------------------

def test_example_2_healthcare_denver_all_raised():
    p = Prospect(
        firm_name="Denver Health CFOs", city="Denver", state="CO",
        classification="niched", match_param=("industry", "healthcare"),
    )
    leads = [
        mk("d1", "double_signal", industry="healthcare", city="Denver", state="CO", date="2026-07-03"),
        mk("f2", "funding_only", industry="healthcare", city="Denver", state="CO", date="2026-07-02"),
        mk("f3", "funding_only", industry="healthcare", city="Denver", state="CO", date="2026-07-01"),
    ]
    g = build_gift(p, FakeScraper(leads))
    assert g is not None
    assert g.gift_size == 3
    assert g.all_niche is True
    assert g.geo_level == "city"
    assert g.subject_shape == "plural"
    assert g.what_category == "raised"


# --------------------------------------------------------------------------
# Example 3 — construction/Austin, 2 fresh L2 (TX) + 1 fresh L3 (Ohio), hiring
# all_niche TRUE, geo NONE (Ohio breaks state)
# --------------------------------------------------------------------------

def test_example_3_construction_l2_l3_hiring_geo_none():
    p = Prospect(
        firm_name="BuildBooks", city="Austin", state="TX",
        classification="niched", match_param=("industry", "construction"),
    )
    leads = [
        mk("tx1", "hiring_only", industry="construction", city="Houston", state="TX", date="2026-07-03", finance_grade="medium"),
        mk("tx2", "hiring_only", industry="construction", city="Dallas", state="TX", date="2026-07-02", finance_grade="strong"),
        mk("oh1", "hiring_only", industry="construction", city="Columbus", state="OH", date="2026-07-01", finance_grade="medium"),
    ]
    g = build_gift(p, FakeScraper(leads))
    assert g is not None
    assert g.gift_size == 3
    assert ids(g) == {"tx1", "tx2", "oh1"}
    assert g.all_niche is True          # all matched via industry (L2/L3)
    assert g.geo_level == "none"        # Ohio lead is out of state
    assert g.subject_shape == "plural"
    assert g.what_category == "hiring"


# --------------------------------------------------------------------------
# Example 4 — SaaS/Phoenix, L1-L3 empty, 2 fresh L4 + 1 fresh L5
# all_niche FALSE, geo STATE, mixed
# --------------------------------------------------------------------------

def test_example_4_saas_l4_l5_all_niche_false_geo_state():
    p = Prospect(
        firm_name="Cactus CFO", city="Phoenix", state="AZ",
        classification="niched", match_param=("industry", "software_saas"),
    )
    leads = [
        mk("px1", "funding_only", industry="construction", city="Phoenix", state="AZ", date="2026-07-03"),
        mk("px2", "hiring_only", industry="healthcare", city="Phoenix", state="AZ", date="2026-07-02", finance_grade="medium"),
        mk("tuc", "funding_only", industry="ecommerce_retail", city="Tucson", state="AZ", date="2026-07-01"),
    ]
    g = build_gift(p, FakeScraper(leads))
    assert g is not None
    assert g.gift_size == 3
    assert ids(g) == {"px1", "px2", "tuc"}
    assert g.all_niche is False         # no lead matched software_saas
    assert g.geo_level == "state"       # all AZ, not all Phoenix
    assert g.subject_shape == "plural"
    assert g.what_category == "mixed"


# --------------------------------------------------------------------------
# Example 5 — generalist/Chicago, cfo_wanted (3a) + 2 fresh L1. SINGULAR.
# best lead level = city (generalist L1). No date claim (low confidence).
# --------------------------------------------------------------------------

def test_example_5_generalist_cfo_wanted_singular():
    p = Prospect(
        firm_name="Windy City Finance", city="Chicago", state="IL",
        classification="generalist", match_param=None,
    )
    leads = [
        mk("cfo", "cfo_wanted", city="Chicago", state="IL", date="2026-06-20",
           date_confidence="low", domain=None),
        mk("c1", "funding_only", city="Chicago", state="IL", date="2026-07-03"),
        mk("c2", "hiring_only", city="Chicago", state="IL", date="2026-07-02", finance_grade="medium"),
    ]
    g = build_gift(p, FakeScraper(leads))
    assert g is not None
    assert g.gift_size == 3
    assert ids(g) == {"cfo", "c1", "c2"}
    assert g.best_lead.id == "cfo"           # cfo_wanted outranks everything
    assert g.best_lead_level == 1            # generalist L1 = city
    assert g.subject_shape == "singular"     # cfo_wanted forces singular
    assert g.all_niche is False
    assert g.geo_level == "city"


# --------------------------------------------------------------------------
# Example 6 — healthcare/Sacramento, 3a cfo_wanted in San Diego (L2) beats
# the 3 fresh L1 funding leads. gift = cfo + 2 L1. SINGULAR, geo STATE.
# --------------------------------------------------------------------------

def test_example_6_3a_cfo_wanted_beats_l1():
    p = Prospect(
        firm_name="Sac Health CFO", city="Sacramento", state="CA",
        classification="niched", match_param=("industry", "healthcare"),
    )
    leads = [
        mk("sd_cfo", "cfo_wanted", industry="healthcare", city="San Diego", state="CA",
           date="2026-06-25", date_confidence="low", domain=None),
        mk("s1", "funding_only", industry="healthcare", city="Sacramento", state="CA", date="2026-07-03"),
        mk("s2", "funding_only", industry="healthcare", city="Sacramento", state="CA", date="2026-07-02"),
        mk("s3", "funding_only", industry="healthcare", city="Sacramento", state="CA", date="2026-07-01"),
    ]
    g = build_gift(p, FakeScraper(leads))
    assert g is not None
    assert g.gift_size == 3
    assert "sd_cfo" in ids(g)                # 3a lead is in the gift
    assert g.best_lead.id == "sd_cfo"
    assert g.best_lead_level == 2            # healthcare + state
    assert g.subject_shape == "singular"
    assert g.all_niche is True
    assert g.geo_level == "state"
    # exactly 2 of the 3 L1 funding leads were pulled
    assert len(ids(g) & {"s1", "s2", "s3"}) == 2


# --------------------------------------------------------------------------
# Example 7 — ecommerce/Nashville, one usable lead: fresh L2 funding (Memphis).
# SINGULAR, geo STATE, best lead L2.
# --------------------------------------------------------------------------

def test_example_7_single_lead_l2():
    p = Prospect(
        firm_name="Music City CFO", city="Nashville", state="TN",
        classification="niched", match_param=("industry", "ecommerce_retail"),
    )
    leads = [
        mk("mem", "funding_only", industry="ecommerce_retail", city="Memphis", state="TN", date="2026-07-01"),
    ]
    g = build_gift(p, FakeScraper(leads))
    assert g is not None
    assert g.gift_size == 1
    assert ids(g) == {"mem"}
    assert g.subject_shape == "singular"     # single lead
    assert g.best_lead_level == 2
    assert g.all_niche is True
    assert g.geo_level == "state"
    assert g.what_category == "raised"


# --------------------------------------------------------------------------
# Example 8 — generalist/Miami, 2 fresh L1 both hiring. PLURAL, geo CITY.
# --------------------------------------------------------------------------

def test_example_8_generalist_two_l1_hiring():
    p = Prospect(
        firm_name="Miami Numbers", city="Miami", state="FL",
        classification="generalist", match_param=None,
    )
    leads = [
        mk("m1", "hiring_only", city="Miami", state="FL", date="2026-07-03", finance_grade="strong"),
        mk("m2", "hiring_only", city="Miami", state="FL", date="2026-07-02", finance_grade="medium"),
    ]
    g = build_gift(p, FakeScraper(leads))
    assert g is not None
    assert g.gift_size == 2
    assert ids(g) == {"m1", "m2"}
    assert g.all_niche is False
    assert g.geo_level == "city"
    assert g.subject_shape == "plural"
    assert g.what_category == "hiring"


# --------------------------------------------------------------------------
# Example 9 — fintech/Boise, 1 fresh L3 (NYC) + 1 stale L5 (Idaho) from Round 2.
# all_niche FALSE, geo NONE, PLURAL.
# --------------------------------------------------------------------------

def test_example_9_fresh_far_plus_stale_state_round2():
    p = Prospect(
        firm_name="Spud Capital CFO", city="Boise", state="ID",
        classification="niched", match_param=("industry", "fintech"),
    )
    leads = [
        mk("nyc", "funding_only", industry="fintech", city="New York", state="NY", freshness="fresh", date="2026-07-01"),
        mk("ida", "hiring_only", industry="other", city="Nampa", state="ID", freshness="stale", date="2026-06-01", finance_grade="medium"),
    ]
    g = build_gift(p, FakeScraper(leads))
    assert g is not None
    assert g.gift_size == 2
    assert ids(g) == {"nyc", "ida"}          # fresh L3 first, then stale L5
    assert g.all_niche is False              # Idaho lead is L5
    assert g.geo_level == "none"             # NYC breaks state
    assert g.subject_shape == "plural"
    assert g.what_category == "mixed"


# --------------------------------------------------------------------------
# Example 10 — healthcare/Boston. L1: 1 fresh + 2 stale; L2: 2 fresh.
# Round 1 fills it (1 L1 + 2 L2). Stale L1 leads never touched.
# --------------------------------------------------------------------------

def test_example_10_fresh_farther_beats_stale_closer():
    p = Prospect(
        firm_name="Bean Town CFO", city="Boston", state="MA",
        classification="niched", match_param=("industry", "healthcare"),
    )
    leads = [
        mk("bos_fresh", "funding_only", industry="healthcare", city="Boston", state="MA", freshness="fresh", date="2026-07-03"),
        mk("bos_stale1", "funding_only", industry="healthcare", city="Boston", state="MA", freshness="stale", date="2026-06-01"),
        mk("bos_stale2", "hiring_only", industry="healthcare", city="Boston", state="MA", freshness="stale", date="2026-06-02", finance_grade="medium"),
        mk("ma_fresh1", "funding_only", industry="healthcare", city="Worcester", state="MA", freshness="fresh", date="2026-07-02"),
        mk("ma_fresh2", "hiring_only", industry="healthcare", city="Cambridge", state="MA", freshness="fresh", date="2026-07-01", finance_grade="strong"),
    ]
    g = build_gift(p, FakeScraper(leads))
    assert g is not None
    assert g.gift_size == 3
    assert ids(g) == {"bos_fresh", "ma_fresh1", "ma_fresh2"}
    assert "bos_stale1" not in ids(g)        # stale L1 never touched
    assert "bos_stale2" not in ids(g)
    assert g.all_niche is True
    assert g.geo_level == "state"            # 2 leads outside Boston


# --------------------------------------------------------------------------
# Example 11 — legal/rural MT, both rounds empty -> remove prospect.
# --------------------------------------------------------------------------

def test_example_11_zero_leads_drops_prospect():
    p = Prospect(
        firm_name="Big Sky Ledger", city="Ekalaka", state="MT",
        classification="niched", match_param=("industry", "professional_services"),
    )
    other_state = [mk("x", "funding_only", industry="fintech", city="Austin", state="TX")]
    g = build_gift(p, FakeScraper(other_state))
    assert g is None                         # 0 leads -> no gift, drop + log


# --------------------------------------------------------------------------
# Example 12 — follow-up pull (M8 acceptance; mechanics available at M1).
# Pull ONE new lead, exclude_ids = already-sent. Value/fallback copy is M2/M8;
# here we prove the pull returns the right lead and honors exclude_ids.
# --------------------------------------------------------------------------

def test_example_12_followup_pull_excludes_sent():
    p = Prospect(
        firm_name="Denver Health CFOs", city="Denver", state="CO",
        classification="niched", match_param=("industry", "healthcare"),
        sent_lead_ids=["h1", "h2", "h3"],
    )
    # A fresh double_signal (2 days ago, high-confidence) is the value-version lead.
    leads = [
        mk("h1", "funding_only", industry="healthcare", city="Denver", state="CO"),
        mk("h2", "funding_only", industry="healthcare", city="Denver", state="CO"),
        mk("h3", "hiring_only", industry="healthcare", city="Denver", state="CO"),
        mk("new_ds", "double_signal", industry="healthcare", city="Denver", state="CO",
           freshness="fresh", date="2026-07-05", date_confidence="high"),
    ]
    lead = pull_one_lead(p, FakeScraper(leads))
    assert lead is not None
    assert lead.id == "new_ds"                       # new, not an already-sent id
    assert lead.id not in p.sent_lead_ids

    # cfo_wanted still surfaces via 3a; copy layer turns it into "just found one".
    leads2 = [
        mk("new_cfo", "cfo_wanted", industry="healthcare", city="Denver", state="CO",
           freshness="fresh", date="2026-06-20", date_confidence="low", domain=None),
    ]
    lead2 = pull_one_lead(p, FakeScraper(leads2))
    assert lead2 is not None and lead2.id == "new_cfo"

    # nothing new -> no pull (copy layer emits the fallback version).
    assert pull_one_lead(p, FakeScraper(leads[:3])) is None


# --------------------------------------------------------------------------
# Example 13 — taxonomy mapping (Step 2b).
# --------------------------------------------------------------------------

def test_example_13_taxonomy_mapping():
    taxonomy = {
        "healthcare": ["dental", "veterinary", "behavioral_health"],
        "fintech": ["payments", "lending"],
        "software_saas": ["devtools", "vertical_saas"],
        "other": ["misc"],
        "unknown": [],
    }
    # child match -> niche
    assert map_prospect("we serve dental practices", taxonomy) == ("niched", ("niche", "dental"))
    # parent match -> industry
    assert map_prospect("we serve healthcare startups", taxonomy) == ("niched", ("industry", "healthcare"))
    # no match -> generalist (phrase saved elsewhere, never claimed)
    assert map_prospect("we serve credit unions", taxonomy) == ("generalist", None)
    # #8: a phrase spanning 2+ industries can't be honestly narrowed -> generalist
    assert map_prospect("we serve healthcare and fintech clients", taxonomy) == ("generalist", None)
    assert map_prospect("dental practices and payments companies", taxonomy) == ("generalist", None)


# --------------------------------------------------------------------------
# Example 14 — megacorp exclude is System A's job; System B does NOT re-filter.
# "Canon USA" was already dropped upstream (never in the API response). A real
# small firm the API DOES return ("Canon Plumbing") passes straight through.
# --------------------------------------------------------------------------

def test_example_14_system_b_does_not_refilter_brands():
    p = Prospect(
        firm_name="Trades CFO", city="Toledo", state="OH",
        classification="generalist", match_param=None,
    )
    # System A already excluded "Canon USA"; it simply isn't in the feed.
    leads = [
        mk("plumb", "hiring_only", company="Canon Plumbing", city="Toledo", state="OH", finance_grade="medium"),
    ]
    g = build_gift(p, FakeScraper(leads))
    assert g is not None
    assert ids(g) == {"plumb"}               # brand-named small firm passes through


# --------------------------------------------------------------------------
# Example 15 — finance-vertical exclude is also System A's job. A preserved
# fintech *product* startup ("Rain") the API returns is gifted as-is.
# --------------------------------------------------------------------------

def test_example_15_system_b_does_not_refilter_verticals():
    p = Prospect(
        firm_name="Fintech CFO Co", city="Austin", state="TX",
        classification="niched", match_param=("industry", "fintech"),
    )
    # "Solvay Bank" was dropped upstream; "Rain" (a product startup) was kept.
    leads = [
        mk("rain", "hiring_only", company="Rain", industry="fintech", city="Austin", state="TX", finance_grade="weak"),
    ]
    g = build_gift(p, FakeScraper(leads))
    assert g is not None
    assert ids(g) == {"rain"}


# --------------------------------------------------------------------------
# Example 16 — confluence: a double_signal (Controller + Form D) outranks a
# lone medium Controller in the within-level re-sort and becomes the best lead.
# --------------------------------------------------------------------------

def test_example_16_double_signal_outranks_lone_controller():
    p = Prospect(
        firm_name="Hard Hat CFO", city="Austin", state="TX",
        classification="niched", match_param=("industry", "construction"),
    )
    leads = [
        # same level (industry + city); the lone Controller is FRESHER on date...
        mk("controller", "hiring_only", industry="construction", city="Austin", state="TX",
           date="2026-07-04", finance_grade="medium"),
        # ...but the double_signal outranks it by signal type in the re-sort.
        mk("confluence", "double_signal", industry="construction", city="Austin", state="TX",
           date="2026-07-01"),
    ]
    g = build_gift(p, FakeScraper(leads))
    assert g is not None
    assert g.best_lead.id == "confluence"        # signal rank beats recency for best lead
    assert g.leads[0].id == "confluence"         # and leads the within-level re-sort

    # the re-sort itself: double_signal sorts before hiring_only despite older date
    ordered = sorted(leads, key=sort_key)
    assert [l.id for l in ordered] == ["confluence", "controller"]


# --------------------------------------------------------------------------
# Sanity: match-level ladder (niched + generalist).
# --------------------------------------------------------------------------

def test_compute_match_level_ladder():
    niched = Prospect(
        firm_name="N", city="Denver", state="CO",
        classification="niched", match_param=("industry", "healthcare"),
    )
    assert compute_match_level(mk("a", "funding_only", industry="healthcare", city="Denver", state="CO"), niched) == 1
    assert compute_match_level(mk("b", "funding_only", industry="healthcare", city="Boulder", state="CO"), niched) == 2
    assert compute_match_level(mk("c", "funding_only", industry="healthcare", city="Miami", state="FL"), niched) == 3
    assert compute_match_level(mk("d", "funding_only", industry="fintech", city="Denver", state="CO"), niched) == 4
    assert compute_match_level(mk("e", "funding_only", industry="fintech", city="Boulder", state="CO"), niched) == 5
    assert compute_match_level(mk("f", "funding_only", industry="fintech", city="Miami", state="FL"), niched) is None

    gen = Prospect(firm_name="G", city="Denver", state="CO", classification="generalist", match_param=None)
    assert compute_match_level(mk("g", "funding_only", city="Denver", state="CO"), gen) == 1
    assert compute_match_level(mk("h", "funding_only", city="Boulder", state="CO"), gen) == 2
    assert compute_match_level(mk("i", "funding_only", city="Miami", state="FL"), gen) is None
