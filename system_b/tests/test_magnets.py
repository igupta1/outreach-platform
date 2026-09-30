"""The vertical lead magnets: identity, freshness, and the templated lines.

These cover the seams where a magnet lead differs from a job-post lead — the
places where reusing the job-post assumptions fails silently rather than
loudly."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import ClassVar

from system_b.clients.inventory import _entity_id, _is_expired_job_lead, adapt_leadgen_lead
from system_b.copy.email import (
    ecommerce_phrase,
    funds_phrase,
    is_magnet_lead,
    magnet_phrase,
    nonprofit_phrase,
)
from system_b.models import Lead, Signal

TODAY = date(2026, 9, 8)


def row(**kw):
    base = {
        "id": 1, "name": "Compatible Lands Foundation Inc", "domain": None,
        "signal_type": "nonprofit_grant_no_finance_officer",
        "evidence_text": "FY2024 Form 990: $24.6M total revenue; …",
        "source_url": "https://projects.propublica.org/nonprofits/organizations/271693939",
        "industry": "nonprofit", "niche": "charity_foundation",
        "insight": "Partner with the us military…", "headcount": 16,
        "headcount_band": "11-50", "city": "Pryor", "state": "OK", "score": 965.2,
        "signals": [{
            "type": "nonprofit_grant_no_finance_officer",
            "event_date": "2024-12-31T00:00:00", "date_confidence": "low",
            "evidence_text": "FY2024 Form 990: …",
            "source_url": "https://projects.propublica.org/nonprofits/organizations/271693939",
            "payload": {"ein": "27-1693930", "government_grant_share": 0.93},
        }],
    }
    base.update(kw)
    return base


# --- identity --------------------------------------------------------------


def test_a_government_identifier_beats_a_domain():
    """Two records for one charity can disagree about the website; they never
    disagree about the EIN."""
    assert _entity_id(row(domain="acme.org")) == "ein:27-1693930"


def test_a_crd_is_used_for_fund_advisers():
    r = row(signals=[{"type": "adv_no_fund_administrator", "payload": {"crd": "313945"}}])
    assert _entity_id(r) == "crd:313945"


def test_domain_is_the_fallback_identity():
    r = row(domain="Sixpenny.com", signals=[{"type": "x", "payload": {}}])
    assert _entity_id(r) == "domain:sixpenny.com"


def test_a_lead_with_no_identifier_at_all_is_none():
    assert _entity_id(row(domain=None, signals=[])) is None


def test_an_ein_lead_counts_as_findable_without_a_website():
    """Ranking on domain alone pushed every nonprofit and fund lead to the
    bottom as unfindable, when each carries a verifiable federal record."""
    lead = adapt_leadgen_lead(row(), today=TODAY)
    assert lead.domain is None
    assert lead.is_findable is True
    assert lead.identity == "ein:27-1693930"


def test_identity_falls_back_to_domain_on_a_hand_built_lead():
    lead = Lead(id="x", company="Acme", domain="Acme.com", signal_type="job_finance_lead")
    assert lead.identity == "domain:acme.com"


# --- freshness -------------------------------------------------------------


def mk(signal_type, event_date):
    return Lead(id="x", company="A", signal_type=signal_type,
                signals=[Signal(type=signal_type, date=event_date)])


def test_a_structural_signal_does_not_expire_like_a_job_post():
    """A 990's fiscal year end is two years back by construction; the job cap
    would delete every honest nonprofit lead."""
    old = mk("nonprofit_grant_no_finance_officer", "2023-12-31")
    assert _is_expired_job_lead(old, TODAY) is False


def test_an_undated_structural_lead_is_kept():
    """A storefront crawl has no event date — that says nothing about whether
    the arrangement still holds. An undated JOB post is dropped."""
    assert _is_expired_job_lead(mk("ecommerce_sku_load_no_finance_staff", None), TODAY) is False
    assert _is_expired_job_lead(mk("job_finance_lead", None), TODAY) is True


def test_a_stale_form_adv_does_expire():
    """Advisers file annually, so a filing 18 months old means a missed cycle
    and the fund counts can no longer be trusted."""
    assert _is_expired_job_lead(mk("adv_no_fund_administrator", "2026-06-01"), TODAY) is False
    assert _is_expired_job_lead(mk("adv_no_fund_administrator", "2024-01-01"), TODAY) is True


# --- the templated lines ---------------------------------------------------


def lead_with(signal_type, payload):
    return Lead(id="x", company="A", signal_type=signal_type,
                signals=[Signal(type=signal_type, payload=payload)])


def test_magnet_leads_are_recognised():
    for t in ("nonprofit_grant_no_finance_officer", "adv_no_fund_administrator",
              "ecommerce_sku_load_no_finance_staff"):
        assert is_magnet_lead(lead_with(t, {}))
    assert not is_magnet_lead(lead_with("job_finance_lead", {}))


def test_a_repeat_material_weakness_leads_the_nonprofit_line():
    line = nonprofit_phrase(lead_with("nonprofit_grant_no_finance_officer",
                                      {"fac_material_weakness": True,
                                       "fac_repeat_material_weakness": True}))
    assert line == "auditors flagged their controls, two years running"


def test_nonprofit_line_falls_back_to_the_grant_share():
    assert "mostly grant funded" in nonprofit_phrase(
        lead_with("nonprofit_grant_no_finance_officer", {"government_grant_share": 0.93}))
    assert "grant funded" in nonprofit_phrase(
        lead_with("nonprofit_grant_no_finance_officer", {"government_grant_share": 0.05}))


def test_no_line_states_a_dollar_figure():
    """The copy layer strips dollar amounts and flags the lead when it has to;
    the templates must never hand it one."""
    for lead in (
        lead_with("nonprofit_grant_no_finance_officer", {"government_grant_share": 0.9}),
        lead_with("adv_no_fund_administrator", {"unadmin_funds": 9}),
        lead_with("ecommerce_sku_load_no_finance_staff",
                  {"skus": 28004, "marketplaces": "amazon"}),
    ):
        assert "$" not in magnet_phrase(lead)


def test_funds_line_counts_funds_not_dollars():
    assert funds_phrase(lead_with("adv_no_fund_administrator", {"unadmin_funds": 9})) == \
        "9 funds, no outside administrator"
    assert "one fund" in funds_phrase(
        lead_with("adv_no_fund_administrator", {"unadmin_funds": 1}))
    assert "private funds" in funds_phrase(lead_with("adv_no_fund_administrator", {}))


def test_ecommerce_line_rounds_the_catalog_and_names_the_channels():
    """The catalog is crawled live, so an exact count can be wrong by the time
    the recipient checks — worse than no number."""
    line = ecommerce_phrase(lead_with("ecommerce_sku_load_no_finance_staff",
                                      {"skus": 28004, "marketplaces": "amazon,faire"}))
    assert "thousands of skus" in line
    # ONE marketplace, not an inventory of every channel — "shopify and amazon
    # and etsy and faire" is four words spent on one idea.
    assert "shopify + amazon" in line and "faire" not in line
    assert "28,004" not in line and "28004" not in line


def test_every_line_is_short_enough_for_an_80_word_email():
    for lead in (
        lead_with("nonprofit_grant_no_finance_officer", {"fac_repeat_material_weakness": True}),
        lead_with("adv_no_fund_administrator", {"unadmin_funds": 12}),
        lead_with("ecommerce_sku_load_no_finance_staff", {"skus": 2400, "marketplaces": "amazon"}),
    ):
        # Nine words. Three leads sit inside an email that should total under
        # 80, so at nine the leads cost ~27 words and leave room for the
        # opener and the ask. The old lines ran to twelve and spent half the
        # budget on the middle of the message.
        said = magnet_phrase(lead)
        assert len(said.split()) <= 9, f"{len(said.split())} words: {said}"


# --- the subject must not claim an event that did not happen ---------------


def test_a_magnet_gift_is_never_described_as_hiring():
    """The category logic was a two-way split — raised, or by elimination
    "hiring". That inverted the truth for a magnet lead: the whole signal is
    that the company posted NOTHING. A subject saying a named organization is
    "hiring finance leadership right now" is a false claim in the first line
    the recipient reads."""
    from system_b.gift.engine import _cfo_what_category
    for t in ("nonprofit_grant_no_finance_officer", "adv_no_fund_administrator",
              "ecommerce_sku_load_no_finance_staff"):
        assert _cfo_what_category([lead_with(t, {})]).startswith("unstaffed")


def test_each_magnet_gets_its_own_subject_words():
    """The three filters do NOT verify the same thing, so they must not share a
    phrase. Nonprofit and Ecommerce both confirm no finance staff; the FUNDS
    filter checks unadministered funds, investor counts and headcount, and says
    nothing about who works there — a 15-person adviser may employ a
    controller. "with nobody running finance" was false for every fund lead."""
    from system_b.copy.subject import _PLURAL_WHAT
    from system_b.gift.engine import _cfo_what_category
    got = {t: _cfo_what_category([lead_with(t, {})])
           for t in ("nonprofit_grant_no_finance_officer",
                     "adv_no_fund_administrator",
                     "ecommerce_sku_load_no_finance_staff")}
    assert len(set(got.values())) == 3, got
    words = {t: _PLURAL_WHAT[c] for t, c in got.items()}
    assert "nobody" not in words["adv_no_fund_administrator"]
    assert "administrator" in words["adv_no_fund_administrator"]
    assert "990" in words["nonprofit_grant_no_finance_officer"]


def test_job_leads_still_read_as_hiring():
    from system_b.gift.engine import _cfo_what_category
    assert _cfo_what_category([lead_with("job_fractional_cfo", {})]) == "hiring"


def test_a_mixed_gift_is_neither():
    from system_b.gift.engine import _cfo_what_category
    assert _cfo_what_category([lead_with("job_fractional_cfo", {}),
                               lead_with("adv_no_fund_administrator", {})]) == "mixed"


def test_the_engine_and_copy_agree_on_which_signals_are_magnets():
    """Two lists, deliberately kept apart so the engine has no copy dependency.
    They must not drift."""
    from system_b.copy.email import MAGNET_SIGNALS as COPY_SIGNALS
    from system_b.gift.engine import MAGNET_SIGNALS as ENGINE_SIGNALS
    assert COPY_SIGNALS == ENGINE_SIGNALS


# --- ranking ---------------------------------------------------------------


def test_the_magnet_score_orders_leads_within_a_signal_type():
    """Every lead from one magnet shares a signal_type, so without the score the
    first tiebreak that did any work was RECENCY — which ordered 29,000
    nonprofits by fiscal-year end and buried the 160 carrying a repeat
    material-weakness finding."""
    from system_b.gift.engine import sort_key
    strong = Lead(id="a", company="A", signal_type="nonprofit_grant_no_finance_officer",
                  score=965.2, entity_id="ein:1")
    weak = Lead(id="b", company="B", signal_type="nonprofit_grant_no_finance_officer",
                score=31.5, entity_id="ein:2")
    assert min([weak, strong], key=sort_key) is strong


def test_score_reaches_the_lead_from_the_inventory_row():
    assert adapt_leadgen_lead(row(score=965.2), today=TODAY).score == 965.2


# --- dates -----------------------------------------------------------------


def test_a_magnet_lead_line_carries_no_relative_date():
    """The date is when a DOCUMENT was filed, not when the situation arose.
    "runs 3 funds with no outside administrator, about a week ago" attaches it
    to the wrong noun and implies the arrangement is new."""
    from system_b.copy.email import _lead_line
    from system_b.niches.cfo import CFO_PACK
    lead = Lead(id="x", company="Acme Advisors", city="New York",
                signal_type="adv_no_fund_administrator", entity_id="crd:1",
                signals=[Signal(type="adv_no_fund_administrator", date="2026-09-01",
                                date_confidence="high", payload={"unadmin_funds": 3})])
    line, _flags = _lead_line(lead, TODAY, "city", pack=CFO_PACK)
    assert "ago" not in line
    assert "3 funds, no outside administrator" in line


# --- the DM must not claim a magnet company posted anything ----------------


def test_the_evergreen_dm_does_not_say_magnet_companies_posted_roles():
    """A magnet lead posted NOTHING — that is the entire signal — so
    "flags companies posting finance roles" was false about every company in
    the gift."""
    from system_b.copy.linkedin import _flags_what
    from system_b.gift.models import Gift
    from system_b.niches.cfo import CFO_PACK

    for t, expected in (
        ("nonprofit_grant_no_finance_officer", "990"),
        ("adv_no_fund_administrator", "administrator"),
        ("ecommerce_sku_load_no_finance_staff", "nobody in finance"),
    ):
        one = lead_with(t, {})
        g = Gift(leads=[one], best_lead=one, gift_size=1, all_niche=True,
                 geo_level="city", subject_shape="singular",
                 what_category="unstaffed", best_lead_level=1)
        said = _flags_what(g, CFO_PACK)
        assert "posting" not in said, said
        assert expected in said, said


def test_a_job_gift_still_says_posting():
    from system_b.copy.linkedin import _flags_what
    from system_b.gift.models import Gift
    from system_b.niches.cfo import CFO_PACK
    lead = lead_with("job_fractional_cfo", {})
    g = Gift(leads=[lead], best_lead=lead, gift_size=1, all_niche=True,
             geo_level="city", subject_shape="singular",
             what_category="hiring", best_lead_level=1)
    assert "posting" in _flags_what(g, CFO_PACK)


def test_the_funds_dm_does_not_borrow_the_no_finance_staff_claim():
    """The Funds filter checks unadministered funds, investor counts and
    headcount. It never verifies who works there."""
    from system_b.copy.linkedin import _flags_what
    from system_b.gift.models import Gift
    from system_b.niches.cfo import CFO_PACK
    lead = lead_with("adv_no_fund_administrator", {})
    g = Gift(leads=[lead], best_lead=lead, gift_size=1, all_niche=True,
             geo_level="city", subject_shape="singular",
             what_category="unstaffed_funds", best_lead_level=1)
    said = _flags_what(g, CFO_PACK)
    assert "nobody" not in said and "no finance" not in said


def test_the_retired_job_inventory_cannot_be_loaded_by_accident():
    """The old cfo/accounting/bookkeeping JSON is still on the blob and will
    never be refreshed again, so `--legacy-niche --pack cfo` would quietly
    build a gift from months-old job posts."""
    import pytest as _pytest

    from system_b.clients.inventory import snapshot_for_niche
    with _pytest.raises(RuntimeError, match="retired"):
        snapshot_for_niche("cfo", today=TODAY)


def test_the_it_packs_still_use_the_job_inventory():
    """Breach and IT signals were NOT retired — only the finance job posts."""
    from system_b.clients.inventory import RETIRED_JOB_NICHES
    for key in ("mssp", "msp", "cloud"):
        assert key not in RETIRED_JOB_NICHES


# --- the standing honesty audit --------------------------------------------


def test_no_sent_surface_makes_a_banned_or_false_claim():
    """One test over EVERY sent surface for all three magnets. These are the
    claims that were actually being made before this pass, each of which would
    have gone out to a real prospect:

      "hiring finance leadership right now"  — about companies that posted
                                               nothing; the whole signal is the
                                               absence of a posting
      "flags companies posting finance roles" — same, in the LinkedIn DM
      "referrals dried up and nothing        — borrowed social proof; the real
       replaced them"                          total is 30 emails, 2 replies
      "would 15 min work"                    — a calendar ask, against the rule
      ", about a week ago"                   — a relative date off a FILING
                                               date, implying the arrangement
                                               is new
    """
    import re

    from system_b.copy.email import _CTA_LINE, LEFT_FIELD
    from system_b.copy.linkedin import DM_2, _sign_off
    from system_b.copy.subject import _PLURAL_WHAT, _SINGULAR_WHAT
    from system_b.niches.cfo import CFO_PACK

    banned = [
        (r"referrals dried up|hearing the same thing", "borrowed social proof"),
        (r"15 min", "calendar ask, not a binary one"),
        (r"—", "em dash (house style)"),
    ]
    surfaces = {
        "cta": _CTA_LINE,
        "left_field": LEFT_FIELD,
        "dm_2": DM_2,
        "dm_signoff": _sign_off(CFO_PACK),
    }
    for name, text in surfaces.items():
        for pattern, why in banned:
            assert not re.search(pattern, text, re.IGNORECASE), f"{name}: {why}"

    # The magnet subject words must not borrow a claim their filter never made.
    assert "hiring" not in _PLURAL_WHAT["unstaffed_funds"]
    assert "nobody" not in _PLURAL_WHAT["unstaffed_funds"]
    for key in ("nonprofit_grant_no_finance_officer", "adv_no_fund_administrator",
                "ecommerce_sku_load_no_finance_staff"):
        assert "hiring" not in _SINGULAR_WHAT[key]
        assert "posted" not in _SINGULAR_WHAT[key]


# --- the backlog -----------------------------------------------------------


class _Research:
    candidate_phrases: ClassVar[list[str]] = ["we serve construction contractors"]


class _Prospect:
    match_param = ("industry", "construction")
    niche_phrase = "we serve construction contractors"


def test_a_firm_we_have_no_magnet_for_is_held_not_discarded():
    """A construction-focused firm is a perfectly good prospect; there is just
    no construction magnet yet. Throwing it away loses both the prospect and
    the evidence for what to build next."""
    from system_b.sequence.generate import _backlog_row
    row = {"firm_name": "Acme CFO", "email": "a@b.co", "website": "https://b.co",
           "city": "Denver", "state": "CO"}
    got = _backlog_row(row, _Research(), _Prospect())
    assert got["reason"] == "no_magnet"
    assert got["stated_vertical"] == "construction"
    assert got["stated_phrase"] == "we serve construction contractors"
    assert got["email"] == "a@b.co"


def test_a_firm_stating_no_vertical_is_marked_differently():
    """Nothing to match on, so no magnet could ever help them — they get the
    founder ask, not a gift. That is a different decision from 'build the
    construction magnet', so it must not share a bucket."""
    from system_b.sequence.generate import _backlog_row

    class _NoMatch:
        match_param = None
        niche_phrase = None

    got = _backlog_row({"firm_name": "X"}, _Research(), _NoMatch())
    assert got["reason"] == "no_vertical"


def test_a_vertical_we_DO_have_reads_as_inventory_dry():
    """Not a research problem — refresh or widen the inventory and they
    qualify. Confusing it with 'no magnet' would send you off building
    something that already exists."""
    from system_b.sequence.generate import _backlog_row

    class _Nonprofit:
        match_param = ("industry", "nonprofit")
        niche_phrase = "nonprofits"

    got = _backlog_row({"firm_name": "X"}, _Research(), _Nonprofit())
    assert got["reason"] == "inventory_dry"


# --- rung detection --------------------------------------------------------


def test_the_rung_is_read_off_their_own_service_words():
    """The rung decides one line of copy: "built this one for fractional cfos"
    vs "for bookkeepers". It used to be a single flag for a whole batch, which
    told every bookkeeper in a mixed export the wrong thing."""
    from system_b.research.rung import detect_rung
    cases = {
        "bookkeeping": "bookkeeping services, quickbooks and xero cleanup, "
                       "accounts payable, reconciliations, catch-up work",
        "accounting": "outsourced accounting and controller services, month-end "
                      "close, gaap financial statements, audit prep",
        "cfo": "fractional cfo services, fp&a, board reporting, scenario "
               "planning, investor reporting",
    }
    for expected, text in cases.items():
        got, evidence = detect_rung({"x": text})
        assert got == expected, f"{expected}: got {got} on {evidence}"
        assert evidence, expected


def test_a_firm_selling_everything_is_called_by_its_most_senior_rung():
    """Most firms sell all three. Calling a fractional CFO a "bookkeeper" reads
    as an insult and as proof nothing was read; the reverse reads as flattery.
    So a tie goes UP."""
    from system_b.research.rung import detect_rung
    got, _ = detect_rung({"x": "we do bookkeeping, quickbooks cleanup, accounts "
                               "payable, outsourced accounting, month-end close, "
                               "gaap financial statements, fractional cfo "
                               "services, fp&a and board reporting"})
    assert got == "cfo"


def test_a_single_stray_word_does_not_decide_the_rung():
    """One mention of "controller" on a page otherwise about bookkeeping is not
    a controller practice — and a site saying only "accounting firm" has not
    told us which of the three services it sells."""
    from system_b.research.rung import MIN_TERMS, detect_rung
    assert MIN_TERMS >= 2
    assert detect_rung({"x": "we are an accounting firm for small businesses"}) \
        == (None, [])


def test_an_unreadable_site_returns_no_rung_rather_than_guessing():
    from system_b.research.rung import detect_rung
    assert detect_rung({}) == (None, [])
    assert detect_rung({"x": "   "}) == (None, [])


# --- two charities with the same name --------------------------------------


def test_two_identically_named_charities_never_share_a_gift():
    """116 separate charities are called "Habitat For Humanity International
    Inc" — different cities, different EINs, genuinely different organizations.
    Identity-only dedup let two into one gift, where the reader sees the same
    name twice and concludes the list is broken."""
    from system_b.gift.engine import _same_company
    a = Lead(id="1", company="Habitat For Humanity International Inc",
             city="Denver", signal_type="nonprofit_grant_no_finance_officer",
             entity_id="ein:1")
    b = Lead(id="2", company="HABITAT FOR HUMANITY INTERNATIONAL, INC.",
             city="Alexandria", signal_type="nonprofit_grant_no_finance_officer",
             entity_id="ein:2")
    assert a.identity != b.identity          # genuinely different organizations
    assert _same_company(b, [a]) is True     # …but they must not both be shown


def test_genuinely_different_names_still_both_qualify():
    from system_b.gift.engine import _same_company
    a = Lead(id="1", company="Boulder Food Rescue", entity_id="ein:1",
             signal_type="nonprofit_grant_no_finance_officer")
    b = Lead(id="2", company="Proud Ground", entity_id="ein:2",
             signal_type="nonprofit_grant_no_finance_officer")
    assert _same_company(b, [a]) is False


def test_the_same_organization_is_still_caught_by_id():
    from system_b.gift.engine import _same_company
    a = Lead(id="1", company="Acme Fund", entity_id="crd:99",
             signal_type="adv_no_fund_administrator")
    b = Lead(id="2", company="Acme Fund LLC (dba Acme)", entity_id="crd:99",
             signal_type="adv_no_fund_administrator")
    assert _same_company(b, [a]) is True


def test_gate_b_fit_checks_are_capped_per_prospect():
    """The fit check is the only per-prospect LLM cost, and it multiplies: one
    call per swap attempt for EVERY candidate vertical a firm states. A firm
    naming six industries could cost 24 calls before a single email is
    written."""
    from system_b.gift.tiering import MAX_FIT_CANDIDATES
    assert 1 <= MAX_FIT_CANDIDATES <= 4


def test_the_funds_line_says_custody_when_the_filing_does():
    """Custody is the only dated obligation the funds magnet has: an adviser
    holding client assets owes a surprise annual exam by an independent
    accountant. Without it the line is only our inference that the work is hard."""
    plain = funds_phrase(lead_with("adv_no_fund_administrator", {"unadmin_funds": 9}))
    custody = funds_phrase(lead_with("adv_no_fund_administrator",
                                     {"unadmin_funds": 9, "has_custody": True}))
    assert plain == "9 funds, no outside administrator"
    assert custody == "9 funds, no administrator, holds client assets"


def test_no_custody_claim_when_the_column_was_absent():
    """None means the column was not on the form (exempt advisers file a
    shorter one) — never that they answered no."""
    said = funds_phrase(lead_with("adv_no_fund_administrator",
                                  {"unadmin_funds": 4, "has_custody": None}))
    assert "client assets" not in said


# --- the rung is required, not guessed -------------------------------------


def test_a_site_that_names_no_service_gets_no_rung():
    """Every prospect here is supposed to sell bookkeeping, accounting or
    fractional-CFO work. Guessing one would tell a stranger the tool was "built
    for fractional cfos" on no evidence — the same borrowed confidence the copy
    rules exist to prevent."""
    from system_b.research.rung import detect_rung
    assert detect_rung({"x": "we are a consultancy for growing businesses"}) == (None, [])
    assert detect_rung({}) == (None, [])


def test_a_readable_site_still_returns_its_rung():
    from system_b.research.rung import detect_rung
    got, evidence = detect_rung({"x": "bookkeeping, quickbooks cleanup, "
                                      "accounts payable, reconciliations"})
    assert got == "bookkeeping" and evidence


def test_a_no_rung_prospect_lands_in_the_backlog_with_that_reason():
    from system_b.sequence.generate import _backlog_row
    got = _backlog_row({"firm_name": "Vague Consulting", "email": "a@b.co"},
                       None, prospect=None, reason="no_rung")
    assert got["reason"] == "no_rung"
    assert got["email"] == "a@b.co"


def test_there_is_an_alarm_when_too_many_prospects_have_no_rung():
    """A handful of unreadable sites is normal. A large share means the LIST is
    wrong — an Apollo pull that swept in consultancies rather than finance
    practices."""
    from system_b.run import NO_RUNG_ALARM
    assert 0 < NO_RUNG_ALARM < 0.5


# --- MAGNET_INDUSTRY must agree with what the magnets actually emit ---------


def test_magnet_industry_matches_the_real_inventory():
    """The one map that has to track three other repos' `vertical.py`.

    It drifted once: the funds magnet was retagged `investment_management` and
    this map kept saying `fintech`, so a funds prospect with an empty gift was
    filed as `no_magnet` ("build this magnet next") when the magnet existed and
    the inventory was simply dry. Nothing raised — the value is only read for a
    backlog label, which is exactly why a rename can sit here unnoticed.

    Whenever an inventory file is on disk it is the ground truth, so assert
    against it. Skipped, not failed, when a magnet has not been pulled: the
    three refresh on their own cadence and CI has none of them.
    """
    import json

    from system_b.clients.inventory import MAGNET_INDUSTRY, MAGNETS

    inventory = Path(__file__).resolve().parent.parent / "data" / "inventory"
    checked = 0
    for key, filename in MAGNETS.items():
        path = inventory / filename
        if not path.exists():
            continue
        rows = json.loads(path.read_text()).get("leads") or []
        found = {r.get("industry") for r in rows if r.get("industry")}
        if not found:
            continue
        checked += 1
        assert found == {MAGNET_INDUSTRY[key]}, (
            f"{key}: inventory carries industry={found}, but MAGNET_INDUSTRY "
            f"says {MAGNET_INDUSTRY[key]!r}. Update the map to match the magnet."
        )
    if not checked:
        import pytest

        pytest.skip("no magnet inventory on disk")


# --- the framing line must not claim a magnet lead announced anything --------


def _magnet_gift(signal_type: str):
    from system_b.gift.models import Gift
    one = lead_with(signal_type, {})
    return Gift(leads=[one], best_lead=one, gift_size=1, all_niche=True,
                geo_level="city", subject_shape="singular",
                what_category="unstaffed", best_lead_level=1)


def test_the_framing_line_does_not_say_a_magnet_lead_posted_a_role():
    """The accounting and bookkeeping packs were written for job posts, and
    their opener still said so: "3 more BUILDING OUT THEIR FINANCE FUNCTION
    RIGHT NOW" / "LOOKING FOR BOOKKEEPING HELP RIGHT NOW".

    Both describe a company that advertised a role. A magnet lead advertised
    nothing -- that is the whole signal, and the reason a filing had to be read
    to find it. Measured on a real batch: an ADV gift opened with the accounting
    wording about firms whose only disclosed fact is that their funds have no
    third-party administrator.

    The subject line was fixed per magnet (`_MAGNET_WHAT`) and the body was not,
    so the two halves of the same email disagreed.
    """
    from system_b.copy.email import need_for
    from system_b.niches.accounting import _JOB_NEED as ACCT_NEED
    from system_b.niches.bookkeeping import _JOB_NEED as BOOK_NEED

    for signal_type in ("nonprofit_grant_no_finance_officer",
                        "adv_no_fund_administrator",
                        "ecommerce_sku_load_no_finance_staff"):
        gift = _magnet_gift(signal_type)
        for default in (ACCT_NEED, BOOK_NEED):
            said = need_for(gift, default=default)
            assert said != default, f"{signal_type} kept the job-post wording"
            assert "right now" not in said, (signal_type, said)
            assert "building out" not in said, (signal_type, said)
            assert "looking for" not in said, (signal_type, said)


def test_the_funds_framing_does_not_borrow_the_no_finance_staff_claim():
    """Funds verifies that a firm's funds have no third-party administrator. It
    says nothing about who works there, so it must not reach for the wording
    the other two magnets earned."""
    from system_b.copy.email import need_for
    said = need_for(_magnet_gift("adv_no_fund_administrator"), default="x")
    assert "nobody" not in said and "no finance" not in said, said
    assert "administrator" in said, said


def test_a_job_post_gift_keeps_its_own_wording():
    """The swap is for magnet gifts only. A company that really did post a
    finance role IS building one out, and that opener is the honest one."""
    from system_b.copy.email import need_for
    from system_b.gift.models import Gift
    lead = lead_with("job_fractional_cfo", {})
    gift = Gift(leads=[lead], best_lead=lead, gift_size=1, all_niche=True,
                geo_level="city", subject_shape="singular",
                what_category="hiring", best_lead_level=1)
    assert need_for(gift, default="building out their finance function right now") \
        == "building out their finance function right now"


def test_a_mixed_magnet_gift_falls_back_rather_than_picking_one():
    """No single clause is true of both an unstaffed nonprofit and a fund with
    no administrator, so a mixed gift keeps the pack's neutral wording instead
    of borrowing whichever magnet happened to sort first."""
    from system_b.copy.email import need_for
    from system_b.gift.models import Gift
    a = lead_with("nonprofit_grant_no_finance_officer", {})
    b = lead_with("adv_no_fund_administrator", {})
    gift = Gift(leads=[a, b], best_lead=a, gift_size=2, all_niche=True,
                geo_level="city", subject_shape="plural",
                what_category="unstaffed", best_lead_level=1)
    assert need_for(gift, default="NEUTRAL") == "NEUTRAL"
