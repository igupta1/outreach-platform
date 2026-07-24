"""M2 acceptance — the copy engine (spec Steps 4 & 5).

Covers every row of the 4b (plural subject), 4c (singular subject), 5a
(framing), and 5c (CTA) tables; the 5b left-field rotation; the 5e honesty
rules (date recompute/suppress, no dollar amounts, domainless + odd-city
flags); and a full Email #1 rendered for a niched and a generalist gift
built by the real M1 engine.

Run:  system_b/.venv/bin/python -m pytest system_b/tests/test_copy.py -q
"""

from __future__ import annotations

from datetime import date

from system_b.copy.email import (
    LEFT_FIELD,
    LEFT_FIELD_LABELS,
    _cta,
    _framing,
    build_email_1,
    rotation_for,
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


def test_4c_singular_what_rotates_per_prospect():
    """The singular WHAT rotates deterministically per prospect (crc32 of firm),
    so a domain isn't sending one identical subject repeatedly — but always emits
    an approved, equivalent phrasing. 'Test Firm' stays on the canonical wording."""
    from system_b.copy.subject import _SINGULAR_WHAT
    g = G(all_niche=False, geo="state", shape="singular", best_level=2,
          best_signal="job_fractional_cfo")
    # pinned fixture -> canonical variant 0
    assert build_subject(g, P()).endswith("is hiring a fractional cfo")
    approved = _SINGULAR_WHAT["job_fractional_cfo"]
    seen = set()
    for name in ["Acme LLC", "Beta Co", "Gamma Inc", "Delta Group", "Epsilon Partners"]:
        s = build_subject(g, P(firm_name=name))
        assert s == build_subject(g, P(firm_name=name))     # deterministic
        assert any(s.endswith(v) for v in approved)         # only approved wording
        seen.add(next(v for v in approved if s.endswith(v)))
    assert len(seen) >= 2, "rotation should vary the subject across prospects"


def test_build_who_what_rotates_tuple_but_not_string():
    """The non-CFO packs' subject WHAT rotates when given a tuple of equivalent
    phrasings (per-prospect), and is left verbatim when given a plain string."""
    from system_b.copy.subject import build_who_what
    g = G(all_niche=False, geo="state", shape="singular", best_level=2,
          best_signal="job_finance_lead")
    variants = ("is hiring finance help", "is building out its finance function",
                "is bringing on finance help")
    # plain string -> used verbatim (back-compat)
    assert build_who_what(g, P(), singular_what="is hiring finance help",
                          plural_what="x") == "a colorado company is hiring finance help"
    # tuple -> rotates, always an approved phrasing, deterministic, and varies
    seen = set()
    for name in ["Acme LLC", "Beta Co", "Gamma Inc", "Delta Group", "Epsilon Partners"]:
        s = build_who_what(g, P(firm_name=name), singular_what=variants, plural_what="x")
        assert any(s.endswith(v) for v in variants)
        seen.add(next(v for v in variants if s.endswith(v)))
    assert len(seen) >= 2


def test_child_niche_keeps_its_word_in_subject():
    # #9: a mapped child niche must keep its label, not degrade to "a company"
    p = Prospect(firm_name="Legal CFO", city="Denver", state="CO",
                 classification="niched", match_param=("niche", "law_firm"))
    g = G(all_niche=True, geo="none", shape="singular", best_level=3, best_signal="job_fractional_cfo")
    assert build_subject(g, p) == "a legal company is hiring a fractional cfo"
    p2 = Prospect(firm_name="Consult CFO", city="Austin", state="TX",
                  classification="niched", match_param=("niche", "consulting"))
    g2 = G(all_niche=True, geo="city", shape="plural", what="hiring")
    assert build_subject(g2, p2) == "consulting companies in austin hiring finance leadership right now"


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
        "saw on your site you work with healthcare, so i pulled 3 healthcare companies showing they need finance help right now:"

    # TIER 2 — one of several stated industries, verb "work with"; names ONLY
    # the one niche we're gifting for.
    p_multi = P(niche_phrase="WHO WE SERVE: healthcare, real estate, nonprofits",
                niche_source="site", niche_exclusivity="one_of_several")
    assert _framing(G(all_niche=True, geo="city"), p_multi) == \
        "noticed you work with healthcare companies, so i pulled 3 more showing they need finance help right now:"

    p_list = P(niche_source="client_list")
    assert _framing(G(all_niche=True, geo="state"), p_list) == \
        "noticed you've worked with a bunch of healthcare companies, so i pulled 3 more showing they need finance help right now:"

    p = P()
    # the "based in [city]" opener is used ONLY when the leads are in the
    # prospect's city or state; geo none makes no location claim.
    assert _framing(G(all_niche=False, geo="city"), p) == \
        "saw you're based in denver, so i pulled 3 companies in denver showing they need finance help right now:"
    assert _framing(G(all_niche=False, geo="state"), p) == \
        "saw you're based in denver, so i pulled 3 colorado companies showing they need finance help right now:"
    assert _framing(G(all_niche=False, geo="none"), p) == \
        "i pulled 3 companies showing they need finance help right now:"

    # no city -> fall back to state in the intro
    p_nocity = P(city=None)
    assert _framing(G(all_niche=False, geo="state"), p_nocity) == \
        "saw you're based in colorado, so i pulled 3 colorado companies showing they need finance help right now:"
    # no location at all -> plain open, no personalization
    p_none = P(city=None, state=None)
    assert _framing(G(all_niche=False, geo="none"), p_none) == \
        "i pulled 3 companies showing they need finance help right now:"


# --------------------------------------------------------------------------
# 5c — CTA table (4 rows)
# --------------------------------------------------------------------------

def test_5c_cta_table():
    p = P()
    assert _cta(G(all_niche=True, geo="city"), p) == \
        "want me to keep an eye out for healthcare ones and send them your way?"
    assert _cta(G(all_niche=False, geo="city"), p) == \
        "want me to keep an eye out for denver ones and send them your way?"
    assert _cta(G(all_niche=False, geo="state"), p) == \
        "want me to keep an eye out for colorado ones and send them your way?"
    assert _cta(G(all_niche=False, geo="none"), p) == \
        "want me to keep an eye out and send new ones your way?"


# --------------------------------------------------------------------------
# 5b — left-field rotation
# --------------------------------------------------------------------------

def test_5b_left_field_rotation():
    # five variants (A-E), all distinct, house style: all lowercase, no em dashes
    assert len(LEFT_FIELD) == 5
    assert len(set(LEFT_FIELD)) == 5
    assert LEFT_FIELD_LABELS == ["A", "B", "C", "D", "E"]
    assert LEFT_FIELD[0] == (
        "most fractional cfos i talk to say referrals were great, till they "
        "dried up. built this to catch companies the day they show a "
        "finance-need signal."
    )
    assert all(line == line.lower() for line in LEFT_FIELD)
    assert not any("—" in line for line in LEFT_FIELD)
    p = P(firm_name="Acme CFO")
    # deterministic + in range
    assert rotation_for(p) == rotation_for(P(firm_name="Acme CFO"))
    assert 0 <= rotation_for(p) < len(LEFT_FIELD)
    # explicit rotation selects the exact line AND logs its label (A-E) on the draft
    for k in range(len(LEFT_FIELD)):
        g = build_gift(P(), FakeScraper([mk("a", "funding_form_d", industry="healthcare", city="Denver", state="CO")]))
        draft = build_email_1(g, P(), {"a": "closed a round"}, today=TODAY, rotation=k)
        assert LEFT_FIELD[k] in draft.body
        assert draft.left_field_variant == LEFT_FIELD_LABELS[k]


def test_greeting_lowercased_but_company_names_kept_cased():
    # "hey dora," not "hey Dora," — lowercase prose, proper nouns intact.
    p = P(first_name="Dora")
    lead = mk("a", "job_finance_lead", industry="healthcare", city="Denver", state="CO",
              date="2026-07-05", company="Acme BioLabs", finance_grade="medium")
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, {"a": "posted a controller role"}, today=TODAY)
    assert draft.body.startswith("hey dora,\n\n")
    assert "hey Dora," not in draft.body
    # ...but a lead company name (a proper noun, added by code) keeps its casing
    assert "Acme BioLabs, denver:" in draft.body
    # missing first name still falls back to "there"
    assert build_email_1(g, P(first_name=None), {"a": "x"}, today=TODAY).body.startswith("hey there,")


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
    # job_finance_lead keeps its LLM description (funding is templated), so this
    # exercises the date recompute on a real freeform line.
    lead = mk("hc", "job_finance_lead", industry="healthcare", city="Denver", state="CO",
              date="2026-07-05", date_confidence="high", finance_grade="strong")
    p = P()
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, {"hc": "posted a head of finance role"}, today=TODAY)
    assert "posted a head of finance role, 3 days ago" in draft.body


def test_funding_lines_are_templated_not_llm():
    # funding descriptions are code-templated + consistent (#10), never the LLM's
    fd = mk("fd", "funding_form_d", industry="healthcare", city="Denver", state="CO", date="2026-07-05")
    cf = mk("cf", "funding_form_d", industry="healthcare", city="Denver", state="CO", date="2026-07-05")
    cf.signals[0].plain_words_description = "raised via Reg CF equity crowdfunding"
    p = P()
    gfd = build_gift(p, FakeScraper([fd]))
    gcf = build_gift(p, FakeScraper([cf]))
    # the LLM description is ignored for funding leads
    dfd = build_email_1(gfd, p, {"fd": "closed a huge seed round of $9M!!!"}, today=TODAY)
    dcf = build_email_1(gcf, p, {"cf": "whatever the model said"}, today=TODAY)
    assert "just filed to raise, 3 days ago" in dfd.body
    assert "$" not in dfd.body and "9M" not in dfd.body
    assert "just raised via crowdfunding, 3 days ago" in dcf.body

    # a "double" lead (a hire that ALSO filed a raise) is the highest-intent gift:
    # its PRIMARY signal is the hire (kept from the LLM description), and the raise
    # is appended via the honest code template — mentioned, but never a $ figure.
    ds = mk("ds", "job_finance_lead", also_signal="funding_form_d",
            industry="healthcare", city="Denver", state="CO", date="2026-07-05")
    gds = build_gift(p, FakeScraper([ds]))
    dds = build_email_1(gds, p, {"ds": "hiring a senior controller"}, today=TODAY)
    assert "hiring a senior controller" in dds.body       # the hire, from the description
    assert "and just filed to raise" in dds.body          # the raise, code-templated
    assert "$" not in dds.body


def test_5e_low_confidence_date_suppressed():
    # job_fractional_cfo from fractionaljobs.io => date_confidence low => NO date in copy
    lead = mk("cw", "job_fractional_cfo", industry="healthcare", city="Denver", state="CO",
              date="2026-07-05", date_confidence="low", domain=None)
    p = P()
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, {"cw": "is hiring a fractional cfo right now"}, today=TODAY)
    assert "is hiring a fractional cfo right now" in draft.body
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


def test_5e_dollar_amount_stripped_and_flagged():
    # all raises are templated now, so the $-strip safety net runs on the LLM
    # path (hiring/cfo) — e.g. a salary figure the model slips into a role line.
    lead = mk("f", "job_finance_lead", industry="healthcare", city="Denver", state="CO",
              date="2026-07-05", date_confidence="high", finance_grade="medium")
    p = P()
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, {"f": "posted a $200k controller role"}, today=TODAY)
    assert "$" not in draft.body
    assert "200k" not in draft.body
    assert any("dollar amount" in f for f in draft.flags)


# --------------------------------------------------------------------------
# 5e — honesty: domainless + odd-city funding flags
# --------------------------------------------------------------------------

def test_lead_description_forced_lowercase_company_kept_cased():
    # job_finance_lead keeps its LLM description (funding is templated)
    lead = mk("f", "job_finance_lead", industry="healthcare", city="Denver", state="CO",
              date="2026-07-05", company="Acme BioLabs", finance_grade="medium")
    p = P()
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, {"f": "posted a VP of Finance role"}, today=TODAY)
    # description is lowercased in the voice...
    assert "posted a vp of finance role" in draft.body
    assert "VP of Finance" not in draft.body
    # ...but the company name (added by code) keeps its real casing
    assert "Acme BioLabs, denver:" in draft.body


def test_fix_articles_in_lead_lines():
    # a/an corrected in the freeform lead line (#11)
    lead = mk("g", "job_finance_lead", industry="healthcare", city="Denver", state="CO",
              date="2026-07-05", finance_grade="medium")
    p = P()
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, {"g": "posted a assistant controller and a accounting manager"}, today=TODAY)
    assert "posted an assistant controller and an accounting manager" in draft.body


def test_5e_domainless_flag():
    lead = mk("dl", "job_finance_lead", city="Denver", state="CO", domain=None, finance_grade="medium")
    p = P(niched=False)
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, {"dl": "posted a controller role"}, today=TODAY)
    assert any("domainless" in f for f in draft.flags)


def test_5e_odd_city_funding_flag():
    lead = mk("fc", "funding_form_d", city="Denver", state="CO")  # geo will be city
    p = P(niched=False)
    g = build_gift(p, FakeScraper([lead]))
    assert g.geo_level == "city"
    draft = build_email_1(g, p, {"fc": "filed a raise"}, today=TODAY)
    assert any("registered address" in f for f in draft.flags)


# --------------------------------------------------------------------------
# Full Email #1 — niched (Example 1) via the real M1 engine
# --------------------------------------------------------------------------

def test_full_email_niched_example_1():
    p = P(niche_phrase="healthcare startups", first_name="dana")
    leads = [
        mk("h1", "funding_form_d", industry="healthcare", city="Denver", state="CO", date="2026-07-05", company="Acme Bio"),
        mk("h2", "funding_form_d", industry="healthcare", city="Denver", state="CO", date="2026-07-04", company="Nimbus Rx"),
        mk("h3", "job_finance_lead", industry="healthcare", city="Denver", state="CO", date="2026-07-03", company="Vitals Co", finance_grade="medium"),
    ]
    g = build_gift(p, FakeScraper(leads))
    descriptions = {
        "h1": "closed a seed round",
        "h2": "just filed a raise",
        "h3": "posted for a controller",
    }
    draft = build_email_1(g, p, descriptions, today=TODAY, rotation=0)

    assert draft.subject == "healthcare companies in denver that need finance help right now"
    assert draft.body.startswith("hey dana,\n\n")
    assert "saw on your site you work with healthcare, so i pulled 3 healthcare companies" in draft.body
    # a finance-lead hire (rank 1) now outranks the funding leads (rank 2) in the
    # within-level re-sort, so the hiring line is #1 and the two raises follow.
    assert "1. Vitals Co, denver: posted for a controller, 5 days ago" in draft.body   # hire outranks funding
    assert "2. Acme Bio, denver: just filed to raise, 3 days ago" in draft.body        # funding templated
    assert "3. Nimbus Rx, denver: just filed to raise, 4 days ago" in draft.body
    assert LEFT_FIELD[0] in draft.body
    assert "want me to keep an eye out for healthcare ones and send them your way?" in draft.body
    assert draft.body.endswith("best,\nishaan")
    # funding leads in a city-claim gift raise the registered-address flag
    assert any("registered address" in f for f in draft.flags)


# --------------------------------------------------------------------------
# Full Email #1 — generalist (Example 8) via the real M1 engine
# --------------------------------------------------------------------------

def test_full_email_generalist_example_8():
    p = P(niched=False, city="Miami", state="FL", first_name="sam")
    leads = [
        mk("m1", "job_finance_lead", city="Miami", state="FL", date="2026-07-06", company="Palm Freight", finance_grade="strong"),
        mk("m2", "job_finance_lead", city="Miami", state="FL", date="2026-07-05", company="Bay Foods", finance_grade="medium"),
    ]
    g = build_gift(p, FakeScraper(leads))
    draft = build_email_1(g, p, {"m1": "posted a VP of finance role", "m2": "posted a controller role"}, today=TODAY, rotation=1)

    assert draft.subject == "companies in miami hiring finance leadership right now"
    assert "saw you're based in miami, so i pulled 2 companies in miami" in draft.body
    assert "1. Palm Freight, miami: posted a vp of finance role, 2 days ago" in draft.body  # forced lowercase
    assert "2. Bay Foods, miami: posted a controller role, 3 days ago" in draft.body
    assert "want me to keep an eye out for miami ones and send them your way?" in draft.body
    # ZERO niche words anywhere — subject AND body — for a generalist
    assert_no_niche_claim(draft.subject + "\n" + draft.body)


# --------------------------------------------------------------------------
# Single-lead gift folds in (no numbering); job_fractional_cfo date suppressed (Ex 5/7)
# --------------------------------------------------------------------------

def test_single_lead_not_numbered():
    p = P(niche="ecommerce_retail", city="Nashville", state="TN", first_name="lee")
    lead = mk("mem", "funding_form_d", industry="ecommerce_retail", city="Memphis", state="TN", date="2026-07-05", company="River Goods")
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, {"mem": "just filed a raise"}, today=TODAY)
    assert g.gift_size == 1
    assert draft.subject == "an ecommerce company in tennessee just raised"
    assert "River Goods, memphis: just filed to raise, 3 days ago" in draft.body   # funding templated
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
        firm_name="Paws & Ledgers", city="Denver", state="CO",
        classification="niched", match_param=("niche", "pet_grooming"),
        niche_phrase="pet grooming shops", niche_source="site", first_name="jo",
    )
    leads = [
        mk("p1", "funding_form_d", niche="pet_grooming", city="Denver", state="CO", date="2026-07-05", company="Fluff Co"),
        mk("p2", "job_finance_lead", niche="pet_grooming", city="Denver", state="CO", date="2026-07-04", company="Shear Joy", finance_grade="medium"),
    ]
    g = build_gift(p, FakeScraper(leads))
    assert g.all_niche is True                       # gift really is on-niche...
    draft = build_email_1(g, p, {"p1": "closed a round", "p2": "posted a controller role"}, today=TODAY)

    # ...but the copy is generalist, because the token has no label.
    assert draft.subject == "companies in denver that need finance help right now"
    assert "saw you're based in denver, so i pulled 2 companies in denver" in draft.body
    assert "want me to keep an eye out for denver ones and send them your way?" in draft.body
    for banned in ("pet_grooming", "pet grooming", "pet grooming shops"):
        assert banned not in (draft.subject + "\n" + draft.body)
    assert_no_niche_claim(draft.subject + "\n" + draft.body)


def test_cfo_wanted_gift_flags_live_check():
    p = P(niched=False, city="Chicago", state="IL", first_name="ray")
    leads = [
        mk("cfo", "job_fractional_cfo", city="Chicago", state="IL", date="2026-06-20", date_confidence="low", domain=None, company="Loop Labs"),
        mk("c1", "funding_form_d", city="Chicago", state="IL", date="2026-07-05", company="Windy Co"),
        mk("c2", "job_finance_lead", city="Chicago", state="IL", date="2026-07-04", company="Deep Dish Inc", finance_grade="medium"),
    ]
    g = build_gift(p, FakeScraper(leads))
    draft = build_email_1(g, p, {"cfo": "is hiring a fractional cfo right now", "c1": "closed a round", "c2": "posted a controller role"}, today=TODAY)
    assert draft.subject == "a company in chicago is hiring a fractional cfo"
    assert any("confirm it's still live" in f for f in draft.flags)
    assert any("domainless" in f for f in draft.flags)
