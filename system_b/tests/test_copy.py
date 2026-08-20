"""M2 acceptance — the copy engine (spec Steps 4 & 5).

Covers every row of the 4b (plural subject), 4c (singular subject), 5a
(framing), and 5c (CTA) tables; the shared 5b left-field line; the 5e honesty
rules (date recompute/suppress, no dollar amounts, domainless + odd-city
flags); and a full Email #1 rendered for a niched and a generalist gift
built by the real M1 engine.

Run:  system_b/.venv/bin/python -m pytest system_b/tests/test_copy.py -q
"""

from __future__ import annotations

from datetime import date

from system_b.copy.email import (
    LEFT_FIELD,
    _cta,
    _framing,
    build_email_1,
)
from system_b.copy.honesty import relative_date, strip_dollar_amounts
from system_b.copy.lex import NICHE_DISPLAY, niche_display
from system_b.copy.subject import build_subject
from system_b.gift.engine import build_gift
from system_b.gift.models import Gift, Prospect
from system_b.tests.test_gift import FakeScraper, mk

TODAY = date(2026, 7, 8)


def assert_no_niche_claim(text: str) -> None:
    """No raw taxonomy token and no niche is ever CLAIMED (`[label] compan...`)
    anywhere in the given text (subject + body)."""
    low = text.lower()
    assert "_" not in low, "raw taxonomy token leaked into copy"
    for label in set(NICHE_DISPLAY.values()):
        assert f"{label} compan" not in low, f"niche '{label}' claimed in copy"


# --------------------------------------------------------------------------
# builders
# --------------------------------------------------------------------------

def P(*, niched=True, niche="healthcare", city="Denver", state="CO", **kw) -> Prospect:
    return Prospect(
        firm_name=kw.get("firm_name", "Test Firm"),
        city=city,
        state=state,
        classification="niched" if niched else "generalist",
        match_param=("industry", niche) if niched else None,
        niche_phrase=kw.get("niche_phrase"),
        niche_source=kw.get("niche_source", "site"),
        niche_exclusivity=kw.get("niche_exclusivity", "sole" if niched else "none"),
        first_name=kw.get("first_name", "alex"),
    )


def G(*, all_niche, geo, shape="plural", what="mixed", best_level=None,
      best_signal="funding_form_d", gift_size=3) -> Gift:
    bl = mk("best", best_signal)
    return Gift(
        leads=[bl], best_lead=bl, gift_size=gift_size,
        all_niche=all_niche, geo_level=geo, subject_shape=shape,
        what_category=what, best_lead_level=best_level,
    )


# --------------------------------------------------------------------------
# 4b — PLURAL subject table (6 WHO rows x 3 WHAT values)
# --------------------------------------------------------------------------

def test_4b_plural_who_what_table():
    p = P()  # niched healthcare, Denver CO
    assert build_subject(G(all_niche=True, geo="city", what="mixed"), p) == \
        "healthcare companies in denver that need finance help right now"
    assert build_subject(G(all_niche=True, geo="state", what="raised"), p) == \
        "healthcare companies in colorado that just raised"
    assert build_subject(G(all_niche=True, geo="none", what="hiring"), p) == \
        "healthcare companies hiring finance leadership right now"
    assert build_subject(G(all_niche=False, geo="city", what="raised"), p) == \
        "companies in denver that just raised"
    assert build_subject(G(all_niche=False, geo="state", what="hiring"), p) == \
        "colorado companies hiring finance leadership right now"
    assert build_subject(G(all_niche=False, geo="none", what="mixed"), p) == \
        "companies that need finance help right now"


# --------------------------------------------------------------------------
# 4c — SINGULAR subject table (5 match-level rows, niched + generalist)
# --------------------------------------------------------------------------

def test_4c_singular_who_table_niched():
    p = P()
    assert build_subject(G(all_niche=True, geo="city", shape="singular", best_level=1, best_signal="funding_form_d"), p) == \
        "a healthcare company in denver just raised"
    assert build_subject(G(all_niche=True, geo="state", shape="singular", best_level=2, best_signal="job_fractional_cfo"), p) == \
        "a healthcare company in colorado is hiring a fractional cfo"
    assert build_subject(G(all_niche=True, geo="none", shape="singular", best_level=3, best_signal="job_finance_lead"), p) == \
        "a healthcare company is hiring finance leadership"
    assert build_subject(G(all_niche=False, geo="city", shape="singular", best_level=4, best_signal="funding_form_d"), p) == \
        "a company in denver just raised"
    assert build_subject(G(all_niche=False, geo="state", shape="singular", best_level=5, best_signal="job_finance_lead"), p) == \
        "a colorado company is hiring finance leadership"


def test_4c_singular_who_table_generalist():
    p = P(niched=False)
    assert build_subject(G(all_niche=False, geo="city", shape="singular", best_level=1, best_signal="funding_form_d"), p) == \
        "a company in denver just raised"
    assert build_subject(G(all_niche=False, geo="state", shape="singular", best_level=2, best_signal="job_finance_lead"), p) == \
        "a colorado company is hiring finance leadership"


def test_4c_singular_geo_follows_gift_not_best_lead():
    """Regression: the singular subject's geo claim follows gift.geo_level, not
    the best lead. If the best lead matches the prospect's city (best_level=1) but
    the gift as a whole spans states (geo_level='none'), the subject must NOT claim
    the city — the body lists leads elsewhere. Previously it emitted
    'a healthcare company in denver ...' while showing out-of-city leads."""
    p = P()  # niched healthcare, Denver CO
    g = G(all_niche=True, geo="none", shape="singular", best_level=1,
          best_signal="job_fractional_cfo")
    assert build_subject(g, p) == "a healthcare company is hiring a fractional cfo"
    # generalist mismatch: same guard, no city leaked
    g2 = G(all_niche=False, geo="none", shape="singular", best_level=1,
           best_signal="job_finance_lead")
    assert build_subject(g2, P(niched=False)) == "a company is hiring finance leadership"





def test_one_phrasing_per_subject_key():
    """The WHAT tables used to hold equivalent phrasings rotated by a hash of the
    firm name. That bought variety nobody could act on and made the copy harder
    to reason about; the subject already varies through the WHO."""
    from system_b.copy.subject import _PLURAL_WHAT, _SINGULAR_WHAT

    for table in (_PLURAL_WHAT, _SINGULAR_WHAT):
        assert all(isinstance(v, str) for v in table.values())


def test_child_niche_keeps_its_word_in_subject():
    # #9: a mapped child niche must keep its label, not degrade to "a company"
    p = Prospect(firm_name="Legal CFO", city="Denver", state="CO",
                 classification="niched", match_param=("niche", "law_firm"))
    g = G(all_niche=True, geo="none", shape="singular", best_level=3, best_signal="job_fractional_cfo")
    assert build_subject(g, p) == "a law firm is hiring a fractional cfo"
    # firm_name -> the canonical subject variant (crc32 % 3 == 0), since this test
    # pins the exact WHAT wording; rotation itself is covered separately.
    p2 = Prospect(firm_name="Test Firm", city="Austin", state="TX",
                  classification="niched", match_param=("niche", "consulting"))
    g2 = G(all_niche=True, geo="city", shape="plural", what="hiring")
    assert build_subject(g2, p2) == "consulting firms in austin hiring finance leadership right now"


def test_4c_an_before_vowel():
    # niche starting with a vowel sound
    p_ec = P(niche="ecommerce_retail", state="TN")
    assert build_subject(G(all_niche=True, geo="state", shape="singular", best_level=2, best_signal="funding_form_d"), p_ec) == \
        "an ecommerce company in tennessee just raised"
    # state starting with a vowel sound (generalist L2)
    p_az = P(niched=False, state="AZ")
    assert build_subject(G(all_niche=False, geo="state", shape="singular", best_level=2, best_signal="job_finance_lead"), p_az) == \
        "an arizona company is hiring finance leadership"
    # vowel LETTER but consonant SOUND -> "a utah", never "an utah"
    p_ut = P(niched=False, state="UT")
    assert build_subject(G(all_niche=False, geo="state", shape="singular", best_level=2, best_signal="job_fractional_cfo"), p_ut) == \
        "a utah company is hiring a fractional cfo"


# --------------------------------------------------------------------------
# 5a — framing table (5 rows)
# --------------------------------------------------------------------------

def test_5a_framing_table():
    # TIER 1 — sole focus, still SOFT verb "work with" (never "focus on"). framing
    # uses the clean niche word, NOT the raw scraped phrase (#7/Change 3).
    p_site = P(niche_phrase="healthcare startups", niche_source="site", niche_exclusivity="sole")
    assert _framing(G(all_niche=True, geo="city"), p_site) == \
        "saw on your site you work with healthcare companies, so i pulled 3 more showing they need finance help:"

    # TIER 2 — one of several stated industries, verb "work with"; names ONLY
    # the one niche we're gifting for.
    p_multi = P(niche_phrase="WHO WE SERVE: healthcare, real estate, nonprofits",
                niche_source="site", niche_exclusivity="one_of_several")
    assert _framing(G(all_niche=True, geo="city"), p_multi) == \
        "noticed you work with healthcare companies, so i pulled 3 more showing they need finance help:"

    # client_list with NO nameable clients -> the soft, unnamed phrasing.
    p_list = P(niche_source="client_list")
    assert _framing(G(all_niche=True, geo="state"), p_list) == \
        "noticed you've worked with healthcare companies, so i pulled 3 more showing they need finance help:"

    # client_list WITH nameable clients -> name exactly two. This is what makes
    # a 2-client threshold honest: a citation, not an inference.
    # Ranked, not first-two: the name carrying an organizational marker leads.
    p_named = P(niche_source="client_list")
    p_named.client_names = ["MAPS", "Public Justice Foundation", "Prizmah"]
    assert _framing(G(all_niche=True, geo="state"), p_named) == \
        ("noticed you've worked with healthcare companies like Public Justice "
         "Foundation and MAPS, so i pulled 3 more showing they need finance help:")

    # one nameable client is not enough to name any -> falls back to unnamed.
    p_one = P(niche_source="client_list")
    p_one.client_names = ["MAPS"]
    assert _framing(G(all_niche=True, geo="state"), p_one) == \
        "noticed you've worked with healthcare companies, so i pulled 3 more showing they need finance help:"

    p = P()
    # the "based in [city]" opener is used ONLY when the leads are in the
    # prospect's city or state; geo none makes no location claim.
    assert _framing(G(all_niche=False, geo="city"), p) == \
        "saw you're based in denver, so i pulled 3 companies in denver showing they need finance help:"
    assert _framing(G(all_niche=False, geo="state"), p) == \
        "saw you're based in denver, so i pulled 3 colorado companies showing they need finance help:"
    assert _framing(G(all_niche=False, geo="none"), p) == \
        "i pulled 3 companies showing they need finance help:"

    # no city -> fall back to state in the intro
    p_nocity = P(city=None)
    assert _framing(G(all_niche=False, geo="state"), p_nocity) == \
        "saw you're based in colorado, so i pulled 3 colorado companies showing they need finance help:"
    # no location at all -> plain open, no personalization
    p_none = P(city=None, state=None)
    assert _framing(G(all_niche=False, geo="none"), p_none) == \
        "i pulled 3 companies showing they need finance help:"


# --------------------------------------------------------------------------
# 5c — CTA table (4 rows)
# --------------------------------------------------------------------------

def test_5c_cta_asks_for_the_call():
    """One ask, one goal: book 15 minutes. The old CTA branched on niche/geo and
    recruited subscribers to a free lead feed — the wrong yes. This one is
    deliberately niche/geo-agnostic: the opener and the leads already carried the
    personalization, and repeating it here made the close about the feed."""
    expected = (
        "still tuning it. would 15 min work to hear what would make it useful "
        "for you? happy to set it up to run for you either way :)"
    )
    p = P()
    for all_niche, geo in ((True, "city"), (False, "city"), (False, "state"), (False, "none")):
        assert _cta(G(all_niche=all_niche, geo=geo), p) == expected
    # it asks exactly once
    assert expected.count("?") == 1


# --------------------------------------------------------------------------
# 5b — left-field rotation
# --------------------------------------------------------------------------

def test_every_pack_shares_the_one_left_field_line():
    """It used to be per-pack, and the packs drifted: cfo opened "i'm an
    engineer" while accounting and bookkeeping opened "most bookkeepers i talk
    to". The engineer reveal is what stops a machine-built gift from reading as
    spray-and-pray, and nothing about it is CFO-specific, so every buyer gets
    it. The audience word is the only thing that varies."""
    from system_b.copy.email import left_field_for
    from system_b.niches.base import pack_for

    seen = {}
    for key in ("cfo", "accounting", "bookkeeping", "msp", "mssp", "cloud"):
        pack = pack_for(key)
        line = left_field_for(pack)
        assert line.startswith("i'm an engineer. built this one for ")
        assert pack.dm_audience in line
        assert "referrals dried up and nothing replaced them" in line
        assert line == line.lower() and "—" not in line
        seen[key] = line
    # every pack differs ONLY by the audience word
    assert len(set(seen.values())) == 6
    for key, line in seen.items():
        assert line.replace(pack_for(key).dm_audience, "X") == \
            LEFT_FIELD.format(audience="X")


def test_greeting_lowercased_but_company_names_kept_cased():
    # "hey dora," not "hey Dora," — lowercase prose, proper nouns intact.
    p = P(first_name="Dora")
    lead = mk("a", "job_finance_lead", industry="healthcare", city="Denver", state="CO",
              date="2026-07-05", company="Acme BioLabs", finance_grade="medium")
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, today=TODAY)
    assert draft.body.startswith("hey dora,\n\n")
    assert "hey Dora," not in draft.body
    # ...but a lead company name (a proper noun, added by code) keeps its casing
    assert "Acme BioLabs, denver:" in draft.body
    # missing first name still falls back to "there"
    assert build_email_1(g, P(first_name=None), today=TODAY).body.startswith("hey there,")


# --------------------------------------------------------------------------
# 5e — honesty: dates recomputed for high-confidence, suppressed for low
# --------------------------------------------------------------------------

def test_relative_date():
    assert relative_date("2026-07-08", TODAY) == "today"
    assert relative_date("2026-07-07", TODAY) == "yesterday"
    assert relative_date("2026-07-05", TODAY) == "3 days ago"
    assert relative_date("2026-07-01", TODAY) == "about a week ago"
    assert relative_date("2026-06-17", TODAY) == "about 3 weeks ago"


def test_5e_high_confidence_date_appended():
    # a high-confidence job lead gets a date on its templated hiring line.
    lead = mk("hc", "job_finance_lead", industry="healthcare", city="Denver", state="CO",
              date="2026-07-05", date_confidence="high", finance_grade="strong",
              evidence="Head of Finance")
    p = P()
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, today=TODAY)
    assert "is looking for a head of finance, 3 days ago" in draft.body


def test_no_raise_claim_is_ever_made():
    # The EDGAR sources that evidenced a raise were deleted, so the claim is
    # unprovable and no pack may make it. Guard against re-adding one.
    fd = mk("fd", "funding_form_d", industry="healthcare", city="Denver", state="CO", date="2026-07-05")
    p = P()
    body = build_email_1(build_gift(p, FakeScraper([fd])), p, today=TODAY).body
    assert "filed to raise" not in body
    assert "raised" not in body
    assert "$" not in body

    # a "double" lead (a hire that ALSO filed a raise) is the highest-intent gift:
    # its PRIMARY signal is the hire (kept from the LLM description), and the raise
    # is appended via the honest code template — mentioned, but never a $ figure.
    ds = mk("ds", "job_finance_lead", also_signal="funding_form_d",
            industry="healthcare", city="Denver", state="CO", date="2026-07-05",
            evidence="Senior Controller")
    gds = build_gift(p, FakeScraper([ds]))
    dds = build_email_1(gds, p, today=TODAY)
    assert "is looking for a senior controller" in dds.body  # the hire, templated
    assert "filed to raise" not in dds.body      # the raise is no longer claimed
    assert "$" not in dds.body


def test_5e_low_confidence_date_suppressed():
    # job_fractional_cfo from fractionaljobs.io => date_confidence low => NO date in copy
    lead = mk("cw", "job_fractional_cfo", industry="healthcare", city="Denver", state="CO",
              date="2026-07-05", date_confidence="low", domain=None, evidence="Fractional CFO")
    p = P()
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, today=TODAY)
    assert "is looking for a fractional cfo" in draft.body
    for banned in ("days ago", "weeks ago", "yesterday", "today", "a week ago"):
        assert banned not in draft.body


# --------------------------------------------------------------------------
# 5e — honesty: never a dollar amount for a raise
# --------------------------------------------------------------------------

def test_strip_dollar_amounts():
    assert strip_dollar_amounts("raised $2M in seed") == ("raised in seed", True)
    assert strip_dollar_amounts("closed a $1,500,000 round") == ("closed a round", True)
    assert strip_dollar_amounts("raised 500k") == ("raised", True)
    assert strip_dollar_amounts("just raised") == ("just raised", False)


def test_breach_line_is_templated_and_carries_no_specifics():
    # EVERY line is now code-templated, so no figure or breach detail can reach
    # copy from source data at all — the $-strip is a dead-code safety net
    # rather than the thing doing the work.
    lead = mk("f", "breach_disclosed", city="Denver", state="CO",
              date="2026-07-05", date_confidence="high")
    p = P(niched=False)
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, today=TODAY)
    assert "$" not in draft.body
    assert "200k" not in draft.body
    assert "disclosed a security incident" in draft.body


def test_job_line_strips_salary_and_metadata():
    # a job title with '| location | $salary' becomes a clean 'is looking for a
    # {role}' — no pipes, no dollar figure (the goofy-line fix).
    lead = mk("s", "job_finance_lead", industry="healthcare", city="Denver", state="CO",
              date="2026-07-05", finance_grade="medium",
              evidence="Property Accounting Manager | Remote | $90,000/yr DOE")
    p = P()
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, today=TODAY)
    assert "is looking for a property accounting manager" in draft.body
    assert "|" not in draft.body and "$" not in draft.body and "90,000" not in draft.body


# --------------------------------------------------------------------------
# 5e — honesty: domainless + odd-city funding flags
# --------------------------------------------------------------------------

def test_lead_description_forced_lowercase_company_kept_cased():
    # a job lead's hiring line is templated from its evidence title, lowercased
    lead = mk("f", "job_finance_lead", industry="healthcare", city="Denver", state="CO",
              date="2026-07-05", company="Acme BioLabs", finance_grade="medium",
              evidence="VP of Finance")
    p = P()
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, today=TODAY)
    # the role is lowercased in the voice...
    assert "is looking for a vp of finance" in draft.body
    assert "VP of Finance" not in draft.body
    # ...but the company name (added by code) keeps its real casing
    assert "Acme BioLabs, denver:" in draft.body


def test_fix_articles_in_lead_lines():
    # a/an corrected in the templated hiring line (#11): "a assistant" -> "an assistant"
    lead = mk("g", "job_finance_lead", industry="healthcare", city="Denver", state="CO",
              date="2026-07-05", finance_grade="medium", evidence="Assistant Controller")
    p = P()
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, today=TODAY)
    assert "is looking for an assistant controller" in draft.body


def test_5e_domainless_flag():
    lead = mk("dl", "job_finance_lead", city="Denver", state="CO", domain=None, finance_grade="medium")
    p = P(niched=False)
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, today=TODAY)
    assert any("domainless" in f for f in draft.flags)


def test_registered_address_flag_is_dead_with_funding_gone():
    # The flag existed because a Form D city is a registered address, not HQ.
    # No funding claim is made now, so it must not fire (and its lead should
    # not be reachable at all once the inventory stops carrying funding).
    lead = mk("fc", "funding_form_d", city="Denver", state="CO")
    p = P(niched=False)
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, today=TODAY)
    assert not any("registered address" in f for f in draft.flags)


# --------------------------------------------------------------------------
# Full Email #1 — niched (Example 1) via the real M1 engine
# --------------------------------------------------------------------------

def test_full_email_niched_example_1():
    p = P(niche_phrase="healthcare startups", first_name="dana")
    leads = [
        mk("h1", "job_junior_finance", industry="healthcare", city="Denver", state="CO", date="2026-07-05", company="Acme Bio", evidence="Bookkeeper"),
        mk("h2", "job_junior_finance", industry="healthcare", city="Denver", state="CO", date="2026-07-04", company="Nimbus Rx", evidence="Staff Accountant"),
        mk("h3", "job_finance_lead", industry="healthcare", city="Denver", state="CO", date="2026-07-03", company="Vitals Co", finance_grade="medium", evidence="Controller"),
    ]
    g = build_gift(p, FakeScraper(leads))
    draft = build_email_1(g, p, today=TODAY)

    assert draft.subject == "healthcare companies in denver hiring finance leadership right now"
    assert draft.body.startswith("hey dana,\n\n")
    assert "saw on your site you work with healthcare companies, so i pulled 3 more" in draft.body
    # a finance-lead hire (rank 1) outranks the junior-finance leads (rank 2)
    # in the within-level re-sort, so the finance-lead line is #1.
    assert "1. Vitals Co, denver: is looking for a controller, 5 days ago" in draft.body
    assert "2. Acme Bio, denver: is looking for a bookkeeper, 3 days ago" in draft.body
    assert "3. Nimbus Rx, denver: is looking for a staff accountant, 4 days ago" in draft.body
    assert LEFT_FIELD[0] in draft.body
    assert "would 15 min work to hear what would make it useful for you?" in draft.body
    assert draft.body.endswith("best,\nishaan")
    # no funding claim means no registered-address caveat
    assert not any("registered address" in f for f in draft.flags)


# --------------------------------------------------------------------------
# Full Email #1 — generalist (Example 8) via the real M1 engine
# --------------------------------------------------------------------------

def test_full_email_generalist_example_8():
    p = P(niched=False, city="Miami", state="FL", first_name="sam")
    leads = [
        mk("m1", "job_finance_lead", city="Miami", state="FL", date="2026-07-06", company="Palm Freight", finance_grade="strong", evidence="VP of Finance"),
        mk("m2", "job_finance_lead", city="Miami", state="FL", date="2026-07-05", company="Bay Foods", finance_grade="medium", evidence="Controller"),
    ]
    g = build_gift(p, FakeScraper(leads))
    draft = build_email_1(g, p, today=TODAY)

    assert draft.subject == "companies in miami hiring finance leadership right now"
    assert "saw you're based in miami, so i pulled 2 companies in miami" in draft.body
    assert "1. Palm Freight, miami: is looking for a vp of finance, 2 days ago" in draft.body
    assert "2. Bay Foods, miami: is looking for a controller, 3 days ago" in draft.body
    assert "would 15 min work to hear what would make it useful for you?" in draft.body
    # ZERO niche words anywhere — subject AND body — for a generalist
    assert_no_niche_claim(draft.subject + "\n" + draft.body)


# --------------------------------------------------------------------------
# Single-lead gift folds in (no numbering); job_fractional_cfo date suppressed (Ex 5/7)
# --------------------------------------------------------------------------

def test_single_lead_not_numbered():
    p = P(niche="ecommerce_retail", city="Nashville", state="TN", first_name="lee")
    lead = mk("mem", "job_finance_lead", industry="ecommerce_retail", city="Memphis", state="TN", date="2026-07-05", company="River Goods", evidence="Controller")
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, today=TODAY)
    assert g.gift_size == 1
    assert "River Goods, memphis: is looking for a controller, 3 days ago" in draft.body
    assert "1. River Goods" not in draft.body        # single lead is not numbered


def test_niche_display_never_returns_a_raw_token():
    assert niche_display(("niche", "dental")) == "dental"           # curated child
    assert niche_display(("industry", "software_saas")) == "software"  # never "software_saas"
    assert niche_display(("niche", "pet_grooming")) is None          # unmapped -> None
    assert niche_display(("industry", "unknown")) is None
    assert niche_display(None) is None


def test_unmapped_niche_renders_generalist_not_a_token():
    # A niched prospect whose taxonomy token has no curated label. The gift is
    # genuinely all-niche (leads matched by the token), but copy must fall back
    # to generalist rather than print "pet_grooming"/"pet grooming".
    p = Prospect(
        firm_name="Test Firm", city="Denver", state="CO",   # crc32 % 3 == 0 -> canonical WHAT
        classification="niched", match_param=("niche", "pet_grooming"),
        niche_phrase="pet grooming shops", niche_source="site", first_name="jo",
    )
    leads = [
        mk("p1", "funding_form_d", niche="pet_grooming", city="Denver", state="CO", date="2026-07-05", company="Fluff Co"),
        mk("p2", "job_finance_lead", niche="pet_grooming", city="Denver", state="CO", date="2026-07-04", company="Shear Joy", finance_grade="medium"),
    ]
    g = build_gift(p, FakeScraper(leads))
    assert g.all_niche is True                       # gift really is on-niche...
    draft = build_email_1(g, p, today=TODAY)

    # ...but the copy is generalist, because the token has no label.
    assert draft.subject == "companies in denver that need finance help right now"
    assert "saw you're based in denver, so i pulled 2 companies in denver" in draft.body
    assert "would 15 min work to hear what would make it useful for you?" in draft.body
    for banned in ("pet_grooming", "pet grooming", "pet grooming shops"):
        assert banned not in (draft.subject + "\n" + draft.body)
    assert_no_niche_claim(draft.subject + "\n" + draft.body)


def test_cfo_gift_no_longer_flags_every_card():
    p = P(niched=False, city="Chicago", state="IL", first_name="ray")
    leads = [
        mk("cfo", "job_fractional_cfo", city="Chicago", state="IL", date="2026-06-20", date_confidence="low", domain=None, company="Loop Labs"),
        mk("c1", "funding_form_d", city="Chicago", state="IL", date="2026-07-05", company="Windy Co"),
        mk("c2", "job_finance_lead", city="Chicago", state="IL", date="2026-07-04", company="Deep Dish Inc", finance_grade="medium"),
    ]
    g = build_gift(p, FakeScraper(leads))
    draft = build_email_1(g, p, today=TODAY)
    assert draft.subject == "a company in chicago is hiring a fractional cfo"
    # The blanket "confirm it's still live" flag is retired: it fired on 21 of
    # 23 real prospects and buried the flags that needed a decision. The
    # MAX_JOB_LEAD_AGE_DAYS cap enforces posting freshness in code instead.
    assert not any("confirm it's still live" in f for f in draft.flags)
    assert any("domainless" in f for f in draft.flags)


# --- job title: board metadata never reaches copy ---------------------------

from system_b.copy.email import _clean_role, _client_names_phrase, job_phrase  # noqa: E402


def test_role_drops_trailing_board_metadata():
    """Every input is a real inventory title. The city especially: the line
    already prints the company's city, so "financial controller - savannah, ga"
    said savannah twice."""
    cases = {
        "Financial Controller - Savannah, GA": "Financial Controller",
        "Assistant Controller - Hybrid (Austin)": "Assistant Controller",
        "CPA Finance Manager - 75% Remote": "CPA Finance Manager",
        "Senior Accountant - Onsite/Hybrid role": "Senior Accountant",
        "Senior Accountant (Full-Time)": "Senior Accountant",
        "Part-Time Interim Chief Financial Officer (CFO)": "Part-Time Interim Chief Financial Officer",
        "Division Controller for Schools Division (Full-Time, Remote)": "Division Controller for Schools Division",
        "Chief Financial Officer - Healthcare Industry (In Office) (Phoenix)":
            "Chief Financial Officer - Healthcare Industry",
    }
    for raw, want in cases.items():
        assert _clean_role(raw) == want, raw


def test_role_keeps_a_dash_segment_that_describes_the_role():
    """A dash segment is usually the role itself. Only a place or a work
    arrangement gets cut."""
    for raw in (
        "Assistant Controller - Manufacturing",
        "Accounting Manager - Billing & Operations",
        "Senior Project Manager - FP&A",
        "Controller — Medical AI Startup",
        "Finance Manager - Security Services",
        "Accounting Manager - Multi-State/Multi-Entity",
        "Controller - Finance, hr",     # lowercase 'hr' is not a state
    ):
        assert _clean_role(raw) == raw, raw


def test_role_that_is_only_metadata_degrades_to_is_hiring():
    lead = mk("x", "job_finance_lead", evidence="(Remote)")
    assert job_phrase(lead) == "is hiring"


def test_lead_line_shows_the_fractional_word_the_title_hid():
    lead = mk("f1", "job_fractional_cfo", company="Acme", evidence="Chief Financial Officer")
    lead.role_qualifier = "interim"
    assert job_phrase(lead) == "is looking for an interim cfo"


def test_lead_line_does_not_double_up_the_qualifier():
    lead = mk("f2", "job_fractional_cfo", company="Acme",
              evidence="Fractional Chief Financial Officer")
    lead.role_qualifier = "fractional"
    assert job_phrase(lead) == "is looking for a fractional cfo"


def test_client_choice_prefers_an_organization_over_a_brand():
    """Taking whatever came back first put "Humans of New York" — a famous brand
    — in front of a prospect as a claimed client while Public Justice Foundation
    sat unused."""
    p = P(niche_source="client_list")
    p.client_names = [
        "The Nemasket Group, Inc.", "Humans of New York",
        "Multidisciplinary Association for Psychedelic Studies (MAPS)",
        "Public Justice Foundation", "Round Canopy Parachuting Team - USA",
    ]
    # the legal suffix is stripped where the name is SPOKEN (nobody says "Inc.")
    assert _client_names_phrase(p) == "The Nemasket Group and Public Justice Foundation"


def test_client_choice_falls_back_when_nothing_looks_like_an_org():
    p = P(niche_source="client_list")
    p.client_names = ["Humans of New York", "Dear New York"]
    assert _client_names_phrase(p) == "Dear New York and Humans of New York"  # shortest first


# --- speech, not filings ----------------------------------------------------

def test_titles_people_say_as_initials_are_abbreviated():
    """A job board writes "Chief Financial Officer". Nobody says that out loud to
    another finance person, and the expanded form in a casual lowercase line is a
    tell that the sentence was assembled rather than written."""
    from system_b.copy.email import job_phrase

    cases = {
        "Chief Financial Officer": "is looking for a cfo",
        "VP of Finance": "is looking for a vp of finance",
        "Chief Information Security Officer": "is looking for a ciso",
        # longest-first: CISO must not be half-matched into "chief information officer"
        "Chief Information Officer": "is looking for a cio",
    }
    for title, expected in cases.items():
        assert job_phrase(mk("l", "job_finance_lead", evidence=title)) == expected


def test_spelled_out_term_does_not_keep_its_own_initials_in_parens():
    """"head of financial planning & analysis (fp&a)" abbreviates to
    "head of fp&a (fp&a)" unless the redundant parenthetical is dropped."""
    from system_b.copy.email import job_phrase

    lead = mk("l", "job_finance_lead",
              evidence="Head of Financial Planning & Analysis (FP&A)")
    assert job_phrase(lead) == "is looking for a head of fp&a"


def test_chief_accounting_officer_is_left_spelled_out():
    """CFO and CISO are universally spoken as initials. CAO is not, so expanding
    it is the honest default."""
    from system_b.copy.email import job_phrase

    lead = mk("l", "job_finance_lead", evidence="Chief Accounting Officer")
    assert "cao" not in job_phrase(lead)


def test_legal_suffixes_are_dropped_where_the_name_is_spoken():
    from system_b.copy.lex import spoken_name

    assert spoken_name("Antilles Power Depot, Inc.") == "Antilles Power Depot"
    assert spoken_name("Gwen Fonarow LLC") == "Gwen Fonarow"
    assert spoken_name("The Nemasket Group, Inc.") == "The Nemasket Group"
    # "& Co." is how those firms are actually known — stripping it reads wrong
    assert spoken_name("DP Mende & Co.") == "DP Mende & Co."
    # only the TRAILING suffix, and never down to nothing
    assert spoken_name("BooGoo Inc. (BGB)") == "BooGoo Inc. (BGB)"
    assert spoken_name("LLC") == "LLC"


def test_lead_line_says_the_company_the_way_a_person_would():
    from system_b.copy.email import _lead_line
    from system_b.niches.base import default_pack

    lead = mk("l1", "job_finance_lead", city="Denver", state="CO",
              company="Antilles Power Depot, Inc.", evidence="Chief Financial Officer")
    line, _ = _lead_line(lead, TODAY, "none", pack=default_pack())
    assert line.startswith("Antilles Power Depot, denver: is looking for a cfo")
    assert "Inc." not in line


def test_niches_that_are_not_companies_are_not_called_companies():
    """"nonprofit companies" is the fastest way to sound like a slot got filled.
    A nonprofit is not a company; a law firm is not a "legal company"."""
    from system_b.copy.lex import niche_noun

    assert niche_noun("nonprofit") == "nonprofits"
    assert niche_noun("nonprofit", 1) == "nonprofit"
    assert niche_noun("legal") == "law firms"
    assert niche_noun("dental") == "dental practices"
    assert niche_noun("restaurant") == "restaurants"
    # anything not listed keeps the default, so this stays a short exception list
    assert niche_noun("healthcare") == "healthcare companies"
    assert niche_noun("healthcare", 1) == "healthcare company"
    # a geography reads correctly through the same default
    assert niche_noun("atlanta") == "atlanta companies"


def test_nonprofit_framing_and_subject_read_as_speech():
    # "Test Firm" pins the canonical WHAT variant (crc32 % 3 == 0); rotation
    # itself is covered separately.
    p = Prospect(firm_name="Test Firm", city="Denver", state="CO",
                 classification="niched", match_param=("industry", "nonprofit"),
                 niche_exclusivity="one_of_several")
    g = G(all_niche=True, geo="none", shape="plural", what="hiring")
    assert "nonprofits" in _framing(g, p)
    assert "nonprofit companies" not in _framing(g, p)
    assert build_subject(g, p) == "nonprofits hiring finance leadership right now"


# --------------------------------------------------------------------------
# the revenue lever belongs to EVERY pack, not just cfo
# --------------------------------------------------------------------------

def test_revenue_opener_fires_for_every_pack():
    """`_revenue_framing` was reachable only from `_framing` (the cfo pack), so
    bookkeeping / accounting / msp prospects who stated a revenue range still
    opened on "saw you're based in denver" — an Apollo merge field. Worse, the
    review gate's `_personalization` ranked those cards for a lever the copy
    never pulled, and that ranking IS the CSV row order the operator works down
    to the LinkedIn cap."""
    from system_b.niches.base import pack_for

    p = P(niched=False, city="Denver", state="CO")
    p.client_revenue = (2_000_000.0, 10_000_000.0)
    gift = G(all_niche=False, geo="city")

    for key in ("cfo", "accounting", "bookkeeping", "msp", "mssp", "cloud"):
        line = pack_for(key).framing(gift, p)
        assert line.startswith("saw you work with $2m-$10m companies."), f"{key}: {line}"
        assert "denver" in line, f"{key}: {line}"


def test_revenue_opener_keeps_each_packs_own_words():
    """The clause after the gift is the pack's, not a hardcoded cfo one."""
    from system_b.niches.base import pack_for

    p = P(niched=False, city="Denver", state="CO")
    p.client_revenue = (1_000_000.0, None)
    gift = G(all_niche=False, geo="city")

    assert "bookkeeping help" in pack_for("bookkeeping").framing(gift, p)
    assert "finance function" in pack_for("accounting").framing(gift, p)
    assert "it help" in pack_for("msp").framing(gift, p)
    assert "need finance help" in pack_for("cfo").framing(gift, p)


def test_client_list_opener_still_skips_revenue_in_every_pack():
    """A client-list opener already names two real clients; spending words on a
    revenue range on top of that is the one case where the lever stays off."""
    from system_b.niches.base import pack_for

    p = P(niched=True, niche="healthcare", niche_source="client_list")
    p.client_revenue = (2_000_000.0, 10_000_000.0)
    gift = G(all_niche=True, geo="city")

    for key in ("cfo", "accounting", "bookkeeping", "msp"):
        line = pack_for(key).framing(gift, p)
        assert "$2m" not in line, f"{key}: {line}"
        assert line.startswith("noticed you've worked with"), f"{key}: {line}"


def test_the_printed_role_comes_from_the_signal_the_subject_names():
    """A company with several postings carries several signals, and leadgen sets
    `signal_type` from the strongest — not necessarily `signals[0]`. Reading
    signals[0] let the subject describe one posting while the body described
    another: Jobtailor's subject said "is hiring a fractional cfo" over a line
    reading "is looking for a vp of finance", a different full-time posting."""
    from system_b.copy.email import job_phrase
    from system_b.models import Lead, Signal

    lead = Lead(
        id="x", company="Jobtailor", domain="jobtailor.com",
        signal_type="job_fractional_cfo",
        signals=[
            Signal(type="job_finance_lead", date="2026-08-01",
                   plain_words_description="VP of Finance (San Francisco)"),
            Signal(type="job_fractional_cfo", date="2026-08-18",
                   plain_words_description="Interim Chief Financial Officer"),
        ],
    )
    assert lead.headline_signal.type == "job_fractional_cfo"
    assert job_phrase(lead) == "is looking for an interim cfo"


def test_headline_signal_falls_back_when_no_type_matches():
    from system_b.models import Lead, Signal

    lead = Lead(
        id="y", company="Odd Co", signal_type="job_security",
        signals=[Signal(type="job_it_support", plain_words_description="Help Desk Tech")],
    )
    assert lead.headline_signal.plain_words_description == "Help Desk Tech"
