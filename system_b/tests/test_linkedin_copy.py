"""LinkedIn DM copy — the second channel, held to the email's rules.

The DMs are the one place a false claim would be pasted by hand weeks after it
was generated, so these cover the two things that can go wrong: claiming a
vertical the gift does not support, and asserting a role that has since closed.
"""

from __future__ import annotations

from system_b.copy.linkedin import (
    build_dm_1,
    build_dm_1_evergreen,
    build_dm_2,
)
from system_b.gift.engine import build_gift
from system_b.gift.models import Prospect
from system_b.niches.base import pack_for
from system_b.tests.test_gift import FakeScraper, mk

DASHES = "‒–—―"


def _niched():
    prospect = Prospect(firm_name="C-Suite Support Council", city=None, state=None,
                        classification="niched", match_param=("industry", "real_estate"),
                        first_name="Paul")
    leads = [
        mk("l1", "job_finance_lead", industry="real_estate", city="Benicia", state="CA",
           date="2026-08-03", company="Twin Oaks Real Estate",
           evidence="Founding Head of Finance & Strategy"),
        mk("l2", "job_finance_lead", industry="real_estate", city="Dallas", state="TX",
           date="2026-07-25", company="Elm Grove Companies", evidence="Chief Financial Officer"),
    ]
    sc = FakeScraper(leads)
    return prospect, build_gift(prospect, sc, niche_only=True, pack=pack_for("cfo"))


def _generalist():
    prospect = Prospect(firm_name="AT3 Agency", city="Atlanta", state="GA",
                        classification="generalist", first_name="Arthur")
    leads = [
        mk("a1", "job_finance_lead", city="Atlanta", state="GA", date="2026-08-03",
           company="Agora Exchange", evidence="Director of Accounting"),
    ]
    sc = FakeScraper(leads)
    return prospect, build_gift(prospect, sc, pack=pack_for("cfo"))


# --- DM #1, fresh ----------------------------------------------------------

def test_dm_1_opens_like_email_1_and_names_one_company():
    prospect, gift = _niched()
    dm = build_dm_1(gift, prospect, pack=pack_for("cfo"))
    assert dm.startswith("hey paul, noticed you work with real estate companies,")
    assert "just posted a finance role" in dm
    assert "Twin Oaks Real Estate in benicia" in dm     # company keeps its casing
    assert "hiring a founding head of finance & strategy" in dm
    assert "built this one for fractional cfos" in dm
    assert "would 15 min work" in dm                     # every touch asks for the call
    assert "Elm Grove" not in dm                         # ONE company, not the gift


def test_dm_1_falls_back_to_geography_for_a_generalist():
    prospect, gift = _generalist()
    dm = build_dm_1(gift, prospect, pack=pack_for("cfo"))
    assert dm.startswith("hey arthur, saw you're based in atlanta,")
    assert "Agora Exchange in atlanta" in dm
    # a generalist never gets a vertical claim, on either channel
    for banned in ("real estate", "healthcare", "companies posting"):
        assert banned not in dm


def test_dm_1_never_claims_a_niche_the_gift_does_not_support():
    """Same gate as the subject and framing: a niched prospect whose gift is
    filled from geography (all_niche False) gets no vertical claim."""
    prospect = Prospect(firm_name="Acme CFOs", city="Denver", state="CO",
                        classification="niched", match_param=("industry", "construction"),
                        first_name="dana")
    leads = [mk("x1", "job_finance_lead", industry="manufacturing", city="Denver",
                state="CO", date="2026-08-03", company="Off Niche Co",
                evidence="Controller")]
    gift = build_gift(prospect, FakeScraper(leads), pack=pack_for("cfo"))
    assert gift is not None and not gift.all_niche
    dm = build_dm_1(gift, prospect, pack=pack_for("cfo"))
    assert "construction" not in dm
    assert "saw you're based in denver" in dm


def test_dm_1_falls_back_to_evergreen_for_a_non_job_lead():
    """A breach describes an event, not an open role, so "just posted a security
    role" would be false. The fresh shape refuses rather than mis-templating."""
    prospect = Prospect(firm_name="Acme Security", city="Denver", state="CO",
                        classification="generalist", first_name="dana")
    leads = [mk("b1", "breach_disclosed", city="Denver", state="CO",
                date="2026-08-03", company="Breached Co",
                evidence="Breached Co reported a data breach")]
    pack = pack_for("mssp")
    gift = build_gift(prospect, FakeScraper(leads), pack=pack)
    dm = build_dm_1(gift, prospect, pack=pack)
    assert "just posted" not in dm
    assert "Breached Co" not in dm
    assert dm == build_dm_1_evergreen(gift, prospect, pack=pack)


# --- DM #1, evergreen ------------------------------------------------------

def test_evergreen_names_nothing_that_can_go_stale():
    """The reason this variant exists: a connection accepted six weeks later
    would otherwise be told a filled role is open."""
    prospect, gift = _niched()
    dm = build_dm_1_evergreen(gift, prospect, pack=pack_for("cfo"))
    assert "noticed you work with real estate companies." in dm
    assert "flags real estate companies posting finance roles" in dm
    assert "Twin Oaks" not in dm and "benicia" not in dm
    assert "just posted" not in dm and "hiring" not in dm
    # the ask survives — the whole point of the touch is still the call
    assert "would 15 min work" in dm


def test_evergreen_uses_geography_when_there_is_no_vertical():
    prospect, gift = _generalist()
    dm = build_dm_1_evergreen(gift, prospect, pack=pack_for("cfo"))
    assert "flags atlanta companies posting finance roles" in dm
    assert "Agora Exchange" not in dm


# --- DM #2 + house style ---------------------------------------------------

def test_dm_2_is_constant_and_lead_free():
    assert build_dm_2() == build_dm_2()
    body = build_dm_2()
    assert "no worries if leads aren't what you're short on" in body
    assert "worth 15 min?" in body


def test_no_dm_contains_an_em_dash_or_shouts():
    prospect, gift = _niched()
    pack = pack_for("cfo")
    for dm in (build_dm_1(gift, prospect, pack=pack),
               build_dm_1_evergreen(gift, prospect, pack=pack),
               build_dm_2()):
        assert not any(c in dm for c in DASHES)
        # prose is lowercase; only proper nouns (company names) keep their casing
        assert dm[0].islower()
        prose = dm.replace("Twin Oaks Real Estate", "")
        assert not any(w[:1].isupper() for w in prose.split())


def test_every_pack_can_render_both_dms():
    """Each pack supplies its own audience and role words; a missing one would
    render 'built this one for None.'"""
    prospect, gift = _generalist()
    for key in ("cfo", "accounting", "msp", "mssp", "cloud"):
        pack = pack_for(key)
        for dm in (build_dm_1(gift, prospect, pack=pack),
                   build_dm_1_evergreen(gift, prospect, pack=pack)):
            assert "None" not in dm
            assert pack.dm_audience in dm
