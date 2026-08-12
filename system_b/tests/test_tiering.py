"""Change 2 — three-tier niche resolution (both Gate B checks + framing verb).

Covers the spec's required cases with the pure resolver + FakeScraper + an
INJECTED fit-check (so tests stay offline/deterministic):
  * sole focus            -> "work with [niche]" (soft verb, never "focus on")
  * one of several        -> "work with [one niche]", names ONLY that niche
  * best-supplied pick    -> among fitting candidates, claim the one leads back
  * GATE B taxonomy       -> stated niche but no bucketed leads -> generalist
  * GATE B fit            -> leads bucketed to the niche but value_props DON'T
                             read as it (mis-tagged) -> drop -> generalist
  * granular child        -> "22 dental practices" claims `dental`, not healthcare
  * blob rejection        -> a multi-industry blob never becomes a claim
  * per-candidate phrase  -> the CLAIMED niche's phrase is what the card shows
  * raw-phrase guard      -> a saved website blob never reaches the copy

Run:  system_b/.venv/bin/python -m pytest system_b/tests/test_tiering.py -q
"""

from __future__ import annotations

from datetime import date

from system_b.copy.email import build_email_1
from system_b.gift.taxonomy import map_industry_candidates
from system_b.gift.tiering import resolve_gift
from system_b.research.models import Evidence, ResearchResult
from system_b.tests.test_gift import FakeScraper, mk

TODAY = date(2026, 7, 8)

TAXONOMY = {
    "healthcare": ["dental", "veterinary", "behavioral_health"],
    "construction": ["general_contractor", "specialty_trades"],
    "real_estate": ["brokerage", "proptech"],
    "software_saas": ["b2b_saas"],
    "nonprofit": [],
    "other": [],
    "unknown": [],
}


def _fit(*, per_id=None):
    """Fake fit-check. Default: everything fits. `per_id` overrides by lead id."""
    def f(label, leads):
        if per_id is not None:
            return [per_id.get(lead.id, True) for lead in leads]
        return [True] * len(leads)
    return f


_FIT_YES = _fit()


def _row(**kw):
    base = {"firm_name": "Test Firm", "city": "Denver", "state": "CO", "first_name": "sam"}
    base.update(kw)
    return base


def _research(match_params, *, exclusivity, phrases=None, niche_phrase="stated thing",
              niche_source="site", classification="niched"):
    return ResearchResult(
        classification=classification,
        match_param=match_params[0] if match_params else None,
        niche_phrase=niche_phrase,
        niche_source=niche_source,
        evidence=[Evidence("phrase", niche_phrase, "https://x.com")],
        candidate_match_params=list(match_params),
        candidate_phrases=list(phrases or []),
        exclusivity=exclusivity,
    )


def _body(prospect, gift):
    return build_email_1(gift, prospect, today=TODAY).body


# --------------------------------------------------------------------------
# map_industry_phrase — granular child preference + blob rejection
# --------------------------------------------------------------------------

def test_map_industry_candidates_prefers_child_over_coarse_guess():
    # "22 dental practices" -> dental, NOT the LLM's coarse guess "healthcare"
    assert map_industry_candidates("managed accounting for 22 dental practices",
                                   "healthcare", TAXONOMY) == [("niche", "dental")]
    # a clean single-industry phrase with no child -> the parent industry
    assert map_industry_candidates("residential construction companies",
                                   "construction", TAXONOMY) == [("industry", "construction")]


def test_map_industry_candidates_synonym_alias_fallback():
    # a distinctive one-word synonym maps when the strict all-tokens match misses
    # ("saas" alone never satisfies the `software_saas` key)...
    assert map_industry_candidates("saas", None, TAXONOMY) == [("industry", "software_saas")]
    # ...but the alias is a FALLBACK: when the phrase already names a real served
    # vertical, the alias word is the prospect's own service, not a 2nd vertical.
    assert map_industry_candidates("saas tools for dental practices", None, TAXONOMY) == \
        [("niche", "dental")]
    # a phrase with no vertical at all stays generalist (no alias, no guess)
    assert map_industry_candidates("veteran led businesses", None, TAXONOMY) == []


def test_map_industry_candidates_splits_multi_industry_phrase():
    # a phrase stating several industries -> ALL become candidates (children first)
    got = map_industry_candidates(
        "we serve dental practices, construction firms, and real estate brokerage",
        "consulting", TAXONOMY)
    assert set(got) == {("niche", "dental"), ("industry", "construction"), ("niche", "brokerage")}
    assert got[0][0] == "niche"                              # children sort ahead of bare industries
    # phrase itself maps to nothing, but the model's clean guess does -> use it
    assert map_industry_candidates("we help great teams win", "construction", TAXONOMY) == \
        [("industry", "construction")]


# --------------------------------------------------------------------------
# TIER 1 — sole focus (soft verb "work with", never "focus on")
# --------------------------------------------------------------------------

def test_tier1_sole_focus_construction():
    research = _research([("industry", "construction")], exclusivity="single",
                         phrases=["managing construction operations"],
                         niche_phrase="managing construction operations")
    leads = [
        mk("c1", "job_finance_lead", industry="construction", city="Denver", state="CO", date="2026-07-05", company="BuildCo", finance_grade="medium"),
        mk("c2", "funding_form_d", industry="construction", city="Denver", state="CO", date="2026-07-04", company="Framers LLC"),
        mk("c3", "job_finance_lead", industry="construction", city="Denver", state="CO", date="2026-07-03", company="Rebar Inc", finance_grade="strong"),
    ]
    prospect, gift = resolve_gift(research, _row(firm_name="Absolute Business Solutions"),
                                  FakeScraper(leads), fit=_FIT_YES)
    assert prospect.niche_exclusivity == "sole"
    assert prospect.match_param == ("industry", "construction")
    assert prospect.niche_phrase == "managing construction operations"   # claimed phrase
    assert gift is not None and gift.all_niche is True
    assert "saw on your site you work with construction companies, so i pulled 3 more" in _body(prospect, gift)


# --------------------------------------------------------------------------
# TIER 2 — one of several (verb "work with"), names only the gifted niche
# --------------------------------------------------------------------------

def test_tier2_one_of_several_real_estate():
    research = _research(
        [("industry", "real_estate"), ("industry", "nonprofit")],
        exclusivity="multiple",
        phrases=["real estate investors", "nonprofits"],
    )
    leads = [
        mk("r1", "funding_form_d", industry="real_estate", city="Denver", state="CO", date="2026-07-05", company="Mesa Realty"),
        mk("r2", "job_finance_lead", industry="real_estate", city="Denver", state="CO", date="2026-07-04", company="Vista Homes", finance_grade="medium"),
        mk("r3", "funding_form_d", industry="real_estate", city="Denver", state="CO", date="2026-07-03", company="Peak Estates"),
    ]
    prospect, gift = resolve_gift(research, _row(firm_name="Abrisma Accounting"),
                                  FakeScraper(leads), fit=_FIT_YES)
    assert prospect.niche_exclusivity == "one_of_several"
    assert prospect.match_param == ("industry", "real_estate")
    assert prospect.niche_phrase == "real estate investors"              # claimed candidate's phrase
    body = _body(prospect, gift)
    assert "noticed you work with real estate companies, so i pulled 3 more" in body
    assert "nonprofit" not in body                                       # never lists the other niche
    assert "focus on" not in body


def test_tier2_single_mapped_industry_still_one_of_several():
    research = _research([("industry", "real_estate")], exclusivity="multiple",
                         phrases=["real estate investors"],
                         niche_phrase="business owners, founders, real estate investors")
    leads = [
        mk("r1", "funding_form_d", industry="real_estate", city="Denver", state="CO", date="2026-07-05"),
        mk("r2", "job_finance_lead", industry="real_estate", city="Denver", state="CO", date="2026-07-04", finance_grade="medium"),
    ]
    prospect, gift = resolve_gift(research, _row(first_name="Akansha"), FakeScraper(leads), fit=_FIT_YES)
    assert prospect.niche_exclusivity == "one_of_several"
    assert "noticed you work with real estate companies" in _body(prospect, gift)


# --------------------------------------------------------------------------
# Best-supplied pick among fitting candidates.
# --------------------------------------------------------------------------

def test_picks_best_supplied_candidate():
    research = _research([("industry", "real_estate"), ("industry", "construction")],
                         exclusivity="multiple", phrases=["real estate", "construction"])
    leads = [
        mk("r1", "funding_form_d", industry="real_estate", city="Denver", state="CO", date="2026-07-05"),
        mk("c1", "funding_form_d", industry="construction", city="Denver", state="CO", date="2026-07-05"),
        mk("c2", "job_finance_lead", industry="construction", city="Denver", state="CO", date="2026-07-04", finance_grade="medium"),
        mk("c3", "funding_form_d", industry="construction", city="Denver", state="CO", date="2026-07-03"),
    ]
    prospect, gift = resolve_gift(research, _row(), FakeScraper(leads), fit=_FIT_YES)
    assert prospect.match_param == ("industry", "construction")
    assert gift.gift_size == 3


# --------------------------------------------------------------------------
# GATE B (taxonomy) — stated niche but no bucketed leads -> generalist.
# --------------------------------------------------------------------------

def test_gate_b_taxonomy_drops_when_no_niche_leads():
    research = _research([("industry", "real_estate")], exclusivity="single",
                         phrases=["real estate investors"])
    leads = [
        mk("s1", "funding_form_d", industry="software_saas", city="Denver", state="CO", date="2026-07-05", company="Bitly Co"),
        mk("s2", "job_finance_lead", industry="software_saas", city="Denver", state="CO", date="2026-07-04", company="Cloudy Inc", finance_grade="medium"),
    ]
    prospect, gift = resolve_gift(research, _row(), FakeScraper(leads), fit=_FIT_YES)
    assert prospect.niche_exclusivity == "none"
    assert prospect.classification == "generalist"
    assert gift is not None and gift.all_niche is False
    body = _body(prospect, gift)
    assert "real estate" not in body and "focus on" not in body and "work with" not in body
    assert "saw you're based in denver" in body


# --------------------------------------------------------------------------
# GATE B (fit) + NICHE-LIFT — a mis-tagged lead is SWAPPED OUT (never listed) and
# the niche is kept with the fitting leads; only when NOTHING fits do we drop to
# generalist. (Still prevents the Power CFO bug: the bad lead is never claimed.)
# --------------------------------------------------------------------------

def test_niche_lift_swaps_out_mistagged_lead_keeps_claim():
    research = _research([("industry", "manufacturing")], exclusivity="single",
                         phrases=["manufacturing"])
    leads = [
        mk("it", "job_fractional_cfo", industry="manufacturing", city="Denver", state="CO", date="2026-07-05", company="Iq Sig"),
        mk("m2", "job_finance_lead", industry="manufacturing", city="Denver", state="CO", date="2026-07-04", company="Real Mfg", finance_grade="medium"),
        mk("m3", "funding_form_d", industry="manufacturing", city="Denver", state="CO", date="2026-07-03", company="Also Mfg"),
    ]
    # taxonomy says all 3 are manufacturing, but the fit-check says the IT co isn't
    fit = _fit(per_id={"it": False, "m2": True, "m3": True})
    prospect, gift = resolve_gift(research, _row(), FakeScraper(leads), fit=fit)
    assert prospect.classification == "niched"                   # claim recovered by swapping the lead out
    assert prospect.match_param == ("industry", "manufacturing")
    body = _body(prospect, gift)
    assert "Iq Sig" not in body                                  # the mis-tagged lead is NEVER listed
    assert "manufacturing" in body                               # niche claimed, honestly


def test_niche_lift_drops_to_generalist_when_nothing_fits():
    research = _research([("industry", "manufacturing")], exclusivity="single",
                         phrases=["manufacturing"])
    leads = [
        mk("b1", "job_finance_lead", industry="manufacturing", city="Denver", state="CO", date="2026-07-05", company="Bad One", finance_grade="medium"),
        mk("b2", "funding_form_d", industry="manufacturing", city="Denver", state="CO", date="2026-07-04", company="Bad Two"),
    ]
    fit = _fit(per_id={"b1": False, "b2": False})                # no lead reads as the niche
    prospect, gift = resolve_gift(research, _row(), FakeScraper(leads), fit=fit)
    assert prospect.classification == "generalist"               # nothing fits -> honest generalist
    assert prospect.niche_exclusivity == "none"
    assert "manufacturing" not in _body(prospect, gift)


def test_gate_b_fit_all_pass_keeps_claim():
    research = _research([("industry", "manufacturing")], exclusivity="single",
                         phrases=["manufacturing"])
    leads = [
        mk("m1", "funding_form_d", industry="manufacturing", city="Denver", state="CO", date="2026-07-05"),
        mk("m2", "job_finance_lead", industry="manufacturing", city="Denver", state="CO", date="2026-07-04", finance_grade="medium"),
    ]
    prospect, gift = resolve_gift(research, _row(), FakeScraper(leads), fit=_FIT_YES)
    assert prospect.classification == "niched"
    assert prospect.match_param == ("industry", "manufacturing")


# --------------------------------------------------------------------------
# no leads at all -> no gift.
# --------------------------------------------------------------------------

def test_no_leads_at_all_is_no_gift():
    research = _research([("industry", "real_estate")], exclusivity="single", phrases=["real estate"])
    leads = [mk("x", "funding_form_d", industry="fintech", city="Austin", state="TX")]
    prospect, gift = resolve_gift(research, _row(), FakeScraper(leads), fit=_FIT_YES)
    assert gift is None
    assert prospect.classification == "generalist"


# --------------------------------------------------------------------------
# Change 3 — a raw website blob saved as niche_phrase never reaches the copy.
# --------------------------------------------------------------------------

def test_raw_phrase_blob_never_leaks_into_copy():
    research = _research(
        [("industry", "real_estate")], exclusivity="multiple",
        phrases=["real estate investors"],
        niche_phrase="WHO WE SERVE: real estate investors, nonprofits, designed for: growth",
    )
    leads = [
        mk("r1", "funding_form_d", industry="real_estate", city="Denver", state="CO", date="2026-07-05"),
        mk("r2", "job_finance_lead", industry="real_estate", city="Denver", state="CO", date="2026-07-04", finance_grade="medium"),
    ]
    prospect, gift = resolve_gift(research, _row(), FakeScraper(leads), fit=_FIT_YES)
    draft = build_email_1(gift, prospect, today=TODAY)
    blob = (draft.subject + "\n" + draft.body).lower()
    for leak in ("who we serve", "designed for", "nonprofit"):
        assert leak not in blob
    assert "work with real estate companies" in draft.body
